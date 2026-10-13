#!/usr/bin/env python3
"""Stage 2: EN->ZH via resident vLLM Hunyuan-MT-7B, all segments concurrently."""
import json,sys,concurrent.futures as cf,urllib.request
from pathlib import Path
URL="http://localhost:8000/v1/chat/completions"
def mt(text,ctx):
    # context prompt leaked previous sentence into output in testing -> translate each segment standalone
    p="Translate the following segment into Chinese, without additional explanation.\n\n"+text
    body={"model":"mt","messages":[{"role":"user","content":p}],"temperature":0.7,"top_p":0.6,"top_k":20,"repetition_penalty":1.05,"max_tokens":512}
    r=urllib.request.urlopen(urllib.request.Request(URL,json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=300)
    return json.load(r)["choices"][0]["message"]["content"].strip()
for f in Path(sys.argv[1]).glob("*/segments.json"):
    J=json.loads(f.read_text());S=J["segments"]
    with cf.ThreadPoolExecutor(64) as ex:
        zh=list(ex.map(lambda i:mt(S[i]["en"],S[i-1]["en"] if i else ""),range(len(S))))
    for s,z in zip(S,zh):s["zh"]=z
    f.write_text(json.dumps(J,ensure_ascii=False,indent=1));print("stage2",f.parent.name,len(S),flush=True)
