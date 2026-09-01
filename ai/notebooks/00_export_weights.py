"""학습 산출물(.keras) -> C 가중치 헤더. 변환 도구가 없는 경로를 코드로 남긴다.

scale 은 float32 연산으로 구한다. float64 로 나누면 소수점 10번째 자리가 달라져
기존 헤더와 바이트 단위로 일치하지 않는다(값 차이는 3e-8 로 무해하지만 대조가 흐려진다).

X-CUBE-AI / STM32Cube AI Studio 가 Cortex-M3 를 지원하지 않아 자동 변환 경로가 막혀 있다.
이 스크립트가 그 도구의 역할(가중치 추출 + 대칭 int8 양자화 + C 배열 생성)을 대신한다.

    python3 00_export_weights.py            # 기존 헤더와 대조만 (파일을 쓰지 않음)
    python3 00_export_weights.py --write    # ai/export/ 에 헤더를 다시 생성

TensorFlow 를 설치하지 않아도 된다. `.keras` 는 zip 이고 그 안의 `model.weights.h5` 를
h5py 로 직접 읽는다.
"""
import io
import json
import sys
import zipfile

import h5py
import numpy as np

import _common as C

KERAS = C.REPO / "ai" / "models" / "autoencoder_v5.keras"
H5_ORDER = ["dense", "dense_1", "dense_2", "dense_3"]


def load_keras(path):
    z = zipfile.ZipFile(path)
    cfg = json.loads(z.read("config.json"))
    dense = [l["config"] for l in cfg["config"]["layers"] if l["class_name"] == "Dense"]
    f = h5py.File(io.BytesIO(z.read("model.weights.h5")), "r")
    W, b, names, acts = {}, {}, [], []
    for i, g in enumerate(H5_ORDER):
        W[i] = np.array(f["layers"][g]["vars"]["0"], dtype=np.float32)
        b[i] = np.array(f["layers"][g]["vars"]["1"], dtype=np.float32)
        names.append(dense[i]["name"])
        acts.append(dense[i]["activation"])
    return W, b, names, acts


def emit_float(W, b, names):
    L = ["#ifndef AUTOENCODER_V5_WEIGHTS_H", "#define AUTOENCODER_V5_WEIGHTS_H", ""]
    for i in sorted(W):
        din, dout = W[i].shape
        L.append(f"// Layer {i}: {names[i]}, input {din} -> output {dout}")
        v = ", ".join(f"{x:.8f}f" for x in W[i].ravel())
        L.append(f"const float layer{i}_weight[{W[i].size}] = {{{v}}};")
        v = ", ".join(f"{x:.8f}f" for x in b[i])
        L.append(f"const float layer{i}_bias[{b[i].size}] = {{{v}}};")
        L.append("")
    L += ["#endif"]
    return "\n".join(L) + "\n"


def emit_int8(W, b, names):
    L = ["#ifndef AUTOENCODER_V5_WEIGHTS_Q_H", "#define AUTOENCODER_V5_WEIGHTS_Q_H", ""]
    for i in sorted(W):
        din, dout = W[i].shape
        s = np.float32(np.abs(W[i]).max() / np.float32(127.0))
        q = np.clip(np.round(W[i] / s), -127, 127).astype(np.int32)
        L.append(f"// Layer {i}: {names[i]}, input {din} -> output {dout}")
        L.append(f"#define layer{i}_scale {s:.10f}f")
        v = ", ".join(str(int(x)) for x in q.ravel())
        L.append(f"const signed char layer{i}_weight_q[{q.size}] = {{{v}}};")
        v = ", ".join(f"{x:.8f}f" for x in b[i])
        L.append(f"const float layer{i}_bias[{b[i].size}] = {{{v}}};")
        L.append("")
    L += ["#endif"]
    return "\n".join(L) + "\n"


def main():
    write = "--write" in sys.argv
    W, b, names, acts = load_keras(KERAS)

    print(f"=== {KERAS.name} ===")
    for i in sorted(W):
        print(f"  layer{i} {names[i]:10s} {W[i].shape[0]:>3} -> {W[i].shape[1]:<3} "
              f"{acts[i]:8s} 가중치 {W[i].size:>6,}  bias {b[i].size:>3}")
    got = {i: W[i].shape for i in W}
    if got != {i: C.LAYER_DIMS[i] for i in C.LAYER_DIMS}:
        print(f"  ✗ 구조 불일치: {got} vs {C.LAYER_DIMS}")
        return 1
    print(f"  구조가 _common.LAYER_DIMS 와 일치")

    ok = True
    for name, text in (("autoencoder_v5_weights.h", emit_float(W, b, names)),
                       ("autoencoder_v5_weights_int8.h", emit_int8(W, b, names))):
        path = C.EXPORT / name
        old = path.read_text() if path.exists() else None
        same = old == text
        ok &= same
        print(f"\n=== {name} ===")
        print(f"  생성 {len(text):,} B / 기존 {len(old):,} B" if old else "  기존 파일 없음")
        print(f"  {'✅ 완전 일치' if same else '⚠️ 텍스트 불일치 — 아래 수치 대조 확인'}")
        if write:
            path.write_text(text)
            print(f"  -> {path} 갱신")

    if not ok:
        print("\n=== 수치 대조 (텍스트가 달라도 값이 같으면 무해) ===")
        f32 = C.parse_weight_header(C.EXPORT / "autoencoder_v5_weights.h")
        q8 = C.parse_weight_header(C.EXPORT / "autoencoder_v5_weights_int8.h")
        sc = C.parse_defines(C.EXPORT / "autoencoder_v5_weights_int8.h")
        for i in sorted(W):
            s = np.float32(np.abs(W[i]).max() / np.float32(127.0))
            q = np.clip(np.round(W[i] / s), -127, 127)
            dw = np.abs(f32[f"layer{i}_weight"] - W[i].ravel()).max()
            db = np.abs(f32[f"layer{i}_bias"] - b[i]).max()
            nq = int((q8[f"layer{i}_weight_q"] != q.ravel()).sum())
            ds = abs(s - sc[f"layer{i}_scale"]) / sc[f"layer{i}_scale"]
            print(f"  layer{i}  float 최대차 {dw:.2e}  bias {db:.2e}  "
                  f"int8 불일치 {nq:,}/{q.size:,}  scale 오차 {ds:.1e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
