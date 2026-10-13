#!/usr/bin/env bash
# Hunyuan-MT-7B resident on :8000 (OpenAI API). bf16 ~15GB + KV; 0.40 of 48GB leaves room for ASR/TTS.
VOL=${VOL:-/workspace}; export HF_HOME=$VOL/hf
exec $VOL/venvs/vllm/bin/vllm serve tencent/Hunyuan-MT-7B --served-model-name mt --port 8000 --trust-remote-code \
  --max-model-len 4096 --gpu-memory-utilization ${MT_MEM:-0.40} --max-num-seqs 64 --enable-prefix-caching
