#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "can_ringbuffer.h"
#include "vids_pipeline.h"

static uint32_t g_result_calls = 0;
void vids_on_result(vids_result_t result, const vids_stats_t *stats)
{
    (void)result; (void)stats;
    g_result_calls++;
}

static can_frame_t make_frame(uint32_t seq)
{
    can_frame_t f;
    static const uint16_t ids[] = {0x100, 0x110, 0x120, 0x316, 0x43F, 0x545};
    f.arbitration_id = ids[seq % (sizeof(ids)/sizeof(ids[0]))];
    f.dlc = 8;
    for (int i = 0; i < 8; i++) f.data[i] = (uint8_t)((seq + i) & 0xFF);
    f.timestamp = (float)seq * 0.001f;
    return f;
}

static int test_A_functional(void)
{
    printf("\n[A] 기능 정확성 (소비자가 실시간으로 따라잡음)\n");
    enum { SLOTS = 64, N = 1000 };
    can_frame_t storage[SLOTS];
    can_rb_t rb;
    can_rb_init(&rb, storage, SLOTS);
    vids_pipeline_init(&rb);
    g_result_calls = 0;

    for (uint32_t i = 0; i < N; i++) {
        can_frame_t f = make_frame(i);
        bool ok = can_rb_push(&rb, &f);
        assert(ok);
        vids_pipeline_poll();
    }
    vids_pipeline_poll();

    vids_stats_t s = vids_pipeline_stats();
    printf("   처리 프레임=%u, 완성 윈도우=%u, 추론 호출=%u, 유실=%u\n",
           s.frames_consumed, s.windows_processed, g_result_calls, s.frames_dropped);

    int fail = 0;
    if (s.frames_consumed   != N)      { printf("   ✗ 처리 프레임 수 불일치\n"); fail = 1; }
    if (s.windows_processed != N / 32) { printf("   ✗ 윈도우 수 불일치(기대 %d)\n", N/32); fail = 1; }
    if (g_result_calls      != N / 32) { printf("   ✗ 추론 호출 수 불일치\n"); fail = 1; }
    if (s.frames_dropped    != 0)      { printf("   ✗ 유실이 0이 아님\n"); fail = 1; }
    if (!fail) printf("   ✔ 통과: 프레임이 순서대로 흐르고 32개마다 정확히 1윈도우 추론됨\n");
    return fail;
}

static int test_B_overflow(void)
{
    printf("\n[B] 유실 카운터 정확성 (소비자가 안 돎 → 반드시 넘쳐야 함)\n");
    enum { SLOTS = 256, N = 1000 };
    can_frame_t storage[SLOTS];
    can_rb_t rb;
    can_rb_init(&rb, storage, SLOTS);

    uint32_t pushed_ok = 0;
    for (uint32_t i = 0; i < N; i++) {
        can_frame_t f = make_frame(i);
        if (can_rb_push(&rb, &f)) pushed_ok++;
    }
    uint32_t expect_stored  = SLOTS - 1;
    uint32_t expect_dropped = N - expect_stored;
    printf("   저장 성공=%u(기대 %u), 유실=%u(기대 %u), 현재 버퍼 적재=%zu\n",
           pushed_ok, expect_stored, rb.dropped, expect_dropped, can_rb_count(&rb));

    int fail = 0;
    if (pushed_ok        != expect_stored)  { printf("   ✗ 저장 수 불일치\n"); fail = 1; }
    if (rb.dropped       != expect_dropped) { printf("   ✗ 유실 수 불일치\n"); fail = 1; }
    if (can_rb_count(&rb)!= expect_stored)  { printf("   ✗ 적재 수 불일치\n"); fail = 1; }
    if (!fail) printf("   ✔ 통과: 넘친 프레임이 정확히 계측됨(한 칸 비움 규칙 포함)\n");
    return fail;
}

static uint32_t run_burst(size_t capacity_slots, uint32_t burst)
{
    can_frame_t *storage = malloc(sizeof(can_frame_t) * capacity_slots);
    can_rb_t rb;
    can_rb_init(&rb, storage, capacity_slots);
    for (uint32_t i = 0; i < burst; i++) {
        can_frame_t f = make_frame(i);
        can_rb_push(&rb, &f);
    }
    uint32_t dropped = rb.dropped;
    free(storage);
    return dropped;
}

static int test_C_compare(void)
{
    printf("\n[C] v1(ISR 처리=HW FIFO 3칸) vs v2(링버퍼 256칸): 200프레임 버스트\n");
    const uint32_t burst = 200;
    uint32_t v1_drop = run_burst(4,   burst);
    uint32_t v2_drop = run_burst(256, burst);
    printf("   v1 유실=%u / %u (%.0f%%)\n", v1_drop, burst, 100.0*v1_drop/burst);
    printf("   v2 유실=%u / %u (%.0f%%)\n", v2_drop, burst, 100.0*v2_drop/burst);

    int fail = 0;
    if (v1_drop != burst - 3) { printf("   ✗ v1 유실 예상과 다름\n"); fail = 1; }
    if (v2_drop != 0)         { printf("   ✗ v2가 유실됨\n"); fail = 1; }
    if (!fail) printf("   ✔ 통과: 버퍼 분리 없이는 버스트에서 대량 유실, v2는 무유실\n");
    return fail;
}

int main(void)
{
    printf("========== Step1 수신 파이프라인 호스트 검증 ==========\n");
    int fail = 0;
    fail |= test_A_functional();
    fail |= test_B_overflow();
    fail |= test_C_compare();
    printf("\n==================== 결과: %s ====================\n",
           fail ? "실패 ✗" : "전부 통과 ✔");
    return fail;
}
