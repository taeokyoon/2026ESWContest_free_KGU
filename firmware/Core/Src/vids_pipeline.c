#include "vids_pipeline.h"
#include "feature_extract.h"
#include "inference.h"
#include "autoencoder_v5_quant.h"

static can_rb_t   *s_rb;
static vids_stats_t s_stats;

static float s_feature_buf[VIDS_INPUT_DIM];
static uint32_t s_run;

static vids_timing_t s_timing;
static uint32_t s_feature_acc;

void vids_pipeline_init(can_rb_t *rb)
{
    s_rb = rb;
    feature_extract_init();
    s_stats.frames_consumed   = 0;
    s_stats.windows_processed = 0;
    s_stats.windows_flagged   = 0;
    s_stats.attacks_detected  = 0;
    s_stats.frames_dropped    = 0;
    s_run = 0;

    vids_timing_stat_reset(&s_timing.feature);
    vids_timing_stat_reset(&s_timing.detect);
    s_feature_acc = 0;
}

uint32_t vids_pipeline_poll(void)
{
    can_frame_t frame;
    uint32_t handled = 0;

    while (can_rb_pop(s_rb, &frame)) {
        handled++;
        s_stats.frames_consumed++;

        uint32_t t0 = vids_timing_now();
        int complete = feature_extract_push(&frame, s_feature_buf);
        uint32_t t1 = vids_timing_now();
        s_feature_acc += t1 - t0;

        if (complete == 1) {
            vids_result_t raw = vids_detect(s_feature_buf);
            uint32_t t2 = vids_timing_now();

            vids_timing_stat_record(&s_timing.detect, t2 - t1);
            vids_timing_stat_record(&s_timing.feature, s_feature_acc);
            s_feature_acc = 0;

            s_stats.windows_processed++;

            if (raw == VIDS_ATTACK) {
                s_stats.windows_flagged++;
                if (s_run < VIDS_K_CONSECUTIVE) {
                    s_run++;
                }
            } else {
                s_run = 0;
            }

            vids_result_t alarm =
                (s_run >= VIDS_K_CONSECUTIVE) ? VIDS_ATTACK : VIDS_NORMAL;
            if (alarm == VIDS_ATTACK) {
                s_stats.attacks_detected++;
            }
            s_stats.frames_dropped = s_rb->dropped;
            vids_on_result(alarm, &s_stats);
        }
    }
    return handled;
}

vids_timing_t vids_pipeline_timing(void)
{
    return s_timing;
}

vids_stats_t vids_pipeline_stats(void)
{
    s_stats.frames_dropped = s_rb->dropped;
    return s_stats;
}

__attribute__((weak)) void vids_on_result(vids_result_t result, const vids_stats_t *stats)
{
    (void)result;
    (void)stats;
}
