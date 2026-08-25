#ifndef FEATURE_EXTRACT_H
#define FEATURE_EXTRACT_H

#include <stdint.h>
#include "inference.h"

#define VIDS_WINDOW_SIZE 32

typedef struct {
    uint16_t arbitration_id; /* 0 ~ 0x7FF (CAN 표준 11비트 ID) */
    uint8_t  dlc;             /* 0 ~ 8 */
    uint8_t  data[8];
    float    timestamp;       /* 초 단위, 단조 증가 */
} can_frame_t;

void feature_extract_init(void);

/* 프레임 1개를 윈도우에 누적한다.
 * 32개가 다 모이면 1을 반환하고 out_features에 354차원 벡터를 채운다 (그대로 vids_detect에 전달).
 * 아직 덜 모였으면 0을 반환한다. */
int feature_extract_push(const can_frame_t *frame, float out_features[VIDS_INPUT_DIM]);

#endif
