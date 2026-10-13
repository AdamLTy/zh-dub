#!/usr/bin/env python3
"""Stage 2 (Claude): style-B "播客自然风" faithful EN->ZH, ~40-segment chunks with surrounding context (±60 segs),
JSON {id: zh} output validated (all ids, non-empty); missing ids retried once, then Hunyuan/blank fallback flagged.
Runs on the launcher host (needs ANTHROPIC_API_KEY); pod never sees the key. usage: stage2_claude.py JOBDIR [--model M]"""
import json,os,re,sys,time,urllib.request
from pathlib import Path
MODEL=os.getenv("CLAUDE_MODEL","claude-sonnet-5-5");CH=40;CTX=60
STYLE=("你是资深中文播客译者。把英文播客/访谈逐句译成简体中文，像中文播客在自然聊天：意思完整忠实，按中文习惯重组句子，"
       "可以拆分长句、调整语序，把英文口头禅（like / you know / I think 的堆叠）换成自然的中文衔接词，但不得省略任何观点、细节、举例或语气；"
       "不要添加原文没有的信息；避免翻译腔；人名/公司名用通行译法（Meta、马克·扎克伯格可作“马克”、Alex 保留英文）。")
def call(prompt):
    b={"model":MODEL,"max_tokens":8000,"messages":[{"role":"user","content":prompt}]}
    for a in range(4):
        try:
            r=urllib.request.Request("https://api.anthropic.com/v1/messages",json.dumps(b).encode(),
              {"x-api-key":os.environ["ANTHROPIC_API_KEY"],"anthropic-version":"2023-06-01","content-type":"application/json"})
            j=json.load(urllib.request.urlopen(r,timeout=600))
            return "".join(c.get("text","") for c in j["content"]),j.get("usage",{})
        except Exception as e:
            if a==3:raise
            time.sleep(5*(a+1))
def parse(t):
    m=re.search(r"\{.*\}",t,re.S)
    try:return {int(k):str(v).strip() for k,v in json.loads(m.group(0)).items()} if m else {}
    except Exception:return {}
USAGE={"input_tokens":0,"output_tokens":0,"calls":0}
def translate(S,ids):
    lo,hi=max(0,ids[0]-CTX),min(len(S),ids[-1]+CTX+1)
    ctx="\n".join(f"{i}|[{S[i]['spk']}] {S[i]['en']}" for i in range(lo,hi))
    todo="\n".join(f"{i}|[{S[i]['spk']}] {S[i]['en']}" for i in ids)
    p=(f"{STYLE}\n\n上下文（仅供理解，不用翻译）：\n{ctx}\n\n请翻译以下编号的句子，每个编号单独翻译、不要合并或拆到别的编号里。"
       f"只输出一个 JSON 对象，键为编号（字符串），值为译文：\n{todo}")
    t,u=call(p);USAGE["calls"]+=1
    for k in("input_tokens","output_tokens"):USAGE[k]+=u.get(k,0)
    return parse(t)
for f in sorted(Path(sys.argv[1]).glob("*/segments.json")):
    J=json.loads(f.read_text());S=J["segments"];out={}
    for c in range(0,len(S),CH):
        ids=list(range(c,min(c+CH,len(S))));r=translate(S,ids)
        miss=[i for i in ids if not r.get(i)]
        if miss:r.update(translate(S,miss))
        out.update(r)
    bad=0
    for i,s in enumerate(S):
        if out.get(i):s["zh"]=out[i];s["mt"]="claude"
        else:bad+=1;s["mt"]="fallback"  # keep Hunyuan zh if stage2_mt ran, else English
        s.setdefault("zh",s["en"])
    J["mt"]={"engine":MODEL,"style":"B 播客自然风","fallback_segments":bad,"usage":dict(USAGE)}
    f.write_text(json.dumps(J,ensure_ascii=False,indent=1))
    print(f"stage2_claude {f.parent.name}: {len(S)-bad}/{len(S)} ok, usage {USAGE}",flush=True)
