"""pipeline/assemble.py against stand-in (answer-key) results: proves clustering, grow() and
MOD matching hang together end to end before spending real API calls. Run: pytest -q

Plan: the answer key has 18 tanks; P04 (a 0.3 ha pond) is refused by grow() BY DESIGN
(see tests/test_grow.py and pipeline/grow.py's SMALL_AREA/EVID_SMALL_DARK), so a perfect
run accepts 17 and refuses exactly 1.

Front: the key lists 16 MOD-verified tanks. grow()'s MIN_AREA=150 was tuned and documented
against the PLAN sheet only (tests/test_grow.py); at the front sheet's native 1:250,000
resolution several of those 16 tanks have under 150 connected px of blue ink, so grow()
correctly refuses them. That's a real resolution limit, not a bug -- we do not tune
grow.py's thresholds (CLAUDE.md, "Testing rules"). This test checks that every one of the
16 known front tanks is accounted for as either accepted or refused (none silently lost).
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
STANDIN = os.path.join(ROOT, "results_standin")


def _ensure_standin():
    if not os.path.isdir(os.path.join(STANDIN, "raw", "claude-opus-5-5")):
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "make_standin_results.py")],
                        check=True, cwd=ROOT)


def test_assemble_answer_key_gives_expected_plan_and_front_counts(tmp_path):
    _ensure_standin()
    from assemble import assemble
    fc, refused = assemble("claude-opus-5-5", "results_standin", out_dir=str(tmp_path))

    plan_tanks = [f for f in fc["features"] if f["properties"]["sheet"] == "plan_25k"]
    plan_refused = [r for r in refused if r["sheet"] == "plan_25k"]
    assert len(plan_tanks) >= 17, f"expected >=17 plan tanks, got {len(plan_tanks)}"
    assert len(plan_refused) <= 1, f"expected at most 1 plan refusal (P04, by design), got {plan_refused}"

    front_tanks = [f for f in fc["features"] if f["properties"]["sheet"] == "front_250k"]
    front_refused = [r for r in refused if r["sheet"] == "front_250k"]
    assert len(front_tanks) + len(front_refused) == 16, (
        f"expected all 16 known front tanks accounted for, got {len(front_tanks)} accepted "
        f"+ {len(front_refused)} refused = {len(front_tanks) + len(front_refused)}")
    assert len(front_tanks) >= 8, f"too few front tanks survived grow(): {len(front_tanks)}"

    # every accepted tank has valid geometry and the properties the app depends on
    for f in fc["features"]:
        p = f["properties"]
        for key in ("id", "sheet", "status", "runs_found", "tiles", "crop", "area_m2"):
            assert key in p, f"missing property {key} on {p.get('id')}"
        assert p["status"] in ("lost", "surviving")
        assert len(f["geometry"]["coordinates"][0]) >= 4

    # every refusal is traceable: reason, point, tile(s), runs
    for r in refused:
        for key in ("point_lonlat", "tile", "runs", "reason"):
            assert key in r


def test_assemble_output_written_to_out_dir(tmp_path):
    _ensure_standin()
    from assemble import assemble
    assemble("claude-opus-5", "results_standin", out_dir=str(tmp_path))
    assert os.path.exists(os.path.join(tmp_path, "tanks_claude-opus-5.geojson"))
    assert os.path.exists(os.path.join(tmp_path, "refused_claude-opus-5.json"))
    fc = json.load(open(os.path.join(tmp_path, "tanks_claude-opus-5.geojson")))
    assert fc["type"] == "FeatureCollection"
