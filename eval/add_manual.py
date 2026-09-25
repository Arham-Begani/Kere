"""Score answers you got by hand from claude.ai (no API key needed).

1. Upload testset/tiles/<tile>.png to a chat with the model, paste testset/manual/<tile>_prompt.txt.
2. Save the model's reply (the whole message is fine) to a text file.
3. python eval/add_manual.py --model claude-opus-5-5 --tile plan_r2c2 --file reply.txt
4. python eval/score.py
Use a new chat for every tile and every run, and the same settings (extended thinking on/off) for both models.
"""
import argparse, json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ap = argparse.ArgumentParser()
ap.add_argument("--model", required=True, help="claude-opus-5 or claude-opus-5-5")
ap.add_argument("--tile", required=True)
ap.add_argument("--run", type=int, default=1)
ap.add_argument("--file", required=True)
a = ap.parse_args()
text = open(a.file, encoding="utf-8").read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    raise SystemExit("no JSON object found in the reply")
answer = json.loads(m.group(0))
out = os.path.join(ROOT, "results", "raw", a.model, f"{a.tile}__run{a.run}.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(dict(model=a.model, tile=a.tile, run=a.run, prompt_version="kere-tanks-v2-manual",
               request=dict(effort="claude.ai", thinking=None, strict_tool=False, dropped_params=[], max_tokens=None),
               latency_s=0.0, stop_reason=None, usage=dict(input_tokens=0, output_tokens=0), parse="manual",
               answer=answer, content=[dict(type="text", text=text)]), open(out, "w"), indent=1)
print(f"saved {out}: {len(answer.get('tanks', []))} tanks")
