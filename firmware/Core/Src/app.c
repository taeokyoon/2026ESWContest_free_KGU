#include "app.h"
#include "can_ringbuffer.h"
#include "vids_pipeline.h"
#include "can_bxcan.h"
#include "stm32f1xx_hal.h"

extern CAN_HandleTypeDef hcan;

#define CAN_RB_SLOTS 64
static can_frame_t s_storage[CAN_RB_SLOTS];
static can_rb_t    s_rb;

int app_setup(void)
{
    can_rb_init(&s_rb, s_storage, CAN_RB_SLOTS);
    vids_pipeline_init(&s_rb);
    return can_bxcan_start(&hcan, &s_rb);
}

void app_loop(void)
{
    can_bxcan_time_service();
    vids_pipeline_poll();
}
