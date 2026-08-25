#ifndef CAN_BXCAN_H
#define CAN_BXCAN_H

#include <stdint.h>
#include "can_ringbuffer.h"

int can_bxcan_start(void *hcan_handle, can_rb_t *rb);

void can_bxcan_time_service(void);

float can_bxcan_now_seconds(void);

uint32_t can_bxcan_rejected(void);

#endif
