#!/usr/bin/env python3
"""Stage 1b (Claude, launcher host): verify speaker attribution from dialogue context (Q/A turn-taking,
self-references, names, interjections). Chunks of 120 segs with 20 overlap. Auto-applies confidence>=0.8; 0.5-0.8 decided by a 2nd focused Claude pass.
No human review; logs everything to speaker_fixes.json and J["speaker_fixes"]. usage: stage1b_speakers.py JOBDIR"""
import json,os,re,sys,time,urllib.request
from pathlib import Path
MODEL=os.getenv("CLAUDE_MODEL","claude-sonnet-5-5");KEY=os.getenv("ZHDUB_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
CH,OV,THR,MID=120,20,0.8,0.5;USAGE={"input_tokens":0,"output_tokens":0,"calls":0}
def call(p):
    b={"model":MODEL,"max_tokens":8000,"messages":[{"role":"user","content":p}]}
    for a in range(4):
        try:
            j=json.load(urllib.request.urlopen(urllib.request.Request("https://api.anthropic.com/v1/messages",json.dumps(b).encode(),
              {"x-api-key":KEY,"anthropic-version":"2023-06-01","content-type":"application/json"}),timeout=600))
            USAGE["calls"]+=1;[USAGE.__setitem__(k,USAGE[k]+j.get("usage",{}).get(k,0)) for k in("input_tokens","output_tokens")]
            return "".join(c.get("text","") for c in j["content"])
        except Exception:
            if a==3:raise
            time.sleep(5*(a+1))
for f in sorted(Path(sys.argv[1]).glob("*/segments.json")):
    J=json.loads(f.read_text());S=J["segments"];spks=sorted({s["spk"] for s in S});props={}
    for c in range(0,len(S),CH-OV):
        ids=range(c,min(c+CH,len(S)))
        tx="\n".join(f"{i}|{S[i]['start']:.1f}-{S[i]['end']:.1f}|{S[i]['spk']}| {S[i]['en']}" for i in ids)
        p=("Below is an automatically diarized podcast/interview transcript (format: id|start-end seconds|speaker|text). "
           f"Speakers: {', '.join(spks)}. The diarizer sometimes assigns a segment to the wrong speaker. Using dialogue context "
           "(question/answer turn-taking, who is asked vs. who answers, self-references and names, interjections like 'yeah'/'right' "
           "from the listener, continuity of an argument), list ONLY segments that are likely mis-attributed. Do not invent new speakers. "
           "Return only JSON: a list of objects {\"seg_id\":int,\"old_spk\":str,\"new_spk\":str,\"confidence\":0-1,\"reason\":str}. "
           "Return [] if everything looks right.\n\n"+tx)
        t=call(p);m=re.search(r"\[.*\]",t,re.S)
        try:L=json.loads(m.group(0)) if m else []
        except Exception:L=[]
        for x in L:
            try:i=int(x["seg_id"])
            except Exception:continue
            if i in ids and (i not in props or x.get("confidence",0)>props[i].get("confidence",0)):props[i]=x
    def second(i,x):  # medium confidence -> focused 2nd Claude pass decides
        tx="\n".join(f"{j}|{S[j]['spk']}| {S[j]['en']}" for j in range(max(0,i-8),min(len(S),i+9)))
        t=call(f"Interview transcript excerpt (id|speaker|text). Speakers: {', '.join(spks)}. Question: is segment {i} "
               f"(currently {S[i]['spk']}) actually spoken by {x['new_spk']}? Reason from turn-taking and content. "
               'Answer only JSON {"answer":"yes"|"no","confidence":0-1,"reason":str}.\n\n'+tx)
        m=re.search(r"\{.*\}",t,re.S)
        try:r=json.loads(m.group(0))
        except Exception:r={"answer":"no","reason":"unparseable"}
        x["second_pass"]=r;return r.get("answer")=="yes" and r.get("confidence",0)>=0.7
    applied=[]
    for i,x in sorted(props.items()):
        valid=x.get("new_spk") in spks and x.get("old_spk")==S[i]["spk"] and x["new_spk"]!=S[i]["spk"]
        c=x.get("confidence",0);ok=valid and (c>=THR or (c>=MID and second(i,x)))
        x.update(applied=bool(ok),en=S[i]["en"],start=S[i]["start"])
        if ok:S[i]["spk_diar"]=S[i]["spk"];S[i]["spk"]=x["new_spk"];applied.append(i)
        elif valid:S[i]["spk_uncertain"]=True   # kept label, but excluded from voice-reference extraction
    J["speaker_fixes"]={"proposed":len(props),"applied":len(applied),"threshold":THR,"items":list(props.values()),"usage":dict(USAGE)}
    (f.parent/"speaker_fixes.json").write_text(json.dumps(J["speaker_fixes"],ensure_ascii=False,indent=1))
    f.write_text(json.dumps(J,ensure_ascii=False,indent=1))
    print(f"stage1b {f.parent.name}: proposed {len(props)}, applied {len(applied)}, usage {USAGE}",flush=True)
