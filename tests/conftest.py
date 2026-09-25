import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the contrast-stretched plan is generated (kept out of the zip to save 7 MB); build it on first run
if not os.path.exists(os.path.join(ROOT, "data", "raw", "plan_25k_autocontrast.png")):
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_testset.py")], check=True, capture_output=True)
