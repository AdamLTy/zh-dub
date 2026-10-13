#!/usr/bin/env python3
"""Stage 2b: duration-budgeted rewrite (Qwen3-8B on vLLM). Per segment target Chinese char range from slot length and
speaker speaking rate; rewrite only segments outside range (shorten / naturally expand, drop parentheticals, spoken tone)."""
import json,re,sys,statistics as st,concurrent.futures as cf,urllib.request
from pathlib import Path
URL="http://localhost:8000/v1/chat/completions"
BASE=4.5   # zh chars/s at median English pace
def n_zh(t):return len(re.findall(r"[\u4e00-\u9fff0-9A-Za-z]",t))
def chat(p):
    body={"model":"mt","messages":[{"role":"user","content":p}],"temperature":0.7,"top_p":0.8,"top_k":20,"max_tokens":400,
          "chat_template_kwargs":{"enable_thinking":False}}
    r=urllib.request.urlopen(urllib.request.Request(URL,json.dumps(body).encode(),{"Content-Type":"application/json"}),timeout=300)
    t=json.load(r)["choices"][0]["message"]["content"];t=re.sub(r"<think>.*?</think>","",t,flags=re.S).strip()
    return re.sub(r"[（(][^）)]*[）)]","",t.splitlines()[-1] if t else "").strip().strip('"“”')
def fit(s):
    lo,hi=s["zh_lo"],s["zh_hi"];z=s["zh"];best=z
    if lo<=n_zh(z)<=hi:return z,0
    for k in range(2):
        how="缩短" if n_zh(best)>hi else "自然地扩充（补足语气、连接词或把意思说完整，不要加无意义的填充词）"
        p=(f"你是视频中文配音的台词编辑。下面是英文原句和中文译文。请把中文译文{how}，使其正好为 {lo}–{hi} 个汉字，"
           f"用自然口语化的简体中文，忠实原意，去掉括号内容，不要解释，只输出改写后的一句话。\n英文：{s['en']}\n中文译文：{best}"
           +(f"\n（上一次输出 {n_zh(best)} 字，不符合要求）" if k else ""))
        c=chat(p)
        if c and abs(n_zh(c)-(lo+hi)/2)<abs(n_zh(best)-(lo+hi)/2):best=c
        if lo<=n_zh(best)<=hi:break
    return best,k+1
for f in Path(sys.argv[1]).glob("*/segments.json"):
    J=json.loads(f.read_text());S=J["segments"]
    # speaker speaking rate: English words/sec relative to overall median -> per-speaker zh chars/s
    wps=lambda ss:sum(len(s["en"].split()) for s in ss)/max(sum(s["end"]-s["start"] for s in ss),1e-3)
    allr=wps(S);rate={k:min(max(BASE*wps([s for s in S if s["spk"]==k])/allr,3.8),5.5) for k in {s["spk"] for s in S}}
    for s in S:
        t=(s["end"]-s["start"])*rate[s["spk"]];s["zh_mt"]=s["zh"];s["zh_lo"]=max(1,round(t*0.85));s["zh_hi"]=max(2,round(t*1.10))
    with cf.ThreadPoolExecutor(64) as ex:res=list(ex.map(fit,S))
    for s,(z,tries) in zip(S,res):s["zh"]=z;s["fit_tries"]=tries
    ok=sum(s["zh_lo"]<=n_zh(s["zh"])<=s["zh_hi"] for s in S);bef=sum(s["zh_lo"]<=n_zh(s["zh_mt"])<=s["zh_hi"] for s in S)
    J["rate_zh_cps"]={k:round(v,2) for k,v in rate.items()}
    f.write_text(json.dumps(J,ensure_ascii=False,indent=1))
    print(f"stage2b {f.parent.name}: in-budget {bef}->{ok}/{len(S)}, rewritten {sum(1 for _,t in res if t)} rates {J['rate_zh_cps']}",flush=True)
