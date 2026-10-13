#!/usr/bin/env bash
# Fresh GPU env setup: clone IndexTTS + download all weights from HuggingFace. Idempotent; local disk only (VOL, default /workspace).
set -euo pipefail
VOL=${VOL:-/workspace}; export VOL
export HF_HOME=$VOL/hf UV_CACHE_DIR=$VOL/uv-cache
apt-get update -qq && apt-get install -y -qq ffmpeg git git-lfs fonts-noto-cjk >/dev/null
command -v uv >/dev/null || pip install -q uv
V=$VOL/venvs; mkdir -p $V
# 1) ASR + separation + diarization (NeMo)
[ -x $V/asr/bin/python ] || { uv venv -p 3.11 $V/asr; VIRTUAL_ENV=$V/asr uv pip install "nemo_toolkit[asr]>=2.3" demucs "pyannote.audio>=3.3" yt-dlp soundfile; }
# 2) vLLM for Hunyuan-MT-7B
[ -x $V/vllm/bin/vllm ] || { uv venv -p 3.11 $V/vllm; VIRTUAL_ENV=$V/vllm uv pip install "vllm>=0.10" ninja; }
# 3) IndexTTS2
[ -d $VOL/index-tts ] || git clone -q https://github.com/index-tts/index-tts.git $VOL/index-tts
( cd $VOL/index-tts && [ -x .venv/bin/python ] || { UV_PROJECT_ENVIRONMENT=.venv uv sync; } )
$V/asr/bin/pip -q install huggingface_hub 2>/dev/null || VIRTUAL_ENV=$V/asr uv pip install huggingface_hub
HF=$V/asr/bin/hf
[ -f $VOL/index-tts/checkpoints/gpt.pth ] || $HF download IndexTeam/IndexTTS-2 --local-dir $VOL/index-tts/checkpoints
$HF download nvidia/parakeet-tdt-0.6b-v2 >/dev/null
$HF download tencent/Hunyuan-MT-7B >/dev/null
$HF download Qwen/Qwen3-8B >/dev/null
echo "setup ok (VOL=$VOL)"
