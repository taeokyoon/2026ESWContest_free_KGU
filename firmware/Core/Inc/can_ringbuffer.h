#ifndef CAN_RINGBUFFER_H
#define CAN_RINGBUFFER_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "feature_extract.h"

#if defined(__ARM_ARCH) && !defined(CAN_RB_HOST_TEST)
  #include "cmsis_compiler.h"
  #define CAN_RB_BARRIER()  __DMB()
#else
  #define CAN_RB_BARRIER()  __asm__ __volatile__("" ::: "memory")
#endif

typedef struct {
    can_frame_t     *buf;
    size_t           capacity;
    volatile size_t  head;
    volatile size_t  tail;
    volatile uint32_t dropped;
} can_rb_t;

static inline size_t can_rb_next(const can_rb_t *rb, size_t idx)
{
    idx++;
    if (idx >= rb->capacity) idx = 0;
    return idx;
}

static inline void can_rb_init(can_rb_t *rb, can_frame_t *storage, size_t capacity)
{
    rb->buf = storage;
    rb->capacity = capacity;
    rb->head = 0;
    rb->tail = 0;
    rb->dropped = 0;
}

static inline bool can_rb_push(can_rb_t *rb, const can_frame_t *frame)
{
    size_t head = rb->head;
    size_t next = can_rb_next(rb, head);
    if (next == rb->tail) {
        rb->dropped++;
        return false;
    }
    rb->buf[head] = *frame;
    CAN_RB_BARRIER();
    rb->head = next;
    return true;
}

static inline bool can_rb_pop(can_rb_t *rb, can_frame_t *out)
{
    size_t tail = rb->tail;
    if (tail == rb->head) {
        return false;
    }
    *out = rb->buf[tail];
    CAN_RB_BARRIER();
    rb->tail = can_rb_next(rb, tail);
    return true;
}

static inline size_t can_rb_count(const can_rb_t *rb)
{
    size_t head = rb->head;
    size_t tail = rb->tail;
    if (head >= tail) return head - tail;
    return rb->capacity - (tail - head);
}

#endif
