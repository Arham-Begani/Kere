"""Stand-in model results, built from the answer keys, used ONLY to build and test the pipeline
before the real eval (eval/run_eval.py) has run. Perfect answers: every tank in every key, at its
inside_point/bbox, with expected_name only when the label is in the tile (never from memory).

Writes results_standin/raw/<model>/<tile>__run{1,2,3}.json -- never results/raw/, so stand-in data
can never be mistaken for a real model result. Any code path that reads results_standin/ must show
the red "DEMO DATA: answer key, not model output" banner.

  python scripts/make_standin_results.py
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "eval"))
from prompt import PROMPT_VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
MODELS = ["claude-opus-5", "claude-opus-5-5"]


def key_to_answer(key):
    tanks = []
    for t in key["tanks"]:
        xs = [p[0] for p in t["polygon"]]
        ys = [p[1] for p in t["polygon"]]
        x, y = t["inside_point"]
        tanks.append(dict(
            x=round(x, 1), y=round(y, 1),
            bbox=[round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)],
            name_as_printed=t.get("expected_name"),
            style=t["style"],
            partial=(t["status"] == "partial"),
        ))
    return dict(image_width=key["width"], image_height=key["height"], tanks=tanks)


def main():
    manifest = json.load(open(P("testset", "manifest.json")))
    n_tiles = 0
    for tinfo in manifest["tiles"]:
        key = json.load(open(P("testset", tinfo["key"])))
        answer = key_to_answer(key)
        n_tiles += 1
        for model in MODELS:
            outdir = P("results_standin", "raw", model)
            os.makedirs(outdir, exist_ok=True)
            for run in (1, 2, 3):
                out = os.path.join(outdir, f"{key['tile']}__run{run}.json")
                rec = dict(
                    model=model, tile=key["tile"], run=run, prompt_version=PROMPT_VERSION,
                    request=dict(effort="high", thinking={"type": "adaptive"}, strict_tool=True,
                                 dropped_params=[], max_tokens=16000),
                    latency_s=1.0, stop_reason="tool_use",
                    usage=dict(input_tokens=1000, output_tokens=200),
                    parse="tool_use", answer=answer,
                    content=[dict(type="text", text="DEMO DATA: answer key, not model output")],
                )
                json.dump(rec, open(out, "w"), indent=1)
    print(f"wrote stand-in results: {len(MODELS)} models x {n_tiles} tiles x 3 runs -> results_standin/raw/")


if __name__ == "__main__":
    main()
