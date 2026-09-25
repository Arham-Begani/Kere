"""Run the Kere map-reading test on Opus 5 and Opus 5.5 with identical inputs.

  export ANTHROPIC_API_KEY=...
  python eval/run_eval.py                      # both models, all 17 tiles, 3 runs each
  python eval/run_eval.py --runs 1 --tiles plan_r1c1 front_se   # quick smoke test (4 calls)
  python eval/score.py                         # then score

Every response is saved raw to results/raw/<model>/<tile>__run<N>.json, so scoring can be re-run
without paying again. Existing result files are skipped (safe to re-run after an interruption).
"""
import argparse, base64, json, os, re, sys, time, random
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

sys.path.insert(0, os.path.dirname(__file__))
from prompt import PROMPT_VERSION, TOOL, build_prompt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.environ.get("ANTHROPIC_API_KEY"):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
TESTSET = os.path.join(ROOT, "testset")
DEFAULT_MODELS = ["claude-opus-5", "claude-opus-5-5"]


def load_keys(which):
    manifest = json.load(open(os.path.join(TESTSET, "manifest.json")))
    keys = {t["tile"]: json.load(open(os.path.join(TESTSET, t["key"]))) for t in manifest["tiles"]}
    if which == ["all"]:
        return keys
    if which == ["plan"]:
        return {k: v for k, v in keys.items() if v["sheet"] == "plan_25k"}
    if which == ["front"]:
        return {k: v for k, v in keys.items() if v["sheet"] == "front_250k"}
    return {k: keys[k] for k in which}


def call(client, model, key, args):
    img = base64.b64encode(open(os.path.join(TESTSET, key["image"]), "rb").read()).decode()
    messages = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
        {"type": "text", "text": build_prompt(key)},
    ]}]
    extra = {}
    if args.effort:
        extra["output_config"] = {"effort": args.effort}
    if args.thinking == "adaptive":
        extra["thinking"] = {"type": "adaptive"}
    tool = dict(TOOL)
    dropped = []
    for attempt in range(6):
        try:
            t0 = time.time()
            resp = client.messages.create(model=model, max_tokens=args.max_tokens, tools=[tool],
                                          tool_choice={"type": "auto"}, messages=messages, extra_body=extra or None)
            return resp, time.time() - t0, extra, tool.get("strict", False), dropped
        except anthropic.BadRequestError as e:
            msg = str(e)
            # parameter not accepted by this model: drop it, note it, retry (recorded in the result file)
            if "strict" in msg and tool.get("strict"):
                tool.pop("strict"); dropped.append("strict"); continue
            if "thinking" in msg and "thinking" in extra:
                extra.pop("thinking"); dropped.append("thinking"); continue
            if "effort" in msg and "output_config" in extra:
                extra.pop("output_config"); dropped.append("effort"); continue
            raise
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            wait = min(60, 2 ** attempt + random.random())
            print(f"  {model} {key['tile']}: {type(e).__name__}, retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529):
                time.sleep(min(60, 2 ** attempt + random.random())); continue
            raise
    raise RuntimeError("too many retries")


def parse(resp):
    for b in resp.content:
        if b.type == "tool_use" and b.name == "report_tanks":
            return b.input, "tool_use"
    text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0)), "text_json"
        except json.JSONDecodeError:
            pass
    return None, "unparsed"


def run_one(client, model, key, run, args):
    out = os.path.join(ROOT, "results", "raw", model, f"{key['tile']}__run{run}.json")
    if os.path.exists(out):
        return out, "skipped"
    resp, secs, extra, strict, dropped = call(client, model, key, args)
    parsed, how = parse(resp)
    rec = dict(model=model, tile=key["tile"], run=run, prompt_version=PROMPT_VERSION,
               request=dict(effort=(extra.get("output_config") or {}).get("effort"), thinking=extra.get("thinking"),
                            strict_tool=strict, dropped_params=dropped, max_tokens=args.max_tokens),
               latency_s=round(secs, 2), stop_reason=resp.stop_reason,
               usage=dict(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens),
               parse=how, answer=parsed,
               content=[b.model_dump() for b in resp.content])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rec, open(out, "w"), indent=1, default=str)
    n = len((parsed or {}).get("tanks", [])) if parsed else "?"
    return out, f"{how}, {n} tanks, {secs:.1f}s, out={resp.usage.output_tokens} tok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tiles", nargs="+", default=["all"], help="all | plan | front | tile ids")
    ap.add_argument("--effort", default="high", help="same effort for both models (Opus 5.5 defaults to medium, Opus 5 to high)")
    ap.add_argument("--thinking", default="adaptive", choices=["adaptive", "default"])
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    keys = load_keys(args.tiles)
    client = anthropic.Anthropic(max_retries=0)
    jobs = [(m, k, r) for m in args.models for k in keys.values() for r in range(1, args.runs + 1)]
    random.shuffle(jobs)  # interleave models so rate limits and time-of-day hit both equally
    print(f"{len(jobs)} calls: {len(args.models)} models x {len(keys)} tiles x {args.runs} runs, effort={args.effort}")
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(run_one, client, m, k, r, args): (m, k["tile"], r) for m, k, r in jobs}
        for f in as_completed(futs):
            m, t, r = futs[f]
            try:
                _, msg = f.result()
                print(f"{m:18s} {t:12s} run{r}: {msg}", flush=True)
            except Exception as e:
                print(f"{m:18s} {t:12s} run{r}: FAILED {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    main()
