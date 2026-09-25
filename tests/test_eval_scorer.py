import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_scorer_selftest_passes():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "eval", "selftest.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
