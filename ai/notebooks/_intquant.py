"""정수 추론 커널 — C 구현이 그대로 따라할 수 있는 형태로 작성한다.

설계
  활성값 : int16, 레이어별 스케일 Sa  (입력·은닉·출력 모두 비음수라 0..32767 사용)
  가중치 : int8,  레이어별 스케일 Sw  (기존 헤더 그대로)
  누산   : int32, acc = sum(a_q * w_q) + b_q,  b_q = round(b / (Sa*Sw))
  재양자화: a_next = round(acc * M),  M = Sa*Sw / Sa_next 를 고정소수점(M0, shift)로

입력과 출력은 **같은 스케일**(1/32767)을 쓴다. 그래야 재구성 오차를 정수 뺄셈으로
그대로 계산할 수 있고, 임계값도 정수로 미리 환산해 비교만 하면 된다.
"""
import numpy as np

ACT_MAX = 32767
W_MAX = 127
IO_SCALE = 1.0 / ACT_MAX  # 입력·출력 공통 (둘 다 [0,1] 범위)

# 출력층 pre-activation 실측 범위는 -8.854 ~ 7.929 (train+attack 2만 윈도우).
# [-8,8]로 자르면 하단이 잘려 오차 2.9e-4가 나오므로 [-12,12]로 넓힌다.
# 표본 간격 24/512 = 0.0469 -> 선형보간 오차 약 2.6e-5.
SIG_LUT_N = 513
SIG_LUT_LO = -12.0
SIG_LUT_HI = 12.0


def fixed_point_multiplier(m):
    """실수 승수 m -> (M0:int32, shift:int) 로 분해.  m ≈ M0 * 2**-shift"""
    if m <= 0:
        raise ValueError("승수는 양수여야 한다")
    shift = 0
    while m < 0.5:
        m *= 2.0
        shift += 1
    while m >= 1.0:
        m /= 2.0
        shift -= 1
    m0 = int(round(m * (1 << 31)))
    if m0 == (1 << 31):
        m0 //= 2
        shift -= 1
    return m0, shift + 31


def apply_multiplier(acc, m0, shift):
    """acc * M0 >> shift, 반올림 포함. C에서는 int64 임시값 1회로 구현된다."""
    prod = acc.astype(np.int64) * np.int64(m0)
    if shift <= 0:
        return prod << np.int64(-shift)
    half = np.int64(1) << np.int64(shift - 1)
    return (prod + half) >> np.int64(shift)


def build_sigmoid_lut():
    """[SIG_LUT_LO, SIG_LUT_HI] 등간격 표. 출력은 int16(스케일 IO_SCALE)."""
    xs = np.linspace(SIG_LUT_LO, SIG_LUT_HI, SIG_LUT_N)
    ys = 1.0 / (1.0 + np.exp(-xs))
    return np.clip(np.round(ys / IO_SCALE), 0, ACT_MAX).astype(np.int32), xs


def sigmoid_lut_eval(x, lut):
    """실수 입력용 선형보간 (검증·오차측정 전용). 구간 밖은 포화."""
    step = (SIG_LUT_HI - SIG_LUT_LO) / (SIG_LUT_N - 1)
    t = np.clip((x - SIG_LUT_LO) / step, 0, SIG_LUT_N - 1 - 1e-9)
    i = t.astype(np.int64)
    frac = t - i
    lo = lut[i].astype(np.float64)
    hi = lut[np.minimum(i + 1, SIG_LUT_N - 1)].astype(np.float64)
    return np.clip(np.floor(lo + (hi - lo) * frac + 0.5), 0, ACT_MAX).astype(np.int32)


FRAC_BITS = 8  # LUT 인덱스의 소수부 비트 수 (8.8 고정소수점)


def sigmoid_index_multiplier(prescale):
    """출력층 acc -> LUT 인덱스(8.8 고정소수점) 변환 승수.

    pre  = acc * prescale
    t    = (pre - LO) / step              (LUT 인덱스, 실수)
    t<<8 = acc * (prescale/step * 256) + (-LO/step * 256)
    앞항의 계수를 (M0, SH)로 분해하고, 뒷항은 상수 오프셋으로 더한다.
    """
    step = (SIG_LUT_HI - SIG_LUT_LO) / (SIG_LUT_N - 1)
    m0, sh = fixed_point_multiplier(prescale / step * (1 << FRAC_BITS))
    offset = int(round(-SIG_LUT_LO / step * (1 << FRAC_BITS)))
    return m0, sh, offset


def sigmoid_lut_int(acc, lut, m0, sh, offset):
    """C 구현과 비트 단위로 동일한 정수 sigmoid. acc(int64) -> int16."""
    idx = apply_multiplier(acc, m0, sh) + np.int64(offset)
    hi_lim = np.int64((SIG_LUT_N - 1) << FRAC_BITS)
    idx = np.clip(idx, 0, hi_lim)
    i = (idx >> FRAC_BITS).astype(np.int64)
    frac = idx & np.int64((1 << FRAC_BITS) - 1)
    i2 = np.minimum(i + 1, SIG_LUT_N - 1)
    lo = lut[i].astype(np.int64)
    d = lut[i2].astype(np.int64) - lo
    return np.clip(lo + ((d * frac) >> FRAC_BITS), 0, ACT_MAX).astype(np.int32)


class IntModel:
    """calibrate() 로 스케일을 잡고 forward() 로 정수 추론을 수행한다."""

    def __init__(self, Wq, b, w_scales, dims):
        self.Wq = {i: Wq[i].astype(np.int32) for i in dims}
        self.b = b
        self.w_scales = w_scales
        self.dims = dims
        self.act_scale = None
        self.b_q = None
        self.mult = None
        self.sig_lut = None
        self.sig_mult = None
        self.out_prescale = None
        self.acc_max = {}

    def calibrate(self, X_calib, percentile=100.0):
        """활성값 스케일 산출. 입력·출력은 IO_SCALE 고정, 은닉층만 데이터로 잡는다."""
        act_scale = {"in": IO_SCALE, "out": IO_SCALE}
        h = X_calib.astype(np.float64)
        for l in range(3):  # 은닉층 3개 (h0, h1, h2)
            h = np.maximum(h @ (self.Wq[l] * self.w_scales[l]) + self.b[l], 0.0)
            hi = np.percentile(h, percentile) if percentile < 100 else h.max()
            act_scale[f"h{l}"] = float(hi) / ACT_MAX
        self.act_scale = act_scale

        names_in = ["in", "h0", "h1", "h2"]
        names_out = ["h0", "h1", "h2", "out"]
        self.b_q, self.mult = {}, {}
        for l in range(4):
            sa = act_scale[names_in[l]]
            sw = self.w_scales[l]
            self.b_q[l] = np.round(self.b[l].astype(np.float64) / (sa * sw)).astype(np.int64)
            if l < 3:
                self.mult[l] = fixed_point_multiplier(sa * sw / act_scale[names_out[l]])
            else:
                self.mult[l] = None  # 출력층은 sigmoid LUT 입력용 실수 변환이 필요
        self.sig_lut, _ = build_sigmoid_lut()
        self.out_prescale = act_scale["h2"] * self.w_scales[3]
        self.sig_mult = sigmoid_index_multiplier(self.out_prescale)
        return act_scale

    def quantize_input(self, X):
        """C와 동일하게 round-half-up (floor(x+0.5))."""
        return np.clip(np.floor(X.astype(np.float64) / IO_SCALE + 0.5), 0, ACT_MAX).astype(np.int32)

    def forward(self, X, batch=8192, track_acc=False):
        """정수 순전파. 반환값은 출력층 int16 배열."""
        outs = []
        for s in range(0, len(X), batch):
            a = self.quantize_input(X[s:s + batch])
            for l in range(4):
                # float64 가수 53비트 > 실제 누산 최대 1.5e9(31비트)라 정수 결과가 비트 단위로 정확.
                # numpy 정수 matmul은 BLAS를 안 타서 수십 배 느리므로 float64로 계산 후 되돌린다.
                acc = (a.astype(np.float64) @ self.Wq[l].astype(np.float64)).astype(np.int64)
                acc += self.b_q[l]
                if track_acc:
                    self.acc_max[l] = max(self.acc_max.get(l, 0), int(np.abs(acc).max()))
                if l < 3:
                    acc = np.maximum(acc, 0)
                    a = np.clip(apply_multiplier(acc, *self.mult[l]), 0, ACT_MAX).astype(np.int32)
                else:
                    a = sigmoid_lut_int(acc, self.sig_lut, *self.sig_mult)
            outs.append(a)
        return np.vstack(outs)


def int_scores(X, out_q):
    """정수 도메인 재구성 오차. 반환은 (sum_sq_full:int64, sum_sq_last2:int64)."""
    in_q = np.clip(np.floor(X.astype(np.float64) / IO_SCALE + 0.5), 0, ACT_MAX).astype(np.int64)
    d = in_q - out_q.astype(np.int64)
    return (d * d).sum(1), (d[:, -2:] * d[:, -2:]).sum(1)


def threshold_to_int(mse_threshold, n_dims):
    """실수 MSE 임계값 -> 정수 제곱합 임계값."""
    return int(np.floor(mse_threshold * n_dims / (IO_SCALE ** 2)))
