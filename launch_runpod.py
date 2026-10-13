#!/usr/bin/env python3
"""Create ONE tagged L40S pod -> setup -> run -> fetch outputs -> terminate THAT pod only.
Safety: never lists/stops other pods. Only acts on pod ids it created, recorded in .runpod_pods.json,
and re-verifies the pod name (prefix zhdub-) before deleting.
env: RUNPOD_API_KEY (required), HF_TOKEN (optional, diarization). SSH key ~/.ssh/id_ed25519(.pub).
Caps: --max-hours (default 2) wall-clock incl. setup; pod terminated on timeout/failure.
Inputs may be URLs or local media files (uploaded to the pod). --start/--duration clip (seconds).
usage: python launch_runpod.py URL|FILE [...] [--start S] [--duration D] [--out ./dub_out] [--community] [--keep]
       python launch_runpod.py --cleanup   # terminate pods recorded in .runpod_pods.json (own pods only)"""
import urllib.error,argparse,json,os,subprocess,sys,time,uuid,urllib.request
from pathlib import Path
API="https://rest.runpod.io/v1";PREFIX="zhdub-";STATE=Path(__file__).resolve().parent/".runpod_pods.json"
def call(m,p,body=None):
    r=urllib.request.Request(API+p,data=json.dumps(body).encode() if body is not None else None,method=m,
        headers={"Authorization":"Bearer "+os.environ["RUNPOD_API_KEY"],"Content-Type":"application/json","User-Agent":"zh-dub-launcher/0.1"})
    try:
        with urllib.request.urlopen(r,timeout=60) as x:t=x.read();return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:raise SystemExit(f"Runpod API {m} {p} -> {e.code}: {e.read()[:500].decode(errors='replace')}")
def state():return json.loads(STATE.read_text()) if STATE.exists() else {}
def save(s):STATE.write_text(json.dumps(s,indent=1))
def terminate(pid):
    s=state()
    if pid not in s:sys.exit(f"refusing: {pid} was not created by this launcher")
    name=call("GET",f"/pods/{pid}").get("name","")
    if not name.startswith(PREFIX) or name!=s[pid]["name"]:sys.exit(f"refusing: {pid} name mismatch ({name})")
    call("DELETE",f"/pods/{pid}");s.pop(pid);save(s);print("terminated own pod",pid)
ap=argparse.ArgumentParser();ap.add_argument("urls",nargs="*");ap.add_argument("--out",default="./dub_out")
ap.add_argument("--community",action="store_true");ap.add_argument("--keep",action="store_true");ap.add_argument("--cleanup",action="store_true")
ap.add_argument("--no-verify-speakers",action="store_true",help="skip Claude speaker-attribution check (on by default with --mt claude)");ap.add_argument("--mt",choices=["claude","hunyuan"]);ap.add_argument("--mode",choices=["audio","video"],default="audio");ap.add_argument("--title",default="");ap.add_argument("--tts-workers",type=int,default=3);ap.add_argument("--start");ap.add_argument("--duration");ap.add_argument("--max-hours",type=float,default=2.0)
ap.add_argument("--segments",help="reuse a finished segments.json (transcript+speakers+zh): skips ASR/diarization, speaker check and MT; stage1 only redoes demucs+refs")
ap.add_argument("--speaker-merge",help="speaker_merge.json to place in the job dir, e.g. {\"S2\":\"S1\"}")
ap.add_argument("--partial",help="dir of previously saved seg*.wav/seg*.ref to upload so stage3 resumes")
ap.add_argument("--image",default="ghcr.io/adamlty/zh-dub:latest",help="prebuilt image; use runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04 for from-scratch setup");A=ap.parse_args()
if not os.getenv("RUNPOD_API_KEY"):sys.exit("RUNPOD_API_KEY not set")
import shutil  # preflight BEFORE creating a pod: local tools + ssh key
miss=[b for b in ("ssh","tar") if not shutil.which(b)]
if miss:sys.exit(f"missing local tools: {miss} (e.g. apt-get install openssh-client tar)")
if not (Path.home()/".ssh/id_ed25519.pub").exists():sys.exit("missing ~/.ssh/id_ed25519(.pub): ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519")
if A.cleanup:
    for pid in list(state()):terminate(pid)
    sys.exit()
if not A.urls:sys.exit("give at least one URL")
key=Path.home()/".ssh/id_ed25519";pub=key.with_suffix(".pub").read_text().strip()
name=PREFIX+uuid.uuid4().hex[:8]
body={"name":name,"imageName":A.image,"gpuTypeIds":["NVIDIA L40S"],"allowedCudaVersions":os.getenv("ZHDUB_CUDA","13.0").split(","),"gpuCount":1,"cloudType":"COMMUNITY" if A.community else "SECURE",
      "containerDiskInGb":60,"volumeInGb":80,"volumeMountPath":"/workspace","ports":["22/tcp"],"supportPublicIp":True,
      "env":{"PUBLIC_KEY":pub}}  # no network volume: pod-local disk only, deleted with the pod
START=time.time()
for n in range(int(os.getenv("ZHDUB_CREATE_TRIES","40"))):  # capacity can be momentarily empty: retry creation (no pod exists yet)
    try:pod=call("POST","/pods",body);break
    except SystemExit as e:
        if "no instances" not in str(e):raise
        print(time.strftime("%H:%M"),"no L40S capacity, retrying in 60s",flush=True);time.sleep(60)
else:sys.exit("no capacity after retries")
pid=pod["id"];s=state();s[pid]={"name":name,"created":time.time()};save(s)
print("created own pod",pid,name,"$/hr",pod.get("costPerHr"),flush=True)
try:
    while True:
        p=call("GET",f"/pods/{pid}");ip,port=p.get("publicIp"),(p.get("portMappings") or {}).get("22")
        if ip and port:break
        time.sleep(10)
    o=["-i",str(key),"-o","StrictHostKeyChecking=no","-o","ServerAliveInterval=30","-o","ServerAliveCountMax=6","-o","ConnectTimeout=20"]
    ssh=["ssh",*o,"-p",str(port),f"root@{ip}"];rsh=f"ssh {' '.join(o)} -p {port}"
    for _ in range(30):
        if subprocess.run(ssh+["true"],capture_output=True).returncode==0:break
        time.sleep(10)
    here=Path(__file__).resolve().parent
    def put(src_dir,names,dst):  # tar over ssh (no rsync needed on either side)
        t=subprocess.Popen(["tar","-C",str(src_dir),"-cf","-",*names],stdout=subprocess.PIPE)
        subprocess.run(ssh+[f"mkdir -p {dst} && tar --no-same-owner -C {dst} -xf -"],stdin=t.stdout,check=True);t.wait()
    put(here,[x.name for x in here.iterdir() if x.name not in(".git",".runpod_pods.json","__pycache__")],"/workspace/zh-dub")
    env=""
    if os.getenv("HF_TOKEN"):  # send via stdin to a 600 file; never on a command line or in logs
        subprocess.run(ssh+["umask 077; cat > /root/.hf_token"],input=os.environ["HF_TOKEN"].encode(),check=True)
        env="export HF_TOKEN=$(cat /root/.hf_token); "
    subprocess.run(ssh+["mkdir -p /workspace/media /workspace/jobs"],check=True);items=[]
    for u in A.urls:
        if os.path.isfile(u):
            put(Path(u).resolve().parent,[Path(u).name],"/workspace/media")
            items.append("/workspace/media/"+Path(u).name)
        else:items.append(u)
    job="/workspace/jobs/"+time.strftime("%Y%m%d-%H%M%S")
    q=" ".join("'"+u.replace("'","")+"'" for u in items)
    import shlex;env+=f"export TITLE={shlex.quote(A.title)} TTS_WORKERS={A.tts_workers}; "
    env+=f"export MODE={A.mode}; "+("export APP=/opt/zhdub; " if "zh-dub" in A.image else "")+("" if (A.mt=="hunyuan" or A.mode=="video") else "export WITH_VLLM=0; ")+("export NEED_LLM=1; " if (A.mt=="hunyuan" or A.mode=="video") else "")
    if A.start:env+=f"export CLIP_START={float(A.start)}; "
    if A.duration:env+=f"export CLIP_DUR={float(A.duration)}; "
    left=lambda:max(60,A.max_hours*3600-(time.time()-START))
    mt=A.mt or ("claude" if A.mode=="audio" else "hunyuan")
    if mt=="claude" and not (os.getenv("ZHDUB_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")):sys.exit("--mt claude needs ZHDUB_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) on this host")
    ABORT=Path(A.out)/"ABORT"  # touch this file to abort (outputs are still pulled first)
    def rssh(cmd,tries=40,**kw):  # ssh with retries + backoff; a dropped connection is never fatal by itself
        for n in range(tries):
            r=subprocess.run(ssh+[cmd],capture_output=True,text=True,**kw)
            if r.returncode!=255:return r
            print(f"ssh unreachable ({n+1}/{tries}), retrying",flush=True);time.sleep(min(15*(n+1),120))
        return r
    def run(st,log):  # detached on the pod (setsid nohup) with an rc marker; poll until done/failed/cap/abort
        rc=f"{job}.{log}.rc";cmd=f"{env}export STAGES={st}; bash /workspace/zh-dub/scripts/setup.sh && bash /workspace/zh-dub/scripts/run_job.sh {job} {q}"
        rssh(f"rm -f {rc}; setsid nohup bash -c {shlex.quote(cmd+'; echo $? > '+rc)} >> {job}.{log}.log 2>&1 < /dev/null & echo started",tries=10)
        last=""
        while True:
            if time.time()-START>A.max_hours*3600:raise SystemExit("hard time cap reached")
            if ABORT.exists():raise SystemExit("ABORT file present")
            r=rssh(f"cat {rc} 2>/dev/null; echo ---; tail -n 2 {job}.{log}.log | tr '\\r' '\\n' | tail -n 1")
            if r.returncode==0:
                code,_,tail=r.stdout.partition("---")
                if tail.strip()!=last:last=tail.strip();print(time.strftime("%H:%M"),last[:160],flush=True)
                if code.strip():
                    if code.strip()!="0":raise SystemExit(f"stage {st} failed rc={code.strip()}")
                    return
            time.sleep(60)
    if A.segments:  # rerun with a finished segments.json: no ASR / Claude
        import tempfile;stg=Path(tempfile.mkdtemp())
        import re;vid=re.sub(r"\W","_",Path(A.urls[0]).stem if os.path.isfile(A.urls[0]) else A.urls[0])[-16:]
        (stg/vid).mkdir();shutil.copy(A.segments,stg/vid/"segments.json")
        if A.speaker_merge:shutil.copy(A.speaker_merge,stg/vid/"speaker_merge.json")
        if A.partial:
            for f in Path(A.partial).glob("seg*.*"):
                if f.suffix in(".wav",".ref") and ".raw" not in f.name and ".tmp" not in f.name:shutil.copy(f,stg/vid/f.name)
        put(stg,[vid],job);env+="export KEEP_SEGMENTS=1; ";run("13","job")
    elif mt=="hunyuan":run("123","job")
    else:  # Claude translation runs HERE; the API key never goes to the pod
        run("1","stage1")
        loc=Path(A.out)/"_seg";loc.mkdir(parents=True,exist_ok=True)
        g=subprocess.Popen(ssh+[f"cd {job} && tar -cf - */segments.json"],stdout=subprocess.PIPE);subprocess.run(["tar","-C",str(loc),"-xf","-"],stdin=g.stdout,check=True);g.wait()
        if not A.no_verify_speakers:
            t=time.time();subprocess.run([sys.executable,str(here/"pipeline/stage1b_speakers.py"),str(loc)],check=True,timeout=left())
            print(f"claude_speakers_s={time.time()-t:.0f}",flush=True)
        t=time.time();subprocess.run([sys.executable,str(here/"pipeline/stage2_claude.py"),str(loc)],check=True,timeout=left())
        print(f"claude_mt_s={time.time()-t:.0f}",flush=True)
        t=subprocess.Popen(["tar","-C",str(loc),"-cf","-",*[str(p.relative_to(loc)) for p in loc.glob("*/segments.json")]],stdout=subprocess.PIPE)
        subprocess.run(ssh+[f"tar --no-same-owner -C {job} -xf -"],stdin=t.stdout,check=True);t.wait()
        run("3","stage3")
    print("job ok; outputs ->",A.out)
finally:
    if "job" in dir():  # ALWAYS pull outputs + partial work (seg wavs, refs, logs) before any terminate; retried
        Path(A.out).mkdir(parents=True,exist_ok=True)
        pats=" ".join(f"-name '{x}' -o" for x in ("zh_dub.mp4","zh_dub.mp3","*.mp3","*.srt","*.lrc","*.vtt","transcript.md","segments.json","speaker_fixes.json","speaker_merge.json","timing.txt","seg[0-9]*[0-9].wav","seg*.ref","ref*.wav","*.rc"))+" -name '*.log'"
        for n in range(8):
            g=subprocess.Popen(ssh+[f"cd /workspace/jobs && find . -type f \\( {pats} \\) -print0 | tar --null -T - -cf -"],stdout=subprocess.PIPE)
            x=subprocess.run(["tar","-C",A.out,"-xf","-"],stdin=g.stdout);g.wait()
            if g.returncode==0 and x.returncode==0:print("fetched outputs ->",A.out,flush=True);break
            print(f"fetch failed ({n+1}/8), retrying",flush=True);time.sleep(30*(n+1))
    if not A.keep:terminate(pid)
    else:print("kept running:",pid,"-> later: python launch_runpod.py --cleanup")
