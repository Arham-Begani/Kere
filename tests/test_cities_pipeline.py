"""pipeline/cities.py: consensus clustering on a fake result (no network/API needed), plus
structural checks on the real exported app/data/cities/<city>/ files (skipped if not built yet).
Run: pytest -q
"""
import json, os, sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from cities import _cluster, _tile_to_sheet_detections, load_cities  # noqa: E402

APP_CITIES = os.path.join(ROOT, "app", "data", "cities")


def _fake_key(tile="c_t0", origin=(1000.0, 500.0), scale=2.0, w=800, h=800):
    return dict(tile=tile, city="fakecity", image=f"tiles/{tile}.png", sheet="city_front_250k",
                width=w, height=h, origin_in_sheet_px=list(origin), scale_in_sheet=scale)


def _fake_record(tile, run, tanks):
    return dict(model="claude-opus-5-5", city="fakecity", tile=tile, run=run,
                answer=dict(image_width=800, image_height=800, tanks=tanks))


def test_consensus_requires_two_of_three_runs():
    key = _fake_key()
    keys = {key["tile"]: key}
    # a tank seen in 2 of 3 runs at the same tile point should cluster and survive consensus;
    # a tank seen in only 1 run should not.
    records = [
        _fake_record(key["tile"], 1, [dict(x=100, y=100, bbox=[80, 80, 120, 120], name_as_printed=None,
                                            nearest_place_as_printed=None, style="solid", partial=False)]),
        _fake_record(key["tile"], 2, [dict(x=102, y=98, bbox=[82, 78, 122, 118], name_as_printed="Ende Kere",
                                            nearest_place_as_printed="Endapalli", style="solid", partial=False)]),
        _fake_record(key["tile"], 3, [dict(x=500, y=500, bbox=[480, 480, 520, 520], name_as_printed=None,
                                            nearest_place_as_printed=None, style="hatched", partial=False)]),
    ]
    dets = _tile_to_sheet_detections(records, keys)
    assert len(dets) == 3
    # sheet px = origin + tile_px/scale: (100,100)->(1050,550) etc, well within a 30px cluster radius
    clusters = _cluster(dets, 30.0)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 2], f"expected one 1-run cluster and one 2-run cluster, got sizes {sizes}"
    consensus = [c for c in clusters if len(set(d["run"] for d in c)) >= 2]
    assert len(consensus) == 1
    names = [d["name"] for d in consensus[0] if d["name"]]
    assert names == ["Ende Kere"]


def test_tile_to_sheet_px_conversion():
    key = _fake_key(origin=(1000.0, 500.0), scale=2.0)
    keys = {key["tile"]: key}
    records = [_fake_record(key["tile"], 1, [dict(x=100, y=100, bbox=[80, 80, 120, 120],
                                                    name_as_printed=None, nearest_place_as_printed=None,
                                                    style="solid", partial=False)])]
    dets = _tile_to_sheet_detections(records, keys)
    assert dets[0]["x"] == pytest.approx(1000 + 100 / 2.0)
    assert dets[0]["y"] == pytest.approx(500 + 100 / 2.0)
    assert dets[0]["bbox"] == pytest.approx([1000 + 80 / 2.0, 500 + 80 / 2.0, 1000 + 120 / 2.0, 500 + 120 / 2.0])


def test_cities_config_has_required_fields():
    for city in load_cities():
        if city.get("hand_traced"):
            continue
        for field in ("key", "sheet", "file", "url", "bounds_lonlat", "compiled_note", "city_center_lonlat"):
            assert field in city, f"{city.get('key')} missing '{field}'"
        b = city["bounds_lonlat"]
        assert (b["lon_e"] - b["lon_w"]) == pytest.approx(1.5, abs=0.01)
        assert (b["lat_n"] - b["lat_s"]) == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize("city_key", [c["key"] for c in load_cities() if not c.get("hand_traced")])
def test_exported_city_files_are_well_formed(city_key):
    d = os.path.join(APP_CITIES, city_key)
    if not os.path.isdir(d):
        pytest.skip(f"{city_key} not exported (dropped by QA, or pipeline/cities.py --step export not run)")
    for fn in ("sheet.jpg", "corners.json", "tanks.geojson", "refused.json", "qa.json", "meta.json"):
        assert os.path.exists(os.path.join(d, fn)), f"{city_key}: missing {fn}"
    corners = json.load(open(os.path.join(d, "corners.json")))
    assert corners["corner_order"] == "TL,TR,BR,BL"
    tl, tr, br, bl = corners["corners"]
    assert tl[0] < tr[0] and bl[0] < br[0], f"{city_key}: TL/BL should be west of TR/BR"
    assert tl[1] > bl[1] and tr[1] > br[1], f"{city_key}: TL/TR should be north of BL/BR"

    fc = json.load(open(os.path.join(d, "tanks.geojson")))
    assert fc["type"] == "FeatureCollection"
    for f in fc["features"]:
        p = f["properties"]
        for key in ("id", "display_name", "status", "runs_found", "crop", "area_m2"):
            assert key in p, f"{city_key}: tank missing '{key}'"
        assert p["status"] in ("lost", "surviving")
        # CLAUDE.md/build-2 naming rule: a name only if printed on the sheet or from a
        # labelled source; the fallback must say "Unnamed"
        if not p["name_as_printed"]:
            assert "Unnamed" in p["display_name"]
        if p["now_osm"]:
            assert p["now_osm"]["source"] == "OpenStreetMap"

    qa = json.load(open(os.path.join(d, "qa.json")))
    assert qa["passed"] is True, f"{city_key}: exported despite failing QA ({qa.get('reason')})"
    assert qa["median_offset_m"] is not None and qa["median_offset_m"] < 400

    meta = json.load(open(os.path.join(d, "meta.json")))
    for key in ("city", "sheet", "source_url", "compiled_note", "counts", "model", "prompt_version"):
        assert key in meta, f"{city_key}: meta.json missing '{key}'"
    assert meta["prompt_version"] == "kere-city-v1"
    assert len(os.listdir(os.path.join(d, "crops"))) > 0, f"{city_key}: no crops exported"


def test_dropped_cities_are_documented_not_shipped():
    """A city whose data/cities/<key>/qa.json says failed must not appear under app/data/cities/."""
    data_cities = os.path.join(ROOT, "data", "cities")
    if not os.path.isdir(data_cities):
        pytest.skip("no data/cities/ QA runs yet")
    for city_key in os.listdir(data_cities):
        qa_path = os.path.join(data_cities, city_key, "qa.json")
        if not os.path.exists(qa_path):
            continue
        qa = json.load(open(qa_path))
        if not qa["passed"]:
            assert not os.path.isdir(os.path.join(APP_CITIES, city_key)), (
                f"{city_key} failed QA ({qa['reason']}) but is exported under app/data/cities/")
