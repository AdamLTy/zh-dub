#!/usr/bin/env bash
# On the pod: bash run_job.sh OUTDIR URL|FILE [...]   (HF_TOKEN optional -> pyannote; else Sortformer)
set -euo pipefail
VOL=${VOL:-/workspace}; export VOL HF_HOME=$VOL/hf
D=$(cd "$(dirname "$0")" && pwd); P=$D/../pipeline; OUT=$1; shift; mkdir -p "$OUT"
llm(){ pkill -f "[v]llm serve" || true; sleep 3; MODEL=$1 nohup bash $D/serve_mt.sh > $OUT/vllm_$(basename $1).log 2>&1 &
       for i in $(seq 180); do curl -sf localhost:8000/v1/models >/dev/null && return 0; sleep 3; done; echo "vLLM failed: $1"; exit 1; }
T0=$(date +%s)
$VOL/venvs/asr/bin/python $P/stage1_asr.py "$OUT" "$@"; T1=$(date +%s)
llm tencent/Hunyuan-MT-7B; python3 $P/stage2_mt.py "$OUT"; T2=$(date +%s)
llm Qwen/Qwen3-8B; python3 $P/stage2b_fit.py "$OUT"; T3=$(date +%s)
pkill -f "[v]llm serve" || true; sleep 5
$VOL/index-tts/.venv/bin/python $P/stage3_tts.py "$OUT"; T4=$(date +%s)
echo "timing_s asr=$((T1-T0)) mt=$((T2-T1)) fit=$((T3-T2)) tts_mux=$((T4-T3)) total=$((T4-T0))" | tee $OUT/timing.txt
