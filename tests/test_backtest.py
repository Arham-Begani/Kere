"""Guards the headline finding so a data change can't silently flip it."""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_lost_lakes_attract_flood_points_and_surviving_ones_do_not(tmp_path):
    out = tmp_path / "bt.json"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "backtest.py"), "--area", "plan", "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = {(x["layer"], x["radius_m"]): x for b in ("this_layer", "reference_MOD_hand_traced") for x in json.load(open(out))[b]["rows"]}
    lost = rows[("1954 plan tanks, answer key: lost", 250)]
    kept = rows[("1954 plan tanks, answer key: surviving", 250)]
    assert lost["lift"] > 1.5 and lost["p_one_sided"] < 0.05
    assert kept["lift"] < 1.2
