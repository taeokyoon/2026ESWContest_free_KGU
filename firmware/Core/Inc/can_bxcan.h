#ifndef CAN_BXCAN_H
#define CAN_BXCAN_H

#include "can_ringbuffer.h"

int can_bxcan_start(void *hcan_handle, can_rb_t *rb);

float can_bxcan_now_seconds(void);

#endif
