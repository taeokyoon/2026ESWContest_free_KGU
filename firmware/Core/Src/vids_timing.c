#include "vids_timing.h"

__attribute__((weak)) uint32_t vids_timing_now(void)
{
    return 0u;
}

void vids_timing_stat_reset(vids_timing_stat_t *s)
{
    s->min_cycles  = UINT32_MAX;
    s->max_cycles  = 0u;
    s->last_cycles = 0u;
    s->sum_cycles  = 0u;
    s->samples     = 0u;
}

void vids_timing_stat_record(vids_timing_stat_t *s, uint32_t cycles)
{
    s->last_cycles = cycles;
    s->sum_cycles += cycles;
    s->samples++;

    if (cycles < s->min_cycles) {
        s->min_cycles = cycles;
    }
    if (cycles > s->max_cycles) {
        s->max_cycles = cycles;
    }
}
