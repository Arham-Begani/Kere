"""Build the Kere '46 test set: map tiles + answer keys for the Opus 5 vs Opus 5.5 map-reading test.

Inputs (all public):
  data/raw/nd-44-13b_plan_25k.jpg   US Army Map Service, sheet ND 44-13 verso, "Bangalore and Vicinity" 1:25,000
  data/raw/nd-44-13a_front_250k.jpg US Army Map Service, sheet ND 44-13 front, 1:250,000 (compiled 1954 from Survey of India 1945-46)
  data/mod/lakes_existing.geojson, data/mod/lakes_lost.geojson  MOD Foundation layers via github.com/soniadas123/bengaluru-water-map

Outputs:
  testset/tiles/*.png, testset/keys/*.json, testset/manifest.json, testset/overview_*.jpg
  data/plan_tanks.geojson (the 18 tanks traced on the plan, georeferenced, with MOD matches)

Every tank outline is traced from the scan's own pixels inside a hand-set box (TANKS), then checked by eye.
Run: python scripts/build_testset.py
"""
import json, os, sys, unicodedata, re
import numpy as np, cv2
from PIL import Image, ImageOps, ImageDraw
from shapely.geometry import shape, Polygon, Point, box, mapping
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(__file__))
from georef import fit_affine, apply_affine, front_lonlat_to_px

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
os.makedirs(P('testset', 'tiles'), exist_ok=True)
os.makedirs(P('testset', 'keys'), exist_ok=True)

# ---------------------------------------------------------------- plan (1:25,000)
# id: bbox (x0,y0,x1,y1) in full-plan px, dark threshold, hatch threshold, drawing style,
#     printed label text (None if unlabeled) and label bbox (where the words sit on the sheet)
TANKS = {
 1: dict(bbox=(1918, 712, 2098, 908), dt=70, ht=40, style='mixed', printed=None),
 2: dict(bbox=(1438, 1162, 1552, 1243), dt=70, ht=40, style='mixed', printed=None),
 3: dict(bbox=(1868, 1405, 1918, 1565), dt=60, ht=40, style='hatched', printed=None),
 4: dict(bbox=(1982, 968, 2010, 1007), dt=75, ht=99, style='solid', printed=None),
 5: dict(bbox=(1882, 1672, 1988, 1833), dt=60, ht=40, style='hatched', printed='Dharmāmbudhi Tank', label=(1872, 1638, 1992, 1686)),
 6: dict(bbox=(3118, 1468, 3310, 1767), dt=45, ht=40, style='solid', printed='Halsūr Tank', label=(3140, 1478, 3232, 1497)),
 7: dict(bbox=(3610, 1443, 3746, 1587), dt=60, ht=40, style='hatched', printed=None),
 8: dict(bbox=(2570, 1378, 2660, 1452), dt=72, ht=40, style='mixed', printed=None),
 9: dict(bbox=(1663, 1963, 1812, 2132), dt=72, ht=40, style='mixed', printed='Agrahār Tank', label=(1570, 2040, 1674, 2059)),
 10: dict(bbox=(1210, 1996, 1289, 2078), dt=80, ht=99, style='solid', printed=None),
 11: dict(bbox=(1546, 2381, 1694, 2584), dt=80, ht=40, style='mixed', printed='Kempāmbudhi Tank', label=(1631, 2393, 1779, 2412)),
 12: dict(bbox=(1283, 2436, 1397, 2519), dt=80, ht=40, style='mixed', printed=None),
 13: dict(bbox=(2963, 1951, 3057, 2044), dt=60, ht=40, style='hatched', printed='Shūle Tank', label=(2975, 1938, 3060, 1957)),
 14: dict(bbox=(2653, 2158, 2722, 2227), dt=60, ht=40, style='hatched', printed='Mud Tank', label=(2715, 2158, 2794, 2177)),
 15: dict(bbox=(3086, 2288, 3184, 2371), dt=60, ht=40, style='hatched', printed=None),
 17: dict(bbox=(2946, 2436, 3224, 2674), dt=85, ht=40, style='solid', printed=None),
 18: dict(bbox=(3846, 2021, 3992, 2124), dt=85, ht=40, style='mixed', printed=None),
 19: dict(bbox=(3863, 2296, 4080, 2634), dt=85, ht=40, style='mixed', printed=None),
}
# features that are water-related but not tanks: no credit, no penalty
AMBIGUOUS_PLAN = [
 dict(kind='service reservoir (labelled "Reservoir")', center=(2406, 1491), r=22),
 dict(kind='service reservoir (labelled "Reservoir")', center=(2279, 1590), r=22),
]
# ground control points: tanks that are unambiguous on the plan and in MOD's layer (existing lakes + labelled lost tanks)
GCP_PAIRS = {6: 'Ulsoor Kere', 11: 'Kempambudhi Kere', 1: 'Sankey Kere', 13: 'Shoolay Tank', 5: 'Dharmambudh Tank', 9: 'Agrahar Hosa Kere'}
PLAN_MAP_AREA = (915, 213, 4105, 3390)  # inside the neatline
TILE = 1000


def load_mod():
    feats = []
    for layer in ['lakes_existing', 'lakes_lost']:
        for f in json.load(open(P('data', 'mod', f'{layer}.geojson')))['features']:
            g = shape(f['geometry']).buffer(0)
            if g.is_empty:
                continue  # a few records have zero area
            feats.append(dict(layer=layer.replace('lakes_', ''), props=f['properties'], geom=g))
    return feats


def trace(gray, spec):
    x0, y0, x1, y1 = spec['bbox']
    g = gray[y0:y1, x0:x1]
    mean = cv2.blur(g, (9, 9)); sq = cv2.blur(g * g, (9, 9)); std = np.sqrt(np.maximum(sq - mean * mean, 0))
    m = ((mean < spec['dt']) | (std > spec['ht'])).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 1:
        m = (lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 1.5, True)[:, 0, :] + np.array([x0, y0])
    return Polygon(c).buffer(0)


def norm_name(s):
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    return re.sub(r'[^a-z]', '', ''.join(ch for ch in s if not unicodedata.combining(ch)).lower())


def build_plan(mod):
    raw = Image.open(P('data', 'raw', 'nd-44-13b_plan_25k.jpg')).convert('L')
    ac = ImageOps.autocontrast(raw, cutoff=1)
    ac.save(P('data', 'raw', 'plan_25k_autocontrast.png'))
    gray = np.array(ac).astype(np.float32)
    polys = {i: trace(gray, s) for i, s in TANKS.items()}
    # georeference from GCPs (tank centroid on plan <-> MOD polygon centroid)
    byname = {f['props']['name']: f for f in mod}
    px = [list(polys[i].centroid.coords[0]) for i in GCP_PAIRS]
    ll = [list(byname[n]['geom'].centroid.coords[0]) for n in GCP_PAIRS.values()]
    A, res = fit_affine(px, ll)

    def px_to_ll(x, y):
        # solve A^T [lon lat 1] = [x y]
        M = np.array(A)  # 3x2
        lhs = M[:2].T; rhs = np.array([x, y]) - M[2]
        return np.linalg.solve(lhs, rhs)

    # project MOD polygons into plan px and match
    tanks_out = []
    for i, poly in polys.items():
        best = None
        for f in mod:
            g = f['geom']
            if g.distance(Point(*px_to_ll(*poly.centroid.coords[0]))) > 0.01:
                continue
            gg = [g] if g.geom_type == 'Polygon' else list(g.geoms)
            pp = unary_union([Polygon(apply_affine(A, *np.array(q.exterior.coords)[:, :2].T)) for q in gg]).buffer(0)
            inter = pp.intersection(poly).area
            if inter > 0:
                score = inter / min(pp.area, poly.area)
                if not best or score > best[0]:
                    best = (score, f)
        s = TANKS[i]
        ll_c = px_to_ll(*poly.centroid.coords[0])
        ring_ll = [list(map(float, px_to_ll(x, y))) for x, y in np.array(poly.exterior.coords)]
        rec = dict(id=f'P{i:02d}', sheet='plan_25k', printed_name=s['printed'], style=s['style'],
                   polygon_px=[[round(x, 1), round(y, 1)] for x, y in poly.exterior.coords],
                   centroid_px=[round(v, 1) for v in poly.centroid.coords[0]], area_px=round(poly.area),
                   area_m2_approx=round(poly.area * 16), centroid_lonlat=[round(float(v), 6) for v in ll_c],
                   label_bbox_px=s.get('label'), polygon_lonlat=ring_ll)
        if best and best[0] >= 0.2:
            p = best[1]['props']
            rec['mod_match'] = dict(name=p['name'], layer=best[1]['layer'], overlap=round(best[0], 2),
                                    last_mapped=p.get('year'), current_use=p.get('current_use'), status=p.get('status'))
        else:
            rec['mod_match'] = None
        tanks_out.append(rec)
    georef = dict(method='affine, least squares', gcps={f'P{i:02d}': n for i, n in GCP_PAIRS.items()},
                  A=np.array(A).tolist(), residual_px=[round(float(r), 1) for r in res],
                  rms_px=round(float(np.sqrt((res ** 2).mean())), 1), metres_per_px=4.0,
                  rms_m=round(float(np.sqrt((res ** 2).mean())) * 4.0))
    json.dump(georef, open(P('data', 'plan_georef.json'), 'w'), indent=1)
    fc = dict(type='FeatureCollection', features=[dict(type='Feature', geometry=dict(type='Polygon', coordinates=[t['polygon_lonlat']]),
               properties={k: v for k, v in t.items() if k not in ('polygon_px', 'polygon_lonlat')}) for t in tanks_out])
    json.dump(fc, open(P('data', 'plan_tanks.geojson'), 'w'), indent=1)
    return ac, tanks_out, georef


def cut_plan_tiles(ac, tanks):
    x0, y0, x1, y1 = PLAN_MAP_AREA
    xs = np.linspace(x0, x1 - TILE, 4).round().astype(int)
    ys = np.linspace(y0, y1 - TILE, 4).round().astype(int)
    out = []
    for r, ty in enumerate(ys):
        for c, tx in enumerate(xs):
            tx, ty = int(tx), int(ty)
            tid = f'plan_r{r}c{c}'
            ac.crop((tx, ty, tx + TILE, ty + TILE)).save(P('testset', 'tiles', f'{tid}.png'))
            tb = box(tx, ty, tx + TILE, ty + TILE)
            items = []
            for t in tanks:
                poly = Polygon(t['polygon_px'])
                frac = poly.intersection(tb).area / poly.area
                if frac < 0.15:
                    continue
                clip = poly.intersection(tb)
                clip = max(clip.geoms, key=lambda g: g.area) if clip.geom_type != 'Polygon' else clip
                lb = t['label_bbox_px']
                label_in = bool(lb) and tb.contains(Point((lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2))
                items.append(dict(id=t['id'], status='full' if frac >= 0.6 else 'partial', fraction_in_tile=round(frac, 2),
                                  polygon=[[round(x - tx, 1), round(y - ty, 1)] for x, y in clip.exterior.coords],
                                  centroid=[round(v, 1) for v in (np.array(clip.centroid.coords[0]) - [tx, ty])],
                                  inside_point=[round(v, 1) for v in (np.array(clip.representative_point().coords[0]) - [tx, ty])],
                                  expected_name=t['printed_name'] if label_in else None,
                                  printed_name_on_sheet=t['printed_name'], style=t['style'],
                                  mod_match=t['mod_match']))
            amb = [dict(kind=a['kind'], center=[a['center'][0] - tx, a['center'][1] - ty], r=a['r'])
                   for a in AMBIGUOUS_PLAN if tb.contains(Point(*a['center']))]
            key = dict(tile=tid, image=f'tiles/{tid}.png', sheet='plan_25k', width=TILE, height=TILE,
                       origin_in_sheet_px=[int(tx), int(ty)], scale_in_sheet=1.0, metres_per_px=4.0,
                       tanks=items, ambiguous=amb, match_buffer_px=15)
            json.dump(key, open(P('testset', 'keys', f'{tid}.json'), 'w'), indent=1)
            out.append(key)
    return out


# ---------------------------------------------------------------- front (1:250,000)
FRONT_WIN = (739, 275, 1234, 613)  # 77.60-77.78 E, 12.88-13.00 N
FRONT_UPSCALE = 2
FRONT_MIN_BLUE = 0.18   # share of blue-ink pixels inside a MOD outline for the tank to count as drawn
FRONT_EXTRA_VERIFIED = ['Ulsoor Kere']  # drawn in blue inside the yellow built-up fill; checked by eye
# MOD records whose outline lands on blue ink that is NOT a tank (grid line, grid number "1", a text label),
# found by eye on 2026-09-25; listed by their projected centroid in sheet px
FRONT_REJECT_NEAR = [(960.0, 552.0, 'grid number "1"'), (846.8, 550.3, 'blue grid line'),
                     (1073.3, 502.7, 'grid line crossing'), (898.1, 393.6, 'text label "Agrahara"')]


def blue_ink(img_bgr):
    b, g, r = [img_bgr[..., k].astype(np.int32) for k in range(3)]
    return ((b - (r + g) / 2) > 14).astype(np.uint8)


def build_front(mod):
    im = cv2.imread(P('data', 'raw', 'nd-44-13a_front_250k.jpg'))
    ink = blue_ink(im)
    X0, Y0, X1, Y1 = FRONT_WIN
    k = FRONT_UPSCALE
    tile = cv2.resize(im[Y0:Y1, X0:X1], None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(P('testset', 'tiles', 'front_se.png'), tile)
    ink_tile = cv2.resize(ink[Y0:Y1, X0:X1] * 255, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(P('testset', 'keys', 'front_se_ink.png'), ink_tile)
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    items, seen = [], set()
    for f in mod:
        g = f['geom']; c = g.centroid
        cx, cy = front_lonlat_to_px(c.x, c.y)
        if not (X0 + 5 < cx < X1 - 5 and Y0 + 5 < cy < Y1 - 5):
            continue
        if any(abs(cx - rx) < 8 and abs(cy - ry) < 8 for rx, ry, _ in FRONT_REJECT_NEAR):
            continue
        gg = [g] if g.geom_type == 'Polygon' else list(g.geoms)
        m = np.zeros(ink.shape, np.uint8)
        for q in gg:
            cv2.fillPoly(m, [np.round(front_lonlat_to_px(*np.array(q.exterior.coords)[:, :2].T)).astype(np.int32)], 1)
        m = cv2.dilate(m, np.ones((7, 7), np.uint8))
        frac = float(ink[m > 0].mean())
        name = f['props']['name']
        if frac < FRONT_MIN_BLUE and name not in FRONT_EXTRA_VERIFIED:
            continue
        blob = (closed & m).astype(np.uint8)
        if blob.sum() < 8:
            blob = m
        cs, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = cv2.convexHull(np.vstack(cs))[:, 0, :]
        poly = Polygon(hull).buffer(0)
        key_c = tuple(np.round(poly.centroid.coords[0]))
        if any(abs(key_c[0] - s[0]) < 4 and abs(key_c[1] - s[1]) < 4 for s in seen):
            continue  # same drawn tank already listed (two MOD records on one blob)
        seen.add(key_c)
        items.append(dict(id=f"F{len(items)+1:02d}", status='full', style='hatched', mod_match=dict(name=name, layer=f['layer'],
                          last_mapped=f['props'].get('year'), current_use=f['props'].get('current_use')),
                          blue_ink_share=round(frac, 2),
                          polygon=[[round((x - X0) * k, 1), round((y - Y0) * k, 1)] for x, y in poly.exterior.coords],
                          centroid=[round((poly.centroid.x - X0) * k, 1), round((poly.centroid.y - Y0) * k, 1)],
                          inside_point=[round((poly.representative_point().x - X0) * k, 1), round((poly.representative_point().y - Y0) * k, 1)],
                          expected_name=None))
    key = dict(tile='front_se', image='tiles/front_se.png', sheet='front_250k', width=int(tile.shape[1]), height=int(tile.shape[0]),
               origin_in_sheet_px=[X0, Y0], scale_in_sheet=k, metres_per_px=round(37.7 / k, 1),
               bounds_lonlat=[77.60, 12.88, 77.78, 13.00], tanks=items, ambiguous=[],
               verified_subset_only=True, ink_mask='keys/front_se_ink.png', ink_radius_px=12, ink_min_share=0.06,
               match_buffer_px=14,
               note='Only tanks matched to MOD records and visibly drawn are in the key. Unlisted detections are judged by the '
                    'blue-ink test: a detection with no blue ink within ink_radius_px counts as invented; one on blue ink is '
                    'counted as "unverified", not wrong.')
    json.dump(key, open(P('testset', 'keys', 'front_se.json'), 'w'), indent=1)
    return key


def overview(keys):
    for key in keys:
        im = Image.open(P('testset', key['image'])).convert('RGB'); d = ImageDraw.Draw(im)
        for t in key['tanks']:
            col = (0, 170, 0) if t['status'] == 'full' else (255, 150, 0)
            d.line([tuple(p) for p in t['polygon']], fill=col, width=3)
            lab = t['id'] + (f" \"{t['expected_name']}\"" if t.get('expected_name') else '')
            if t.get('mod_match'):
                lab += f" = {t['mod_match']['name']}"
            d.text((t['centroid'][0] + 6, t['centroid'][1]), lab, fill=(200, 0, 0))
        for a in key['ambiguous']:
            x, y = a['center']; d.ellipse([x - a['r'], y - a['r'], x + a['r'], y + a['r']], outline=(160, 0, 200), width=3)
        im.save(P('testset', 'answer_overlays', f"{key['tile']}.jpg"), quality=85)


if __name__ == '__main__':
    os.makedirs(P('testset', 'answer_overlays'), exist_ok=True)
    mod = load_mod()
    ac, tanks, georef = build_plan(mod)
    keys = cut_plan_tiles(ac, tanks)
    keys.append(build_front(mod))
    overview(keys)
    manifest = dict(
        created='2026-09-25', tiles=[dict(tile=k['tile'], image=k['image'], key=f"keys/{k['tile']}.json", sheet=k['sheet'],
                                           tanks_full=sum(t['status'] == 'full' for t in k['tanks']),
                                           tanks_partial=sum(t['status'] == 'partial' for t in k['tanks']),
                                           printed_names_expected=sum(bool(t.get('expected_name')) for t in k['tanks']))
                                      for k in keys],
        plan_georef=georef)
    json.dump(manifest, open(P('testset', 'manifest.json'), 'w'), indent=1)
    print(json.dumps(manifest['tiles'], indent=0)[:3000])
    print('plan georef RMS', georef['rms_px'], 'px =', georef['rms_m'], 'm')
    print('plan tanks with MOD match:', sum(1 for t in tanks if t['mod_match']), '/', len(tanks))
