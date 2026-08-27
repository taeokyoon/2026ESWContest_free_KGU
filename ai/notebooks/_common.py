"""공통 유틸 — 데이터 경로 해석, 가중치 파싱, 특성 파이프라인, 순전파.

데이터셋 위치는 아래 순서로 찾는다.
  1) 환경변수 VIDS_DATA
  2) ai/data/
  3) 레포 상위 두 단계까지 재귀 탐색
CSV 파일명만 알면 되므로 폴더 구조(0_Preliminary/... 등)에 의존하지 않는다.

전처리 상수는 ai/export/feature_extract.c에 하드코딩된 값과 반드시 같아야 한다.
평가 시 재계산하지 않고 이 상수를 쓴다 — 보드가 그렇게 동작하기 때문이다.
"""
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / "ai" / "export"
CACHE = REPO / "ai" / "data" / "cache"

WINDOW = 32
FEATURES_PER_FRAME = 11
INPUT_DIM = 354

ID_DELTA_T_MEDIAN = 0.01022195816040039
ID_DELTA_T_LOG_MIN = 0.06283380660796888
ID_DELTA_T_LOG_MAX = 11.873697951933963

LAYER_DIMS = {0: (354, 64), 1: (64, 16), 2: (16, 64), 3: (64, 354)}

TRAIN_FILES = [f"Pre_train_{s}_{i}.csv" for s in ("D", "S") for i in range(3)]
HELDOUT_FILES = ["Pre_submit_D.csv", "Pre_submit_S.csv", "Fin_host_session_submit_S.csv"]

_csv_index = None


def _build_csv_index():
    roots = []
    if os.environ.get("VIDS_DATA"):
        roots.append(Path(os.environ["VIDS_DATA"]))
    roots += [REPO / "ai" / "data", REPO.parent]
    index = {}
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*.csv"):
            index.setdefault(p.name, p)
    return index


def find_csv(name):
    global _csv_index
    if _csv_index is None:
        _csv_index = _build_csv_index()
    if name not in _csv_index:
        raise FileNotFoundError(
            f"{name} 을 찾지 못했습니다. 데이터셋 폴더를 VIDS_DATA 환경변수로 지정하세요.\n"
            f"  예: export VIDS_DATA=~/eswc/'Car Hacking Challenge Dataset Mar 2021'"
        )
    return _csv_index[name]


def parse_weight_header(path):
    """const <type> <name>[N] = {...};  ->  {name: np.ndarray}"""
    text = Path(path).read_text()
    out = {}
    for m in re.finditer(
        r"const\s+(?:float|signed\s+char)\s+(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{(.*?)\}\s*;",
        text, re.S,
    ):
        name, n, body = m.group(1), int(m.group(2)), m.group(3)
        vals = np.array([float(v) for v in body.replace("f", "").split(",") if v.strip()])
        if len(vals) != n:
            raise ValueError(f"{name}: 선언 {n} vs 실제 {len(vals)}")
        out[name] = vals
    return out


def parse_defines(path):
    return {
        m.group(1): float(m.group(2))
        for m in re.finditer(r"#define\s+(\w+)\s+([0-9.eE+-]+)f", Path(path).read_text())
    }


def load_quantized_weights():
    """firmware가 실제로 쓰는 int8 가중치를 (W, b, scale) 형태로 돌려준다."""
    q = parse_weight_header(EXPORT / "autoencoder_v5_weights_int8.h")
    sc = parse_defines(EXPORT / "autoencoder_v5_weights_int8.h")
    W, b, scales, Wq = {}, {}, {}, {}
    for i, (din, dout) in LAYER_DIMS.items():
        s = sc[f"layer{i}_scale"]
        Wq[i] = q[f"layer{i}_weight_q"].reshape(din, dout).astype(np.int32)
        W[i] = (Wq[i] * s).astype(np.float32)
        b[i] = q[f"layer{i}_bias"].astype(np.float32)
        scales[i] = s
    return W, b, scales, Wq


def load_float_weights():
    f = parse_weight_header(EXPORT / "autoencoder_v5_weights.h")
    W = {i: f[f"layer{i}_weight"].reshape(*LAYER_DIMS[i]).astype(np.float32) for i in LAYER_DIMS}
    b = {i: f[f"layer{i}_bias"].astype(np.float32) for i in LAYER_DIMS}
    return W, b


def build_features(df, boundaries, recompute_norm=False):
    """프레임 단위 11특성. recompute_norm=True면 정규화 상수를 데이터에서 재계산(검산용)."""
    lut = {f"{i:02X}": i for i in range(256)}
    parts = df["Data"].str.split(" ", expand=True)
    for c in range(8):
        if c not in parts.columns:
            parts[c] = None
    parts = parts[list(range(8))].fillna("00")
    data_bytes = np.stack(
        [parts[c].map(lut).to_numpy(dtype=np.float64) for c in range(8)], 1
    ) / 255.0

    id_int = df["Arbitration_ID"].map(lambda x: int(x, 16)).to_numpy()
    id_norm = id_int / 0x7FF
    dlc_norm = df["DLC"].to_numpy(dtype=np.float64) / 8.0

    file_id = np.zeros(len(df), dtype=int)
    for i, (s, e) in enumerate(zip(boundaries[:-1], boundaries[1:])):
        file_id[s:e] = i
    df = df.assign(file_id=file_id)

    dt = df.groupby(["file_id", "Arbitration_ID"])["Timestamp"].diff()
    if recompute_norm:
        median = float(dt.median())
        dt_log = np.log1p(dt.fillna(median).to_numpy() * 1000.0)
        lo, hi = float(dt_log.min()), float(dt_log.max())
    else:
        median, lo, hi = ID_DELTA_T_MEDIAN, ID_DELTA_T_LOG_MIN, ID_DELTA_T_LOG_MAX
        dt_log = np.log1p(dt.fillna(median).to_numpy() * 1000.0)
    dt_norm = np.clip((dt_log - lo) / (hi - lo), 0.0, 1.0)

    feats = np.column_stack([id_norm, dlc_norm, data_bytes, dt_norm])
    return feats, id_int, {"median": median, "log_min": lo, "log_max": hi}


def windowize(feats, id_int, labels, boundaries, shuffle_ids=None, drop_id=False):
    """32프레임 비중첩 윈도우 -> (X[n,354], 윈도우별 라벨 배열들)

    shuffle_ids: id_norm 열을 무작위 치환할 rng (shortcut learning 감사용)
    drop_id:     id_norm 열을 0으로 만듦
    """
    Xs, uniq, rep = [], [], []
    lab_out = {k: [] for k in labels}
    for s, e in zip(boundaries[:-1], boundaries[1:]):
        n = (e - s) // WINDOW
        if n == 0:
            continue
        end = s + n * WINDOW
        blk = feats[s:end].reshape(n, WINDOW, FEATURES_PER_FRAME).copy()
        if drop_id:
            blk[:, :, 0] = 0.0
        elif shuffle_ids is not None:
            blk[:, :, 0] = shuffle_ids.permutation(blk[:, :, 0].ravel()).reshape(blk.shape[:2])
        Xs.append(blk.reshape(n, WINDOW * FEATURES_PER_FRAME))
        ids = id_int[s:end].reshape(n, WINDOW)
        for row in ids:
            _, counts = np.unique(row, return_counts=True)
            uniq.append(len(counts) / WINDOW)
            rep.append(counts.max() / WINDOW)
        for k, v in labels.items():
            lab_out[k].append(v[s:end].reshape(n, WINDOW))
    X = np.vstack(Xs)
    X = np.hstack([X, np.array(uniq)[:, None], np.array(rep)[:, None]])
    return X, {k: np.vstack(v) for k, v in lab_out.items()}


def load_windows(files, cache_name, recompute_norm=False, **kw):
    """CSV 목록 -> 윈도우 배열. 결과를 ai/data/cache/ 에 저장(gitignore 대상)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    # recompute_norm 을 캐시 키에 포함해야 한다. 빠뜨리면 02의 상수 검산이
    # 하드코딩된 값을 그대로 읽어 무조건 통과하는 공허한 테스트가 된다.
    suffix = "_recalc" if recompute_norm else ""
    cache = CACHE / f"{cache_name}{suffix}.npz"
    if cache.exists() and not kw:
        z = np.load(cache, allow_pickle=True)
        lab = {k: z[k] for k in z.files if k not in ("X", "consts")}
        consts = dict(z["consts"].item()) if "consts" in z.files else {}
        return z["X"], lab, consts

    frames, boundaries = [], [0]
    for f in files:
        d = pd.read_csv(find_csv(f), dtype={"Arbitration_ID": str, "Data": str})
        if "SubClass" not in d.columns:
            d["SubClass"] = np.nan
        frames.append(d)
        boundaries.append(boundaries[-1] + len(d))
    df = pd.concat(frames, ignore_index=True)
    del frames
    df["SubClass"] = df["SubClass"].fillna("Normal")
    boundaries = np.array(boundaries)

    feats, id_int, consts = build_features(df, boundaries, recompute_norm)
    labels = {
        "is_attack": (df["Class"].to_numpy() == "Attack"),
        "subclass": df["SubClass"].to_numpy().astype("U10"),
    }
    del df
    X, lab = windowize(feats, id_int, labels, boundaries, **kw)
    del feats

    if not kw:
        np.savez_compressed(cache, X=X, consts=np.array(consts, dtype=object), **lab)
    return X, lab, consts


def relu(x):
    return np.maximum(x, 0)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def forward_float(X, W, b, batch=20000):
    """inference.c 와 동일한 순서의 float32 순전파."""
    outs = []
    for i in range(0, len(X), batch):
        h = X[i:i + batch].astype(np.float32)
        for l in range(4):
            h = h @ W[l] + b[l]
            h = relu(h) if l < 3 else sigmoid(h)
        outs.append(h)
    return np.vstack(outs)


def scores(X, out):
    """채점 A(354차원 평균) / B(마지막 2차원 평균) 재구성오차."""
    Xf = X.astype(np.float32)
    d = Xf - out
    return (d ** 2).mean(1), (d[:, -2:] ** 2).mean(1)


def window_labels(lab):
    """프레임 라벨 -> 윈도우 라벨 (하나라도 공격이면 공격)."""
    y = lab["is_attack"].any(1)
    sub = np.full(len(y), "Normal", dtype="U10")
    for t in ("Flooding", "Fuzzing", "Replay", "Spoofing"):
        m = (lab["subclass"] == t).any(1)
        sub[m & (sub == "Normal")] = t
    return y, sub


# ---------------------------------------------------------------- 평가 지표

ATTACK_TYPES = ("Flooding", "Fuzzing", "Replay", "Spoofing")


def apply_k_consecutive(raw, k):
    """k회 연속 양성일 때만 경보. 산발적 오탐을 걸러내고 지속형 공격만 남긴다."""
    if k <= 1:
        return raw.copy()
    fire = raw.copy()
    for j in range(1, k):
        fire[j:] &= raw[:-j]
    fire[:k - 1] = False
    return fire


def find_episodes(mask):
    """연속된 True 구간을 (start, end) 목록으로. end는 배타적."""
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def window_metrics(fire, y, sub):
    """윈도우 단위: 공격유형별 탐지율 + 오탐률."""
    det = {t: float(fire[y & (sub == t)].mean()) for t in ATTACK_TYPES if (sub == t).any()}
    return det, float(fire[~y].mean())


def episode_metrics(fire, sub):
    """에피소드 단위: 공격 한 번에 경보가 한 번이라도 울렸는가."""
    out = {}
    for t in ATTACK_TYPES:
        eps = find_episodes(sub == t)
        if not eps:
            continue
        hit = sum(1 for s, e in eps if fire[s:e].any())
        out[t] = (hit / len(eps), len(eps))
    return out


def frame_metrics(fire, lab):
    """프레임 단위: 윈도우 판정을 32프레임에 전파해 P/R/F1. 대회 공식 채점 단위."""
    pred = np.repeat(fire, WINDOW)
    truth = lab["is_attack"].ravel()
    tp = int((pred & truth).sum())
    fp = int((pred & ~truth).sum())
    fn = int((~pred & truth).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def injection_density(lab, sub):
    """공격 윈도우 안에서 실제 공격 프레임이 차지하는 비율 (단일유형 윈도우 기준)."""
    out = {}
    sc = lab["subclass"]
    for t in ATTACK_TYPES:
        m = sc == t
        rows = m.any(1)
        pure = rows & (((sc != "Normal") & (sc != t)).sum(1) == 0)
        if pure.any():
            out[t] = float(m[pure].sum(1).mean() / WINDOW)
    return out
