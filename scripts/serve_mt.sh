#!/usr/bin/env bash
# Hunyuan-MT-7B resident on :8000 (OpenAI API). bf16 ~15GB + KV; 0.40 of 48GB leaves room for ASR/TTS.
VOL=${VOL:-/workspace}; export HF_HOME=$VOL/hf
export PATH=$VOL/venvs/vllm/bin:$PATH VLLM_USE_FLASHINFER_SAMPLER=0  # FlashInfer sampling JIT fails on the runpod image; use torch sampler
exec $VOL/venvs/vllm/bin/vllm serve tencent/Hunyuan-MT-7B --served-model-name mt --port 8000 --trust-remote-code --enforce-eager \
  --max-model-len 4096 --gpu-memory-utilization ${MT_MEM:-0.40} --max-num-seqs 64 --enable-prefix-caching
