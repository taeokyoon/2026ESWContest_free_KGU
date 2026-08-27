#include <stdint.h>
#include "inference.h"
#include "autoencoder_v5_weights_int8.h"
#include "autoencoder_v5_quant.h"

#define L0_IN  354
#define L0_OUT 64
#define L1_IN  64
#define L1_OUT 16
#define L2_IN  16
#define L2_OUT 64
#define L3_IN  64
#define L3_OUT 354

#define ACC_CHUNK 64

/* 메인 루프에서만 호출된다(vids_pipeline_poll). ISR에서 부르면 안 된다 — 재진입 불가. */
static int16_t s_in_q[VIDS_INPUT_DIM];

static int32_t requantize(int32_t acc, int32_t m0, int32_t shift)
{
    int64_t prod = (int64_t)acc * (int64_t)m0;
    return (int32_t)((prod + ((int64_t)1 << (shift - 1))) >> shift);
}

static int16_t sigmoid_q(int32_t acc)
{
    int64_t prod = (int64_t)acc * (int64_t)VIDS_SIG_M0;
    int32_t idx = (int32_t)((prod + ((int64_t)1 << (VIDS_SIG_SH - 1))) >> VIDS_SIG_SH)
                + VIDS_SIG_OFFSET;

    const int32_t hi_limit = (VIDS_SIG_LUT_N - 1) << VIDS_SIG_FRAC_BITS;
    if (idx < 0)         idx = 0;
    if (idx > hi_limit)  idx = hi_limit;

    int32_t i = idx >> VIDS_SIG_FRAC_BITS;
    int32_t frac = idx & ((1 << VIDS_SIG_FRAC_BITS) - 1);
    int32_t lo = vids_sigmoid_lut[i];
    int32_t hi = vids_sigmoid_lut[(i + 1 < VIDS_SIG_LUT_N) ? (i + 1) : (VIDS_SIG_LUT_N - 1)];

    int32_t v = lo + (((hi - lo) * frac) >> VIDS_SIG_FRAC_BITS);
    if (v < 0)             v = 0;
    if (v > VIDS_ACT_MAX)  v = VIDS_ACT_MAX;
    return (int16_t)v;
}

/* 입력 고정 방식: 가중치를 in 방향으로 순회하며 out 방향은 연속 접근한다.
 * Flash 프리페치 버퍼가 살아 있어야 하므로 out 축을 안쪽에 둔다.
 * out_stride = 가중치 행렬의 행 간격(= 원래 out_dim), n_out = 이번에 계산할 출력 개수.
 * 출력층은 청크로 쪼개 부르므로 둘이 다를 수 있다. */
static void dense_acc(const int16_t *in, int in_dim, int out_stride,
                      const signed char *w, const int32_t *bias, int32_t *acc, int n_out)
{
    for (int o = 0; o < n_out; o++) {
        acc[o] = bias[o];
    }
    for (int i = 0; i < in_dim; i++) {
        int32_t a = in[i];
        if (a == 0) {
            continue;
        }
        const signed char *row = w + (int32_t)i * out_stride;
        for (int o = 0; o < n_out; o++) {
            acc[o] += a * row[o];
        }
    }
}

static void activate(const int32_t *acc, int n, int32_t m0, int32_t shift, int16_t *out)
{
    for (int o = 0; o < n; o++) {
        int32_t v = acc[o];
        if (v < 0) {
            v = 0;
        }
        v = requantize(v, m0, shift);
        if (v > VIDS_ACT_MAX) {
            v = VIDS_ACT_MAX;
        }
        out[o] = (int16_t)v;
    }
}

vids_result_t vids_detect(const float input[VIDS_INPUT_DIM])
{
    int16_t h0[L0_OUT];
    int16_t h1[L1_OUT];
    int16_t h2[L2_OUT];
    int32_t acc[ACC_CHUNK];

    for (int i = 0; i < VIDS_INPUT_DIM; i++) {
        int32_t v = (int32_t)(input[i] * (float)VIDS_ACT_MAX + 0.5f);
        if (v < 0)             v = 0;
        if (v > VIDS_ACT_MAX)  v = VIDS_ACT_MAX;
        s_in_q[i] = (int16_t)v;
    }

    dense_acc(s_in_q, L0_IN, L0_OUT, layer0_weight_q, vids_bias_q0, acc, L0_OUT);
    activate(acc, L0_OUT, VIDS_REQUANT0_M0, VIDS_REQUANT0_SH, h0);

    dense_acc(h0, L1_IN, L1_OUT, layer1_weight_q, vids_bias_q1, acc, L1_OUT);
    activate(acc, L1_OUT, VIDS_REQUANT1_M0, VIDS_REQUANT1_SH, h1);

    dense_acc(h1, L2_IN, L2_OUT, layer2_weight_q, vids_bias_q2, acc, L2_OUT);
    activate(acc, L2_OUT, VIDS_REQUANT2_M0, VIDS_REQUANT2_SH, h2);

    /* 출력층은 복원값을 저장하지 않고 청크 단위로 흘려보내며 오차만 누적한다. */
    int64_t err_full = 0;
    for (int base = 0; base < L3_OUT; base += ACC_CHUNK) {
        int n = L3_OUT - base;
        if (n > ACC_CHUNK) {
            n = ACC_CHUNK;
        }
        dense_acc(h2, L3_IN, L3_OUT, layer3_weight_q + base,
                  vids_bias_q3 + base, acc, n);
        for (int j = 0; j < n; j++) {
            int32_t d = (int32_t)s_in_q[base + j] - (int32_t)sigmoid_q(acc[j]);
            err_full += (int64_t)d * (int64_t)d;
        }
    }

    if (err_full > VIDS_TH_FULL_Q) {
        return VIDS_ATTACK;
    }
    if (s_in_q[VIDS_INPUT_DIM - 2] < VIDS_TH_UNIQUE_Q) {
        return VIDS_ATTACK;
    }
    if (s_in_q[VIDS_INPUT_DIM - 1] > VIDS_TH_REPEAT_Q) {
        return VIDS_ATTACK;
    }
    return VIDS_NORMAL;
}
