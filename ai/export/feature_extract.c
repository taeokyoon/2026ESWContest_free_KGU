#include <math.h>
#include <string.h>
#include "feature_extract.h"

#define ID_TABLE_SIZE       2048   /* CAN 표준 11비트 ID 전체 범위 (0x7FF+1) */
#define FEATURES_PER_FRAME  11     /* id_norm, dlc, byte_0..7, id_delta_t */

/* Colab 학습 데이터 전체에서 뽑은 고정 상수 (2026-08-03 확인, ai/README.md 참고) */
#define ID_DELTA_T_MEDIAN  0.01022195816040039f
#define ID_DELTA_T_LOG_MIN 0.06283380660796888f
#define ID_DELTA_T_LOG_MAX 11.873697951933963f

/* ID별 "마지막으로 본 시각" 기록 (2048칸 = ID값을 그대로 인덱스로 사용) */
static float   last_timestamp[ID_TABLE_SIZE];
static uint8_t id_seen[ID_TABLE_SIZE];

/* 현재 채워지고 있는 윈도우 (32프레임, 논오버랩) */
static float    window_raw[VIDS_WINDOW_SIZE][FEATURES_PER_FRAME];
static uint16_t window_ids[VIDS_WINDOW_SIZE];
static int      window_count;

void feature_extract_init(void)
{
    memset(last_timestamp, 0, sizeof(last_timestamp));
    memset(id_seen, 0, sizeof(id_seen));
    window_count = 0;
}

static float clamp01(float x)
{
    if (x < 0.0f) return 0.0f;
    if (x > 1.0f) return 1.0f;
    return x;
}

/* id_delta_t 계산: 이 ID가 윈도우 안에서 처음이 아니라 "테이블에 한 번도 안 잡힌" 최초 등장이면
 * median으로 채우고(Python fillna(median)과 동일), 아니면 실제 간격을 씀 */
static float compute_id_delta_t_norm(uint16_t id, float timestamp)
{
    float delta_t;
    if (id_seen[id]) {
        delta_t = timestamp - last_timestamp[id];
    } else {
        delta_t = ID_DELTA_T_MEDIAN;
        id_seen[id] = 1;
    }
    last_timestamp[id] = timestamp;

    float log_val = log1pf(delta_t * 1000.0f);
    float norm = (log_val - ID_DELTA_T_LOG_MIN) / (ID_DELTA_T_LOG_MAX - ID_DELTA_T_LOG_MIN);
    return clamp01(norm); /* 학습 때 못 본 극단값 대비 0~1로 잘라줌 */
}

int feature_extract_push(const can_frame_t *frame, float out_features[VIDS_INPUT_DIM])
{
    int idx = window_count;

    window_raw[idx][0] = (float)frame->arbitration_id / 2047.0f; /* id_norm (0x7FF = 2047) */
    window_raw[idx][1] = (float)frame->dlc / 8.0f;                /* dlc_norm */
    for (int b = 0; b < 8; b++) {
        window_raw[idx][2 + b] = (float)frame->data[b] / 255.0f;  /* byte_0..7 */
    }
    window_raw[idx][10] = compute_id_delta_t_norm(frame->arbitration_id, frame->timestamp);
    window_ids[idx] = frame->arbitration_id;

    window_count++;
    if (window_count < VIDS_WINDOW_SIZE) {
        return 0; /* 아직 윈도우 안 참 */
    }

    /* 윈도우 완성: 32 x 11을 순서대로 펼쳐서 352차원으로 조립 (Python df.values.flatten()과 동일 순서) */
    for (int i = 0; i < VIDS_WINDOW_SIZE; i++) {
        for (int f = 0; f < FEATURES_PER_FRAME; f++) {
            out_features[i * FEATURES_PER_FRAME + f] = window_raw[i][f];
        }
    }

    /* 고유 ID 개수 / 최다 반복 횟수 집계: 32개짜리 작은 배열이라 이중 루프로 충분 */
    uint8_t counted[VIDS_WINDOW_SIZE] = {0};
    int unique_count = 0;
    int max_repeat = 0;
    for (int i = 0; i < VIDS_WINDOW_SIZE; i++) {
        if (counted[i]) {
            continue; /* 이미 앞에서 이 ID를 센 적 있으면 건너뜀 (중복 방지) */
        }
        int repeat = 1;
        for (int j = i + 1; j < VIDS_WINDOW_SIZE; j++) {
            if (window_ids[j] == window_ids[i]) {
                repeat++;
                counted[j] = 1; /* 뒤에서 같은 ID를 또 만나도 다시 세지 않도록 표시 */
            }
        }
        unique_count++;
        if (repeat > max_repeat) {
            max_repeat = repeat;
        }
    }
    out_features[352] = (float)unique_count / VIDS_WINDOW_SIZE; /* unique_id_ratio */
    out_features[353] = (float)max_repeat / VIDS_WINDOW_SIZE;   /* max_repeat_ratio */

    window_count = 0; /* 다음 윈도우 준비 (논오버랩이라 겹치지 않게 리셋) */
    return 1;
}
