# Pipeline code is NOT taken from the image: the launcher uploads the current repo to /workspace/zh-dub each run.
# Prebuilt zh-dub runtime: all software envs baked in; model weights (~6GB for audio mode) download at pod start
# into /workspace/hf (fast via hf_xet) -> keeps image ~20GB instead of ~45GB and avoids slow registry pulls.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
ARG WITH_VLLM=0   # audio+Claude needs no vLLM; ~12GB smaller (vLLM installed at runtime if --mt hunyuan/video)
ENV APP=/opt/zhdub UV_CACHE_DIR=/tmp/uv-cache UV_LINK_MODE=copy PYTHONUNBUFFERED=1
RUN apt-get update -qq && apt-get install -y -qq ffmpeg git git-lfs fonts-noto-cjk && rm -rf /var/lib/apt/lists/* && pip install -q uv
COPY scripts/setup.sh /opt/zhdub-src/scripts/setup.sh
RUN SETUP_PHASE=install WITH_VLLM=$WITH_VLLM VOL=/tmp/vol bash /opt/zhdub-src/scripts/setup.sh && rm -rf /tmp/uv-cache /root/.cache /tmp/vol
COPY . /opt/zhdub-src
LABEL org.opencontainers.image.source=https://github.com/AdamLTy/zh-dub
# keep runpod's /start.sh (sshd + PUBLIC_KEY) as CMD
