#!/usr/bin/env python3
"""Stage 3 (audio mode, default): natural-rate IndexTTS2 per segment (no time-stretch), cloned voice per speaker,
concatenated with natural pauses (original gap clamped; extra pause on speaker change). Writes zh_audio.mp3 and
timestamps for the NEW audio: zh.lrc, zh.srt, zh.vtt (+ bilingual *.bi.* variants)."""
import json,os,subprocess,sys
from pathlib import Path
VOL=os.environ.get("APP") or os.environ["VOL"];root=Path(sys.argv[1])
sys.path.insert(0,f"{VOL}/index-tts")
import re,time,numpy as np,soundfile as sf
SR=24000;NW=int(os.getenv("TTS_WORKERS","3"))  # parallel IndexTTS2 processes on one 48GB GPU (~10GB each)
TRIM="silenceremove=start_periods=1:start_threshold=-45dB,areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse"
def sh(*c):subprocess.run(c,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def t_srt(s,sep=","):h,m=divmod(s,3600);m,s=divmod(m,60);return f"{int(h):02}:{int(m):02}:{s:06.3f}".replace(".",sep)
def t_lrc(s):m,s=divmod(s,60);return f"[{int(m):02}:{s:05.2f}]"
def safe(t):return re.sub(r"[^\w\u4e00-\u9fff$.-]+","_",t).strip("_")[:80] or "audio"
if len(sys.argv)>3 and sys.argv[2]=="--worker":   # worker: synthesize segments i % N == k (resumable)
    k,N=int(sys.argv[3]),int(sys.argv[4])
    from indextts.infer_v2 import IndexTTS2
    ck=f"{VOL}/index-tts/checkpoints"
    tts=IndexTTS2(cfg_path=f"{ck}/config.yaml",model_dir=ck,use_fp16=True,use_cuda_kernel=True)
    print(f"worker{k}: bigvgan cuda kernel = {getattr(tts,'use_cuda_kernel',None)}",flush=True)
    for jf in sorted(root.glob("*/segments.json")):
        d=jf.parent;S=json.loads(jf.read_text())["segments"];t0=time.time();n=0
        for i,s in enumerate(S):
            if i%N!=k or (d/f"seg{i:05}.wav").exists():continue
            raw=str(d/f"seg{i:05}.w{k}.raw.wav")
            tts.infer(spk_audio_prompt=s["tts_ref"],text=s["zh"],output_path=raw,verbose=False,interval_silence=150)
            sh("ffmpeg","-y","-i",raw,"-af",TRIM,"-ar",str(SR),"-ac","1",str(d/f"seg{i:05}.tmp.wav"));(d/f"seg{i:05}.ref").write_text(s["tts_ref"]);os.replace(d/f"seg{i:05}.tmp.wav",d/f"seg{i:05}.wav");os.remove(raw)
            n+=1
            if n%50==0:print(f"worker{k}: {n} segs, {time.time()-t0:.0f}s",flush=True)
    sys.exit(0)
for jf in sorted(root.glob("*/segments.json")):
    d=jf.parent;J=json.loads(jf.read_text());S=J["segments"];chunks=[];t=0.0
    J["title"]=J.get("title") or os.getenv("TITLE") or d.name;base=safe(J["title"])
    mf=d/"speaker_merge.json"   # optional {"S2":"S1"}: diarization split of one voice -> merge before refs/TTS
    if mf.exists():
        M=json.loads(mf.read_text());n=0
        for s in S:
            if s["spk"] in M:s.setdefault("spk_diar",s["spk"]);s["spk"]=M[s["spk"]];n+=1
        for k in M:J["refs"].pop(k,None)
        J["speaker_merge"]={"map":M,"segments":n};print("speaker_merge",J["speaker_merge"],flush=True)
    if J.get("speaker_fixes") and (d/"vocals.wav").exists():
        # re-extract each speaker's clone reference from corrected, confident segments only (skip changed/uncertain, >=1.5s)
        for spk in sorted({s["spk"] for s in S}):
            good=sorted([s for s in S if s["spk"]==spk and not s.get("spk_uncertain") and "spk_diar" not in s and s["end"]-s["start"]>=1.5],
                        key=lambda s:s["end"]-s["start"],reverse=True)
            pick,tot=[],0
            for s in good:
                if tot>=12:break
                pick.append(s);tot+=s["end"]-s["start"]
            if not pick:continue
            sel="+".join(f"between(t,{s['start']:.2f},{s['end']:.2f})" for s in pick);rf=d/f"ref2_{spk}.wav"
            sh("ffmpeg","-y","-i",str(d/"vocals.wav"),"-af",f"aselect='{sel}',asetpts=N/SR/TB","-t","15","-ac","1","-ar","24000",str(rf))
            J["refs"][spk]=str(rf)
        J["refs_source"]="corrected+confident segments"
    for s in S:s["tts_ref"]=J["refs"][s["spk"]]
    jf.write_text(json.dumps(J,ensure_ascii=False,indent=1))
    t1=time.time();W=[subprocess.Popen([sys.executable,__file__,str(root),"--worker",str(k),str(NW)]) for k in range(NW)]
    if any(w.wait() for w in W):raise SystemExit("TTS worker failed")
    J["tts_seconds"]=round(time.time()-t1);J["tts_workers"]=NW
    for i,s in enumerate(S):
        f=d/f"seg{i:05}.wav";a,_=sf.read(str(f),dtype="float32");s["tts_ref_used"]=(d/f"seg{i:05}.ref").read_text()
        if i:
            gap=S[i]["start"]-S[i-1]["end"];pause=min(max(gap,0.25),1.2)+(0.35 if s["spk"]!=S[i-1]["spk"] else 0)
            chunks.append(np.zeros(int(pause*SR),np.float32));t+=pause
        s["zh_start"]=round(t,3);t+=len(a)/SR;s["zh_end"]=round(t,3);chunks.append(a)
    sf.write(str(d/"zh_audio.wav"),np.concatenate(chunks),SR)
    title=J["title"];sh("ffmpeg","-y","-i",str(d/"zh_audio.wav"),"-af","loudnorm=I=-16:TP=-1.5","-b:a",os.getenv("MP3_BITRATE","96k"),
        "-id3v2_version","3","-metadata",f"title={title}（中文版）","-metadata","artist=zh-dub","-metadata",f"album={title}",
        "-metadata","language=zho",str(d/f"{base}.zh.mp3"))
    name={k:k for k in J["refs"]}
    for bi in (False,True):
        sfx=".bi" if bi else ""
        txt=lambda s:(f"{s['spk']}：{s['zh']}"+(f"\n{s['en']}" if bi else ""))
        lrc=[f"[ti:{title}（中文版）]","[ar:zh-dub]","[la:zh]"]+[t_lrc(s["zh_start"])+txt(s).replace("\n"," / ") for s in S]+[t_lrc(t)]
        (d/f"{base}.zh{sfx}.lrc").write_text("\n".join(lrc)+"\n",encoding="utf-8")
        (d/f"{base}.zh{sfx}.srt").write_text("\n".join(f"{i+1}\n{t_srt(s['zh_start'])} --> {t_srt(s['zh_end'])}\n{txt(s)}\n" for i,s in enumerate(S)),encoding="utf-8")
        (d/f"{base}.zh{sfx}.vtt").write_text("WEBVTT\n\n"+"\n".join(f"{t_srt(s['zh_start'],'.')} --> {t_srt(s['zh_end'],'.')}\n{txt(s)}\n" for s in S),encoding="utf-8")
    F=J.get("speaker_fixes");fx=""
    if F:
        fx=f"\n\n## 说话人校正（Claude）\n提议 {F['proposed']} 处，采纳 {F['applied']} 处（置信度 ≥ {F['threshold']}）\n"+"".join(
            f"\n- #{x['seg_id']} {x['old_spk']}→{x['new_spk']} ({x.get('confidence')}){' ✅' if x.get('applied') else ' ✗ 未采纳'}：{x['en'][:80]} — {x.get('reason','')}" for x in F["items"])
    (d/"transcript.md").write_text("# 中文稿\n\n"+"\n".join(f"- **[{t_srt(s['zh_start'])[:8]}] {s['spk']}** {s['zh']}  \n  <sub>{s['en']}</sub>" for s in S)+fx,encoding="utf-8")
    # consistency check: every segment synthesized with the reference of its final (corrected) speaker label
    bad=[i for i,s in enumerate(S) if s.get("tts_ref_used")!=J["refs"][s["spk"]] or f"_{s['spk']}.wav" not in s["tts_ref"]]
    J["consistency"]={"segments":len(S),"mismatched":bad,"ok":not bad};print("consistency",J["consistency"],flush=True)
    if bad:raise SystemExit(f"speaker/voice mismatch in segments {bad}")
    J["zh_audio_duration"]=round(t,2);os.remove(d/"zh_audio.wav")
    for f in [*d.glob("seg*.wav"),*d.glob("seg*.ref")]:f.unlink()
    jf.write_text(json.dumps(J,ensure_ascii=False,indent=1));print("stage3_audio",d.name,f"{t:.0f}s vs source {J['duration']:.0f}s",flush=True)
