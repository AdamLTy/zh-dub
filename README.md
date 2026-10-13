# zh-dub — 英文视频 → 中文配音（全开源模型）/ English video → Chinese dub (open-weight models)

**中文** · 输入 YouTube 链接，输出中文配音视频（保留原背景音、克隆原说话人音色）、mp3、SRT 字幕和中英对照稿。

| 环节 | 模型 | 依据 |
|---|---|---|
| 英文识别 | NVIDIA Parakeet TDT 0.6B v2 | Open ASR Leaderboard：WER 5.48%，RTFx≈6000 |
| 英译中 | Tencent Hunyuan-MT-7B（vLLM） | WMT25 31 个语向中 30 个第一 |
| 中文 TTS + 声音克隆 | IndexTTS2 | Seed-TTS-Eval zh CER 1.03% |
| 人声/背景分离 | Demucs htdemucs | 保留背景音乐和环境声 |
| 说话人分离（可选） | pyannote 3.1 | 需要 HF_TOKEN |

推荐 GPU：单卡 48GB（如 Runpod L40S）。所有数据只放在本机/pod 本地磁盘。

```bash
# 任意新 GPU 机器（CUDA 12.x / Ubuntu 22.04）
bash scripts/setup.sh                                   # 装依赖 + 从 HuggingFace 下载全部模型（约 40GB）
bash scripts/run_job.sh ./out "https://www.youtube.com/watch?v=..."
# 或在本地一键用 Runpod（只创建/删除本工具自己的 pod）
export RUNPOD_API_KEY=...
python launch_runpod.py "https://www.youtube.com/watch?v=..." --out ./dub_out
```
输出：`zh_dub.mp4`（中文配音默认音轨 + 英文原音轨 + 中文软字幕）、`zh_dub.mp3`、`zh.srt`、`transcript.md`、`timing.txt`。

**安全**：启动器只操作自己创建的 pod（名称前缀 `zhdub-`，id 记录在 `.runpod_pods.json`，删除前再次校验名称），绝不列出或停止账号里的其他 pod。

**已知限制**：IndexTTS2 公开代码没有开放时长参数，本项目通过缩放 s2mel length regulator 实现逐句时长贴合（0.70–1.25×），剩余差值用 ≤1.25× atempo。请确保你有权使用源视频和说话人的声音。

---

## 模式 / Modes
- `--mode audio`（默认）：自然语速中文音频 `zh_audio.mp3`（每位说话人克隆音色，不变速、不删改译文，按原对话顺序加自然停顿），以及按**新音频**时间轴生成的 `zh.lrc` / `zh.srt` / `zh.vtt`（`*.bi.*` 为中英双语）。
- `--mode video`：对口型配音视频（含 Qwen3 时长预算改写和逐句变速贴合）。

播放 mp3 + lrc 滚动字幕：iPhone 可用 Glaze / Mosic / MusicKeep / Offbeat，Android 可用 Musicolet / Poweramp / Muse，Mac 可用 LyricsX 或 VLC（加载 .srt）。

**English** · YouTube URL in → Chinese-dubbed mp4 (background kept, speaker voice cloned), mp3, SRT and bilingual transcript out.

Pipeline: yt-dlp → Demucs → Parakeet TDT 0.6B v2 (timestamps) → optional pyannote diarization → Hunyuan-MT-7B on vLLM → IndexTTS2 voice cloning with per-sentence duration fitting → ffmpeg mix & mux.

```bash
bash scripts/setup.sh                        # fresh GPU env: deps + all weights from HF
bash scripts/run_job.sh ./out URL [URL...]   # models stay loaded across URLs
python launch_runpod.py URL --out ./dub_out  # Runpod: create own L40S pod, run, fetch, terminate it
```
The launcher only touches the pod it created (prefix `zhdub-`, id in `.runpod_pods.json`, re-verified before delete). No network volume. License: MIT.
