import json, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from georef import front_lonlat_to_px, front_px_to_lonlat

def test_front_round_trip_and_corners():
    assert np.allclose(front_lonlat_to_px(77.5, 13.0), (463.5, 275.0))
    assert np.allclose(front_lonlat_to_px(79.0, 12.0), (4600.0, 3091.0))
    for lon, lat in [(77.6, 12.95), (77.7, 12.9), (78.3, 12.4)]:
        x, y = front_lonlat_to_px(lon, lat)
        lo, la = front_px_to_lonlat(x, y)
        assert abs(lo - lon) < 1e-6 and abs(la - lat) < 1e-6

def test_plan_georef_error_is_small():
    g = json.load(open(os.path.join(ROOT, "data", "plan_georef.json")))
    assert g["rms_px"] < 20 and max(g["residual_px"]) < 40  # 4 m/px: RMS about 51 m
