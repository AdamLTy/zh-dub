#!/usr/bin/env python3
"""Create ONE tagged L40S pod -> setup -> run -> fetch outputs -> terminate THAT pod only.
Safety: never lists/stops other pods. Only acts on pod ids it created, recorded in .runpod_pods.json,
and re-verifies the pod name (prefix zhdub-) before deleting.
env: RUNPOD_API_KEY (required), HF_TOKEN (optional, diarization). SSH key ~/.ssh/id_ed25519(.pub).
usage: python launch_runpod.py URL [URL...] [--out ./dub_out] [--community] [--keep]
       python launch_runpod.py --cleanup   # terminate pods recorded in .runpod_pods.json (own pods only)"""
import argparse,json,os,subprocess,sys,time,uuid,urllib.request
from pathlib import Path
API="https://rest.runpod.io/v1";PREFIX="zhdub-";STATE=Path(__file__).resolve().parent/".runpod_pods.json"
def call(m,p,body=None):
    r=urllib.request.Request(API+p,data=json.dumps(body).encode() if body is not None else None,method=m,
        headers={"Authorization":"Bearer "+os.environ["RUNPOD_API_KEY"],"Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=60) as x:t=x.read();return json.loads(t) if t else {}
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
ap.add_argument("--image",default="runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04");A=ap.parse_args()
if not os.getenv("RUNPOD_API_KEY"):sys.exit("RUNPOD_API_KEY not set")
if A.cleanup:
    for pid in list(state()):terminate(pid)
    sys.exit()
if not A.urls:sys.exit("give at least one URL")
key=Path.home()/".ssh/id_ed25519";pub=key.with_suffix(".pub").read_text().strip()
name=PREFIX+uuid.uuid4().hex[:8]
body={"name":name,"imageName":A.image,"gpuTypeIds":["NVIDIA L40S"],"gpuCount":1,"cloudType":"COMMUNITY" if A.community else "SECURE",
      "containerDiskInGb":40,"volumeInGb":100,"volumeMountPath":"/workspace","ports":["22/tcp"],"supportPublicIp":True,
      "env":{"PUBLIC_KEY":pub}}  # no network volume: pod-local disk only, deleted with the pod
pod=call("POST","/pods",body);pid=pod["id"];s=state();s[pid]={"name":name,"created":time.time()};save(s)
print("created own pod",pid,name,"$/hr",pod.get("costPerHr"),flush=True)
try:
    while True:
        p=call("GET",f"/pods/{pid}");ip,port=p.get("publicIp"),(p.get("portMappings") or {}).get("22")
        if ip and port:break
        time.sleep(10)
    o=["-i",str(key),"-o","StrictHostKeyChecking=no","-o","ServerAliveInterval=30"]
    ssh=["ssh",*o,"-p",str(port),f"root@{ip}"];rsh=f"ssh {' '.join(o)} -p {port}"
    for _ in range(30):
        if subprocess.run(ssh+["true"],capture_output=True).returncode==0:break
        time.sleep(10)
    here=Path(__file__).resolve().parent
    subprocess.run(["rsync","-a","--exclude=.git","--exclude=.runpod_pods.json","-e",rsh,f"{here}/",f"root@{ip}:/workspace/zh-dub/"],check=True)
    job="/workspace/jobs/"+time.strftime("%Y%m%d-%H%M%S")
    q=" ".join("'"+u.replace("'","")+"'" for u in A.urls)
    env=f"export HF_TOKEN='{os.environ['HF_TOKEN']}'; " if os.getenv("HF_TOKEN") else ""
    subprocess.run(ssh+[f"{env}bash /workspace/zh-dub/scripts/setup.sh && bash /workspace/zh-dub/scripts/run_job.sh {job} {q}"],check=True)
    Path(A.out).mkdir(parents=True,exist_ok=True)
    subprocess.run(["rsync","-av","-e",rsh,"--include=*/",*[f"--include={x}" for x in
        ("zh_dub.mp4","zh_dub.mp3","zh.srt","transcript.md","segments.json","timing.txt")],"--exclude=*",f"root@{ip}:{job}/",A.out],check=True)
    print("outputs ->",A.out)
finally:
    if not A.keep:terminate(pid)
    else:print("kept running:",pid,"-> later: python launch_runpod.py --cleanup")
