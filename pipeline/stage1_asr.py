#!/usr/bin/env python3
"""Stage 1 (asr venv): download, demucs vocals/bgm split, Parakeet TDT v2 ASR w/ timestamps, optional pyannote diarization,
per-speaker reference clips. Models loaded once for all URLs. Writes <job>/segments.json"""
import json,os,re,subprocess,sys
from pathlib import Path
out=Path(sys.argv[1]);urls=sys.argv[2:]
def sh(*c):subprocess.run(c,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
import torch,soundfile as sf
import nemo.collections.asr as nemo_asr
asr=nemo_asr.models.ASRModel.from_pretrained("nvidia/parakeet-tdt-0.6b-v2").cuda().eval()
asr.change_attention_model("rel_pos_local_attn",[256,256]);asr.change_subsampling_conv_chunking_factor(1)  # long-form (hours)
dia=None
if os.getenv("HF_TOKEN"):
    try:
        from pyannote.audio import Pipeline
        dia=Pipeline.from_pretrained("pyannote/speaker-diarization-3.1",use_auth_token=os.environ["HF_TOKEN"]).to(torch.device("cuda"))
    except Exception as e:print("pyannote unavailable:",e)
sfm=None
if dia is None:  # ungated fallback: NVIDIA Streaming Sortformer (up to 4 speakers, long-form)
    from nemo.collections.asr.models import SortformerEncLabelModel
    sfm=SortformerEncLabelModel.from_pretrained("nvidia/diar_streaming_sortformer_4spk-v2").cuda().eval()
    M=sfm.sortformer_modules;M.chunk_len,M.chunk_right_context,M.fifo_len,M.spkcache_update_period=340,40,40,300
for url in urls:
    vid=re.sub(r"\W","_",Path(url).stem if os.path.isfile(url) else url)[-16:];d=out/vid;d.mkdir(parents=True,exist_ok=True)
    if not (d/"src.mp4").exists():
        cs,cd=os.getenv("CLIP_START"),os.getenv("CLIP_DUR")
        if os.path.isfile(url):  # local media (e.g. uploaded because YouTube blocks datacenter IPs)
            cut=(["-ss",cs] if cs else [])+(["-t",cd] if cd else [])
            sh("ffmpeg","-y",*cut,"-i",url,"-c","copy",str(d/"src.mp4"))
        else:
            sec=["--download-sections",f"*{cs or 0}-{float(cs or 0)+float(cd) if cd else 'inf'}","--force-keyframes-at-cuts"] if (cs or cd) else []
            sh("yt-dlp","-f","bv*[height<=1080]+ba/b","--merge-output-format","mp4",*sec,"-o",str(d/"src.mp4"),url)
    sh("ffmpeg","-y","-i",str(d/"src.mp4"),"-ac","2","-ar","44100",str(d/"src44.wav"))
    # demucs: vocals vs everything else (music/ambience kept as bed)
    sh(sys.executable,"-m","demucs","--two-stems=vocals","-n","htdemucs","-o",str(d/"sep"),str(d/"src44.wav"))
    sep=d/"sep/htdemucs/src44";(sep/"no_vocals.wav").replace(d/"bgm.wav");(sep/"vocals.wav").replace(d/"vocals.wav")
    sh("ffmpeg","-y","-i",str(d/"vocals.wav"),"-ac","1","-ar","16000",str(d/"vocals16.wav"))
    with torch.inference_mode():
        h=asr.transcribe([str(d/"vocals16.wav")],timestamps=True,batch_size=1)[0]
    segs=[{"start":s["start"],"end":s["end"],"en":s["segment"].strip()} for s in h.timestamp["segment"] if s["segment"].strip()]
    # speaker per segment: max overlap with diarization turns
    turns=[]
    if sfm is not None:
        with torch.inference_mode():
            turns=[(float(a),float(b),k.replace("speaker_","S")) for a,b,k in (x.split() for x in sfm.diarize(audio=[str(d/"vocals16.wav")],batch_size=1)[0])]
    elif dia:
        turns=[(t.start,t.end,spk) for t,_,spk in dia(str(d/"vocals16.wav")).itertracks(yield_label=True)]
    for s in segs:
        ov={};[ov.__setitem__(k,ov.get(k,0)+max(0,min(e,s["end"])-max(b,s["start"]))) for b,e,k in turns]
        s["spk"]=max(ov,key=ov.get) if ov and max(ov.values())>0 else "S0"
    # reference clip per speaker: concat their longest clean segments up to ~12s (IndexTTS2 prompt)
    refs={}
    for spk in {s["spk"] for s in segs}:
        mine=sorted([s for s in segs if s["spk"]==spk],key=lambda s:s["end"]-s["start"],reverse=True)
        pick,tot=[],0
        for s in mine:
            if tot>=12:break
            pick.append(s);tot+=s["end"]-s["start"]
        sel="+".join(f"between(t,{s['start']:.2f},{s['end']:.2f})" for s in pick)
        f=d/f"ref_{spk}.wav";sh("ffmpeg","-y","-i",str(d/"vocals.wav"),"-af",f"aselect='{sel}',asetpts=N/SR/TB","-t","15","-ac","1","-ar","24000",str(f))
        refs[spk]=str(f)
    dur=sf.info(str(d/"src44.wav")).duration
    (d/"segments.json").write_text(json.dumps({"url":url,"duration":dur,"refs":refs,"segments":segs},ensure_ascii=False,indent=1))
    print("stage1",vid,len(segs),"segs",len(refs),"speakers",flush=True)
