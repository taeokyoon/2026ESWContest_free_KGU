#include <math.h>
#include "inference.h"
#include "autoencoder_v5_weights_int8.h"

/* 레이어별 입출력 차원 (모델 정의: Dense(64,relu)->Dense(16,relu)->Dense(64,relu)->Dense(354,sigmoid)) */
#define L0_IN  354
#define L0_OUT 64
#define L1_IN  64
#define L1_OUT 16
#define L2_IN  16
#define L2_OUT 64
#define L3_IN  64
#define L3_OUT 354

/* 양자화(int8) 반영 후 재계산한 임계값 (2026-08-03 확정) */
#define THRESHOLD_FULL  0.07299177638757141f
#define THRESHOLD_LAST2 0.01824626258918472f

static float relu(float x)
{
    return x > 0.0f ? x : 0.0f;
}

static float sigmoid(float x)
{
    return 1.0f / (1.0f + expf(-x));
}

// 변경 전
// * weight는 Keras (in_dim, out_dim) 배열을 flatten()
// 한 것이므로
//  * weight[i][j] 원소는 1차원 배열에서 weight[i * out
// _dim + j] 위치에 있음
/* 변경 후
 * weight는 Flash에 int8로 저장되어 있으므로, 계산 직전에 scale을 곱해
 * float로 복원한다 (weight[i][j] = weight_q[i*out_dim+j] * scale).
 * 계산 자체는 float32로 하기 때문에 정확도 손실이 거의 없다.
 */
//  Dense 레이어 1개의 순전파: output = activation(input @ weight + bias)
static void dense_layer(const float *input, int in_dim, int out_dim,
                         const signed char *weight_q, float scale, const float *bias,
                         float (*activation)(float), float *output)
{
    for (int o = 0; o < out_dim; o++) {
        float sum = bias[o];
        for (int i = 0; i < in_dim; i++) {
            float w = weight_q[i * out_dim + o] * scale;
            sum += input[i] * w;
        }
        output[o] = activation(sum);
    }
}

vids_result_t vids_detect(const float input[VIDS_INPUT_DIM])
{
    float h0[L0_OUT];
    float h1[L1_OUT];
    float h2[L2_OUT];
    float output[L3_OUT];

    dense_layer(input, L0_IN, L0_OUT, layer0_weight_q, layer0_scale, layer0_bias, relu, h0);
    dense_layer(h0,    L1_IN, L1_OUT, layer1_weight_q, layer1_scale, layer1_bias, relu, h1);
    dense_layer(h1,    L2_IN, L2_OUT, layer2_weight_q, layer2_scale, layer2_bias, relu, h2);
    dense_layer(h2,    L3_IN, L3_OUT, layer3_weight_q, layer3_scale, layer3_bias, sigmoid, output);

    /* 채점 A: 354차원 전체 평균 재구성오차 (콘텐츠 기반 공격에 강함) */
    float error_sum_full = 0.0f;
    for (int i = 0; i < VIDS_INPUT_DIM; i++) {
        float diff = input[i] - output[i];
        error_sum_full += diff * diff;
    }
    float mse_full = error_sum_full / VIDS_INPUT_DIM;

    /* 채점 B: 마지막 2차원(unique_id_ratio, max_repeat_ratio)만의 평균오차 (빈도 기반 공격에 강함) */
    float diff_a = input[VIDS_INPUT_DIM - 2] - output[VIDS_INPUT_DIM - 2];
    float diff_b = input[VIDS_INPUT_DIM - 1] - output[VIDS_INPUT_DIM - 1];
    float mse_last2 = (diff_a * diff_a + diff_b * diff_b) / 2.0f;

    /* 둘 중 하나라도 임계값을 넘으면 공격 판정 (OR 결합) */
    if (mse_full > THRESHOLD_FULL || mse_last2 > THRESHOLD_LAST2) {
        return VIDS_ATTACK;
    }
    return VIDS_NORMAL;
}
