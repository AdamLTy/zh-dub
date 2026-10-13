#!/usr/bin/env bash
# Setup for any fresh GPU env (also used at Docker build time). Idempotent.
#   APP  = where code envs live (venvs, IndexTTS clone). Image: /opt/zhdub. Default: $VOL.
#   VOL  = data/cache dir (HF weights, jobs). Default /workspace.
#   SETUP_PHASE=install  -> only install software (Docker build);  weights -> only download weights;  default both.
#   WITH_VLLM=1 (default) installs vLLM env; NEED_LLM=1 also pre-downloads Hunyuan-MT/Qwen3 (only needed for --mt hunyuan / video mode).
set -euo pipefail
VOL=${VOL:-/workspace}; APP=${APP:-$VOL}; export VOL APP
export HF_HOME=$VOL/hf UV_CACHE_DIR=${UV_CACHE_DIR:-/root/.cache/uv} UV_LINK_MODE=copy
PH=${SETUP_PHASE:-all}; V=$APP/venvs
if [[ $PH != weights ]]; then
  command -v ffmpeg >/dev/null && command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg git git-lfs fonts-noto-cjk >/dev/null; }
  command -v uv >/dev/null || pip install -q uv
  mkdir -p $V
  [ -x $V/asr/bin/python ] || { uv venv -p 3.11 $V/asr; VIRTUAL_ENV=$V/asr uv pip install "nemo_toolkit[asr]>=2.3" demucs "pyannote.audio>=3.3" yt-dlp soundfile "huggingface_hub[hf_xet]"; }
  if [[ ${WITH_VLLM:-1} == 1 ]]; then [ -x $V/vllm/bin/vllm ] || { uv venv -p 3.11 $V/vllm; VIRTUAL_ENV=$V/vllm uv pip install "vllm>=0.10" ninja; }; fi
  [ -d $APP/index-tts ] || git clone -q https://github.com/index-tts/index-tts.git $APP/index-tts
  ( cd $APP/index-tts && { [ -x .venv/bin/python ] || UV_PROJECT_ENVIRONMENT=.venv uv sync; } && VIRTUAL_ENV=.venv uv pip install -q ninja )
fi
if [[ $PH != install ]]; then
  HF=$V/asr/bin/hf; mkdir -p $HF_HOME
  [ -f $APP/index-tts/checkpoints/gpt.pth ] || $HF download IndexTeam/IndexTTS-2 --local-dir $APP/index-tts/checkpoints >/dev/null &
  $HF download nvidia/parakeet-tdt-0.6b-v2 >/dev/null &
  $HF download nvidia/diar_streaming_sortformer_4spk-v2 >/dev/null &
  if [[ ${NEED_LLM:-0} == 1 ]]; then $HF download tencent/Hunyuan-MT-7B >/dev/null & $HF download Qwen/Qwen3-8B >/dev/null & fi
  wait
fi
uv cache clean >/dev/null 2>&1 || true
echo "setup ok (phase=$PH APP=$APP VOL=$VOL)"
