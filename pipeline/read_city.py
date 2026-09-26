"""Read a city's tiles with Opus 5.5 (pipeline/city_prompt.py -- eval/prompt.py stays frozen for
the Bengaluru scoring). Same strict-tool-choice fallback and settings as eval/run_eval.py.

  export ANTHROPIC_API_KEY=...    # or put it in .env (loaded automatically if not already set)
  python pipeline/read_city.py --city chennai                 # 3 runs, effort high, all tiles
  python pipeline/read_city.py --city chennai --runs 1         # smoke test

Every response is saved raw to results/cities/<city>/raw/<tile>__run<N>.json (skips existing
files, so it's safe to resume after an interruption, same as run_eval.py).
"""
import argparse, base64, glob, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if not os.environ.get("ANTHROPIC_API_KEY"):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))

sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from city_prompt import PROMPT_VERSION, TOOL, build_prompt  # noqa: E402
from cities import city_config, RESULTS_DIR  # noqa: E402

MODEL = "claude-opus-5-5"
PRICE_IN, PRICE_OUT = 4.0, 20.0  # $ per million tokens, matching eval/score.py's PRICES table


def load_keys(city_key):
    keys_dir = os.path.join(RESULTS_DIR, city_key, "keys")
    if not os.path.isdir(keys_dir):
        raise SystemExit(f"no tiles for '{city_key}' yet -- run: python pipeline/cities.py --city {city_key} --step tile")
    return {os.path.basename(f)[:-5]: json.load(open(f)) for f in sorted(glob.glob(os.path.join(keys_dir, "*.json")))}


def call(client, city_cfg, key, args):
    tiles_dir = os.path.join(RESULTS_DIR, city_cfg["key"], "tiles")
    img = base64.b64encode(open(os.path.join(tiles_dir, os.path.basename(key["image"])), "rb").read()).decode()
    messages = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}},
        {"type": "text", "text": build_prompt(city_cfg, key)},
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
            resp = client.messages.create(model=MODEL, max_tokens=args.max_tokens, tools=[tool],
                                          tool_choice={"type": "auto"}, messages=messages, extra_body=extra or None)
            return resp, time.time() - t0, extra, tool.get("strict", False), dropped
        except anthropic.BadRequestError as e:
            msg = str(e)
            if "strict" in msg and tool.get("strict"):
                tool.pop("strict"); dropped.append("strict"); continue
            if "thinking" in msg and "thinking" in extra:
                extra.pop("thinking"); dropped.append("thinking"); continue
            if "effort" in msg and "output_config" in extra:
                extra.pop("output_config"); dropped.append("effort"); continue
            raise
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            wait = min(60, 2 ** attempt + random.random())
            print(f"  {key['tile']}: {type(e).__name__}, retrying in {wait:.0f}s", flush=True)
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
    return None, "unparsed"


def run_one(client, city_cfg, key, run, args):
    out_dir = os.path.join(RESULTS_DIR, city_cfg["key"], "raw")
    out = os.path.join(out_dir, f"{key['tile']}__run{run}.json")
    if os.path.exists(out):
        return out, "skipped"
    resp, secs, extra, strict, dropped = call(client, city_cfg, key, args)
    parsed, how = parse(resp)
    cost = resp.usage.input_tokens * PRICE_IN / 1e6 + resp.usage.output_tokens * PRICE_OUT / 1e6
    rec = dict(model=MODEL, city=city_cfg["key"], tile=key["tile"], run=run, prompt_version=PROMPT_VERSION,
               request=dict(effort=(extra.get("output_config") or {}).get("effort"), thinking=extra.get("thinking"),
                            strict_tool=strict, dropped_params=dropped, max_tokens=args.max_tokens),
               latency_s=round(secs, 2), stop_reason=resp.stop_reason,
               usage=dict(input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens),
               cost_usd=round(cost, 4), parse=how, answer=parsed,
               content=[b.model_dump() for b in resp.content])
    os.makedirs(out_dir, exist_ok=True)
    json.dump(rec, open(out, "w"), indent=1, default=str)
    n = len((parsed or {}).get("tanks", [])) if parsed else "?"
    return out, f"{how}, {n} tanks, {secs:.1f}s, out={resp.usage.output_tokens} tok, ${cost:.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--tiles", nargs="+", default=["all"])
    ap.add_argument("--effort", default="high")
    ap.add_argument("--thinking", default="adaptive", choices=["adaptive", "default"])
    ap.add_argument("--max-tokens", type=int, default=16000)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    city_cfg = city_config(args.city)
    keys = load_keys(args.city)
    if args.tiles != ["all"]:
        keys = {k: v for k, v in keys.items() if k in args.tiles}
    client = anthropic.Anthropic(max_retries=0)
    jobs = [(k, r) for k in keys.values() for r in range(1, args.runs + 1)]
    random.shuffle(jobs)
    print(f"{args.city}: {len(jobs)} calls ({len(keys)} tiles x {args.runs} runs), effort={args.effort}")
    total_cost = 0.0
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(run_one, client, city_cfg, k, r, args): (k["tile"], r) for k, r in jobs}
        for f in as_completed(futs):
            t, r = futs[f]
            try:
                _, msg = f.result()
                print(f"{t:24s} run{r}: {msg}", flush=True)
            except Exception as e:
                print(f"{t:24s} run{r}: FAILED {type(e).__name__}: {e}", flush=True)
    raw_dir = os.path.join(RESULTS_DIR, args.city, "raw")
    for f in glob.glob(os.path.join(raw_dir, "*.json")):
        total_cost += json.load(open(f)).get("cost_usd", 0.0)
    print(f"{args.city}: total spend so far in results/cities/{args.city}/raw = ${total_cost:.3f}")


if __name__ == "__main__":
    main()
