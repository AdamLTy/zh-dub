#!/usr/bin/env bash
# On the pod: bash run_job.sh OUTDIR URL [URL...]   (env HF_TOKEN optional -> multi-speaker diarization)
set -euo pipefail
VOL=${VOL:-/workspace}; export VOL
D=$(cd "$(dirname "$0")" && pwd); P=$D/../pipeline; OUT=$1; shift; mkdir -p "$OUT"; T0=$(date +%s)
$VOL/venvs/asr/bin/python $P/stage1_asr.py "$OUT" "$@"; T1=$(date +%s)
curl -sf localhost:8000/v1/models >/dev/null || { nohup bash $D/serve_mt.sh > $OUT/vllm.log 2>&1 & }
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 3; done
python3 $P/stage2_mt.py "$OUT"; T2=$(date +%s)
$VOL/index-tts/.venv/bin/python $P/stage3_tts.py "$OUT"; T3=$(date +%s)
echo "timing_s asr=$((T1-T0)) mt=$((T2-T1)) tts_mux=$((T3-T2)) total=$((T3-T0))" | tee $OUT/timing.txt
