/* [D] Python 정수 시뮬레이션 <-> C 구현 판정 일치 검증
 *
 * ai/notebooks/06_export_vectors.py 가 만든 이진 파일을 읽어
 * 같은 윈도우를 vids_detect() 에 넣고 판정이 전부 일치하는지 본다.
 *
 * 파일 형식 (리틀엔디안)
 *   uint32  magic = 0x56494453 ('VIDS')
 *   uint32  n_windows
 *   uint32  input_dim (= 354)
 *   n_windows x (input_dim x float32)   윈도우 특성
 *   n_windows x uint8                   Python 이 낸 판정 (0=정상, 1=공격)
 *   n_windows x int64                   Python 이 낸 점수 A 제곱합
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#include "inference.h"

#define MAGIC 0x56494453u

int main(int argc, char **argv)
{
    const char *path = (argc > 1) ? argv[1] : "vectors.bin";
    FILE *f = fopen(path, "rb");
    if (!f) {
        printf("✗ 벡터 파일을 열 수 없습니다: %s\n", path);
        printf("  ai/notebooks/06_export_vectors.py 를 먼저 실행하세요.\n");
        return 1;
    }

    uint32_t magic = 0, n = 0, dim = 0;
    if (fread(&magic, 4, 1, f) != 1 || fread(&n, 4, 1, f) != 1 || fread(&dim, 4, 1, f) != 1) {
        printf("✗ 헤더를 읽지 못했습니다\n");
        fclose(f);
        return 1;
    }
    if (magic != MAGIC || dim != VIDS_INPUT_DIM) {
        printf("✗ 형식 불일치 (magic=%08x dim=%u)\n", magic, dim);
        fclose(f);
        return 1;
    }

    float *X = malloc((size_t)n * dim * sizeof(float));
    uint8_t *want = malloc(n);
    int64_t *score = malloc((size_t)n * sizeof(int64_t));
    if (!X || !want || !score) {
        printf("✗ 메모리 할당 실패\n");
        return 1;
    }
    if (fread(X, sizeof(float), (size_t)n * dim, f) != (size_t)n * dim ||
        fread(want, 1, n, f) != n ||
        fread(score, sizeof(int64_t), n, f) != n) {
        printf("✗ 본문을 읽지 못했습니다\n");
        fclose(f);
        return 1;
    }
    fclose(f);

    printf("\n[D] Python 정수 시뮬레이션 <-> C 구현 판정 일치 (%u 윈도우)\n", n);

    uint32_t mismatch = 0, n_attack = 0;
    for (uint32_t i = 0; i < n; i++) {
        vids_result_t got = vids_detect(&X[(size_t)i * dim]);
        uint8_t g = (got == VIDS_ATTACK) ? 1u : 0u;
        n_attack += want[i];
        if (g != want[i]) {
            if (mismatch < 5) {
                printf("   불일치 #%u: Python=%u C=%u (점수A=%lld)\n",
                       i, want[i], g, (long long)score[i]);
            }
            mismatch++;
        }
    }

    printf("   공격 판정 %u / 정상 판정 %u\n", n_attack, n - n_attack);
    if (mismatch == 0) {
        printf("   ✔ 통과: %u개 전부 일치\n", n);
    } else {
        printf("   ✗ 실패: %u개 불일치\n", mismatch);
    }

    free(X);
    free(want);
    free(score);
    return mismatch == 0 ? 0 : 1;
}
