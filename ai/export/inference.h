#ifndef INFERENCE_H
#define INFERENCE_H

/* v5 오토인코더(354->64->16->64->354) 순전파 + 이중 임계값 판정
 * 입력: CAN 프레임 32개 윈도우에서 뽑은 354차원 특성 벡터
 * 자세한 특성 구성은 ai/README.md의 "빠른 재학습 절차" 참고
 */

#define VIDS_INPUT_DIM 354

typedef enum {
    VIDS_NORMAL = 0,
    VIDS_ATTACK = 1
} vids_result_t;

vids_result_t vids_detect(const float input[VIDS_INPUT_DIM]);

#endif
