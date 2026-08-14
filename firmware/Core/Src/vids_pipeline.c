#include "vids_pipeline.h"
#include "feature_extract.h"
#include "inference.h"

static can_rb_t   *s_rb;
static vids_stats_t s_stats;

static float s_feature_buf[VIDS_INPUT_DIM];

void vids_pipeline_init(can_rb_t *rb)
{
    s_rb = rb;
    feature_extract_init();
    s_stats.frames_consumed   = 0;
    s_stats.windows_processed = 0;
    s_stats.attacks_detected  = 0;
    s_stats.frames_dropped    = 0;
}

uint32_t vids_pipeline_poll(void)
{
    can_frame_t frame;
    uint32_t handled = 0;

    while (can_rb_pop(s_rb, &frame)) {
        handled++;
        s_stats.frames_consumed++;

        if (feature_extract_push(&frame, s_feature_buf) == 1) {
            vids_result_t r = vids_detect(s_feature_buf);
            s_stats.windows_processed++;
            if (r == VIDS_ATTACK) {
                s_stats.attacks_detected++;
            }
            s_stats.frames_dropped = s_rb->dropped;
            vids_on_result(r, &s_stats);
        }
    }
    return handled;
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
