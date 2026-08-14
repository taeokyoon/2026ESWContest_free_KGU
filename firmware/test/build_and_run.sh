#!/usr/bin/env bash
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$(dirname "$HERE")"
ROOT="$(dirname "$FW")"

find_export() {
    for d in "$AI_EXPORT_DIR" "$FW/X-CUBE-AI" "$ROOT/ai/export"; do
        if [ -n "$d" ] && [ -f "$d/feature_extract.c" ] && [ -f "$d/inference.c" ]; then
            echo "$d"; return 0
        fi
    done
    return 1
}

AI_EXPORT="$(find_export)" || {
    echo "✗ AI export 소스를 찾지 못했습니다 (feature_extract.c / inference.c)."
    echo "  ai/export/ 파일을 firmware/X-CUBE-AI/ 에 두거나,"
    echo "  AI_EXPORT_DIR=<경로> 로 지정해 다시 실행하세요."
    exit 1
}
echo "AI export 소스: $AI_EXPORT"

cc -std=c11 -O2 -Wall -Wextra \
   -DCAN_RB_HOST_TEST \
   -I"$FW/Core/Inc" -I"$AI_EXPORT" \
   "$HERE/test_pipeline.c" \
   "$FW/Core/Src/vids_pipeline.c" \
   "$AI_EXPORT/feature_extract.c" \
   "$AI_EXPORT/inference.c" \
   -lm -o "$HERE/test_pipeline"

"$HERE/test_pipeline"
