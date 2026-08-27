#ifndef VIDS_TIMING_H
#define VIDS_TIMING_H

#include <stdint.h>

typedef struct {
    uint32_t min_cycles;
    uint32_t max_cycles;
    uint32_t last_cycles;
    uint64_t sum_cycles;
    uint32_t samples;
} vids_timing_stat_t;

uint32_t vids_timing_now(void);

void vids_timing_stat_reset(vids_timing_stat_t *s);

void vids_timing_stat_record(vids_timing_stat_t *s, uint32_t cycles);

#endif
