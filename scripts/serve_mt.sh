#!/usr/bin/env bash
# Resident vLLM OpenAI server on :8000.  MODEL (default Hunyuan-MT-7B) served as name "mt".
# Stage 2b uses MODEL=Qwen/Qwen3-8B. enforce-eager + torch sampler: CUDA-graph capture and FlashInfer JIT failed on runpod image.
VOL=${VOL:-/workspace}; export HF_HOME=$VOL/hf
export PATH=$VOL/venvs/vllm/bin:$PATH VLLM_USE_FLASHINFER_SAMPLER=0
exec $VOL/venvs/vllm/bin/vllm serve ${MODEL:-tencent/Hunyuan-MT-7B} --served-model-name mt --port 8000 --trust-remote-code --enforce-eager \
  --max-model-len 4096 --gpu-memory-utilization ${MT_MEM:-0.40} --max-num-seqs 64 --enable-prefix-caching
