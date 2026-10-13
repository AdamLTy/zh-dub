#!/usr/bin/env python3
"""Stage 3 (index-tts venv): IndexTTS2 voice-cloned zh speech per segment with duration control, mix over bgm, mux.
Duration control: public IndexTTS2 code has no duration arg, so we scale the s2mel length-regulator target
(mel frames, pitch-preserving) to the original slot; residual >5% fixed with gentle atempo (<=1.25x)."""
import json,os,subprocess,sys
from pathlib import Path
VOL=os.environ["VOL"];root=Path(sys.argv[1])
sys.path.insert(0,f"{VOL}/index-tts")
import soundfile as sf
from indextts.infer_v2 import IndexTTS2
ck=f"{VOL}/index-tts/checkpoints"
tts=IndexTTS2(cfg_path=f"{ck}/config.yaml",model_dir=ck,use_fp16=True,use_cuda_kernel=True)
LR=tts.s2mel.models["length_regulator"];SCALE=[1.0];_fwd=LR.forward
def fwd(x,ylens=None,**k):
    return _fwd(x,ylens=(ylens.float()*SCALE[0]).long() if ylens is not None else None,**k)
LR.forward=fwd
def sh(*c):subprocess.run(c,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def ts(s):h,m=divmod(s,3600);m,s=divmod(m,60);return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".",",")
TRIM="silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
def synth(text,ref,path,scale):
    SCALE[0]=scale;tts.infer(spk_audio_prompt=ref,text=text,output_path=path+".raw.wav",verbose=False,interval_silence=50)
    sh("ffmpeg","-y","-i",path+".raw.wav","-af",TRIM,path);os.remove(path+".raw.wav");return sf.info(path).duration  # trim edge silence
for jf in sorted(root.glob("*/segments.json")):
    d=jf.parent;J=json.loads(jf.read_text());S=J["segments"];inputs=[];filt=[];srt=[];md=[]
    for i,s in enumerate(S):
        # slot = original speech span; may borrow up to 0.3s of following gap if long. Start always = original start.
        nxt=S[i+1]["start"] if i+1<len(S) else J["duration"];span=max(s["end"]-s["start"],0.4);room=max(min(nxt-s["start"],span+0.3),span)
        f=str(d/f"seg{i:05}.wav");ref=J["refs"][s["spk"]]
        n=synth(s["zh"],ref,f,1.0);s["ratio_raw"]=round(n/span,3)
        if not 0.92<=n/span<=1.08:  # symmetric: regen with length-regulator scaled toward span (slower or faster)
            n=synth(s["zh"],ref,f,min(max(span/n,0.75),1.35))
        tgt=min(max(n,span),room)  # short->stretch to span; slightly long->use gap; too long->compress to room
        tempo=min(max(n/tgt,0.80),1.30) if not 0.97<=n/tgt<=1.03 else 1.0   # atempo<1 slows down short lines
        inputs+=["-i",f];filt.append(f"[{i+1}:a]aresample=44100,atempo={tempo:.4f},adelay={int(s['start']*1000)}:all=1[a{i}]")
        s["tts_dur"]=round(n/tempo,2);s["slot"]=round(span,2);s["ratio_fit"]=round(n/tempo/span,3)
        srt+=[str(i+1),f"{ts(s['start'])} --> {ts(s['end'])}",s["zh"],""]
        md.append(f"- **[{ts(s['start'])[:8]}] {s['spk']}** {s['zh']}  \n  <sub>{s['en']}</sub>")
    (d/"zh.srt").write_text("\n".join(srt),encoding="utf-8");(d/"transcript.md").write_text("# 中文配音稿\n\n"+"\n".join(md),encoding="utf-8")
    # mix: bgm (demucs no_vocals) + all dubbed segments
    labels="".join(f"[a{i}]" for i in range(len(S)))
    (d/"fc.txt").write_text(";".join(filt)+f";{labels}amix=inputs={len(S)}:normalize=0[v];[0:a]volume=1.0[b];[b][v]amix=inputs=2:normalize=0,alimiter=limit=0.95,apad=whole_dur={J['video_duration']}[o]")
    sh("ffmpeg","-y","-i",str(d/"bgm.wav"),*inputs,"-filter_complex_script",str(d/"fc.txt"),"-map","[o]","-ar","44100","-c:a","pcm_s16le",str(d/"zh_mix.wav"))
    sh("ffmpeg","-y","-i",str(d/"zh_mix.wav"),"-b:a","192k",str(d/"zh_dub.mp3"))
    sh("ffmpeg","-y","-i",str(d/"src.mp4"),"-i",str(d/"zh_mix.wav"),"-i",str(d/"zh.srt"),"-map","0:v","-map","1:a","-map","0:a","-map","2",
       "-c:v","copy","-c:a","aac","-b:a","192k","-c:s","mov_text","-metadata:s:a:0","language=zho","-metadata:s:a:0","title=中文配音",
       "-metadata:s:a:1","language=eng","-metadata:s:s:0","language=zho","-disposition:a:0","default","-disposition:s:0","default",str(d/"zh_dub.mp4"))
    for p in d.glob("seg*.wav"):p.unlink()
    import statistics as st;R=sorted(s["ratio_fit"] for s in S);Q=lambda q:R[min(len(R)-1,int(q*len(R)))]
    J["fit_stats"]={"median":Q(.5),"p10":Q(.1),"p90":Q(.9),"min":R[0],"max":R[-1],"within10":sum(.9<=x<=1.1 for x in R),"n":len(R)}
    print("fit",J["fit_stats"],flush=True)
    jf.write_text(json.dumps(J,ensure_ascii=False,indent=1));print("stage3",d.name,"done",flush=True)
