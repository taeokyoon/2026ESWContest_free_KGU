#ifndef VIDS_PIPELINE_H
#define VIDS_PIPELINE_H

#include <stdint.h>
#include "can_ringbuffer.h"
#include "inference.h"
#include "vids_timing.h"

typedef struct {
    uint32_t frames_consumed;
    uint32_t windows_processed;
    uint32_t windows_flagged;   /* 윈도우 단위 양성 (연속 필터 적용 전) */
    uint32_t attacks_detected;  /* 경보 발생 횟수 (K회 연속 충족) */
    uint32_t frames_dropped;
} vids_stats_t;

typedef struct {
    vids_timing_stat_t feature;   /* 윈도우당 특징 추출 (32프레임 누적) */
    vids_timing_stat_t detect;    /* 윈도우당 추론 */
} vids_timing_t;

void vids_pipeline_init(can_rb_t *rb);

uint32_t vids_pipeline_poll(void);

vids_stats_t vids_pipeline_stats(void);

vids_timing_t vids_pipeline_timing(void);

void vids_on_result(vids_result_t result, const vids_stats_t *stats);

#endif
