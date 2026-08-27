#ifndef VIDS_PIPELINE_H
#define VIDS_PIPELINE_H

#include <stdint.h>
#include "can_ringbuffer.h"
#include "inference.h"

typedef struct {
    uint32_t frames_consumed;
    uint32_t windows_processed;
    uint32_t windows_flagged;   /* 윈도우 단위 양성 (연속 필터 적용 전) */
    uint32_t attacks_detected;  /* 경보 발생 횟수 (K회 연속 충족) */
    uint32_t frames_dropped;
} vids_stats_t;

void vids_pipeline_init(can_rb_t *rb);

uint32_t vids_pipeline_poll(void);

vids_stats_t vids_pipeline_stats(void);

void vids_on_result(vids_result_t result, const vids_stats_t *stats);

#endif
