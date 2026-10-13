#!/usr/bin/env python3
"""Stage 3 (audio mode, default): natural-rate IndexTTS2 per segment (no time-stretch), cloned voice per speaker,
concatenated with natural pauses (original gap clamped; extra pause on speaker change). Writes zh_audio.mp3 and
timestamps for the NEW audio: zh.lrc, zh.srt, zh.vtt (+ bilingual *.bi.* variants)."""
import json,os,subprocess,sys
from pathlib import Path
VOL=os.environ["VOL"];root=Path(sys.argv[1])
sys.path.insert(0,f"{VOL}/index-tts")
import numpy as np,soundfile as sf
from indextts.infer_v2 import IndexTTS2
ck=f"{VOL}/index-tts/checkpoints"
tts=IndexTTS2(cfg_path=f"{ck}/config.yaml",model_dir=ck,use_fp16=True,use_cuda_kernel=True)
SR=24000
TRIM="silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
def sh(*c):subprocess.run(c,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def t_srt(s,sep=","):h,m=divmod(s,3600);m,s=divmod(m,60);return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".",sep)
def t_lrc(s):m,s=divmod(s,60);return f"[{int(m):02}:{s:05.2f}]"
for jf in sorted(root.glob("*/segments.json")):
    d=jf.parent;J=json.loads(jf.read_text());S=J["segments"];chunks=[];t=0.0
    for i,s in enumerate(S):
        raw=str(d/f"seg{i:05}.raw.wav");f=str(d/f"seg{i:05}.wav")
        tts.infer(spk_audio_prompt=J["refs"][s["spk"]],text=s["zh"],output_path=raw,verbose=False,interval_silence=150)
        sh("ffmpeg","-y","-i",raw,"-af",TRIM,"-ar",str(SR),"-ac","1",f);a,_=sf.read(f,dtype="float32")
        if i:
            gap=S[i]["start"]-S[i-1]["end"];pause=min(max(gap,0.25),1.2)+(0.35 if s["spk"]!=S[i-1]["spk"] else 0)
            chunks.append(np.zeros(int(pause*SR),np.float32));t+=pause
        s["zh_start"]=round(t,3);t+=len(a)/SR;s["zh_end"]=round(t,3);chunks.append(a)
        os.remove(raw);os.remove(f)
    sf.write(str(d/"zh_audio.wav"),np.concatenate(chunks),SR)
    title=J.get("title","");sh("ffmpeg","-y","-i",str(d/"zh_audio.wav"),"-af","loudnorm=I=-16:TP=-1.5","-b:a","160k",
        "-metadata",f"title={title or d.name} (中文)","-metadata","language=zho",str(d/"zh_audio.mp3"))
    name={k:k for k in J["refs"]}
    for bi in (False,True):
        sfx=".bi" if bi else ""
        txt=lambda s:(f"{s['spk']}：{s['zh']}"+(f"\n{s['en']}" if bi else ""))
        lrc=[f"[ti:{title or d.name}]","[la:zh]"]+[t_lrc(s["zh_start"])+txt(s).replace("\n"," / ") for s in S]+[t_lrc(t)]
        (d/f"zh{sfx}.lrc").write_text("\n".join(lrc)+"\n",encoding="utf-8")
        (d/f"zh{sfx}.srt").write_text("\n".join(f"{i+1}\n{t_srt(s['zh_start'])} --> {t_srt(s['zh_end'])}\n{txt(s)}\n" for i,s in enumerate(S)),encoding="utf-8")
        (d/f"zh{sfx}.vtt").write_text("WEBVTT\n\n"+"\n".join(f"{t_srt(s['zh_start'],'.')} --> {t_srt(s['zh_end'],'.')}\n{txt(s)}\n" for s in S),encoding="utf-8")
    (d/"transcript.md").write_text("# 中文稿\n\n"+"\n".join(f"- **[{t_srt(s['zh_start'])[:8]}] {s['spk']}** {s['zh']}  \n  <sub>{s['en']}</sub>" for s in S),encoding="utf-8")
    J["zh_audio_duration"]=round(t,2);os.remove(d/"zh_audio.wav")
    jf.write_text(json.dumps(J,ensure_ascii=False,indent=1));print("stage3_audio",d.name,f"{t:.0f}s vs source {J['duration']:.0f}s",flush=True)
