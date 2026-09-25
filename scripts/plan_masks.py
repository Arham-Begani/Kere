"""Build tank masks on the 1:25,000 plan from hand-set bounding boxes.
water = (smoothed grey < dark_t) OR (local std > hatch_t), inside the bbox, closed, largest component."""
import json, numpy as np, cv2
from PIL import Image
g = np.array(Image.open('data/raw/plan_25k_autocontrast.png')).astype(np.float32)
TANKS = {  # id: (x0,y0,x1,y1, dark_t, hatch_t)
 1:(1918,712,2098,908, 70,40), 2:(1438,1162,1552,1243, 70,40), 3:(1868,1405,1918,1565, 60,40),
 4:(1982,968,2010,1007, 75,99), 5:(1882,1672,1988,1833, 60,40), 6:(3118,1468,3310,1767, 45,40),
 7:(3610,1443,3746,1587, 60,40), 8:(2570,1378,2660,1452, 72,40), 9:(1663,1963,1812,2132, 72,40),
 10:(1210,1996,1289,2078, 80,99), 11:(1546,2381,1694,2584, 80,40), 12:(1283,2436,1397,2519, 80,40),
 13:(2963,1951,3057,2044, 60,40), 14:(2653,2158,2722,2227, 60,40), 15:(3086,2288,3184,2371, 60,40),
 17:(2946,2436,3224,2674, 85,40), 18:(3846,2021,3992,2124, 85,40), 19:(3863,2296,4080,2634, 85,40),
}
mean = cv2.blur(g, (9, 9)); sq = cv2.blur(g * g, (9, 9)); std = np.sqrt(np.maximum(sq - mean * mean, 0))
masks = {}
for i, (x0, y0, x1, y1, dt, ht) in TANKS.items():
    m = ((mean[y0:y1, x0:x1] < dt) | (std[y0:y1, x0:x1] > ht)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 1:
        k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])); m = (lab == k).astype(np.uint8)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 1.5, True)[:, 0, :] + np.array([x0, y0])
    M = cv2.moments(m); cx, cy = x0 + M['m10'] / M['m00'], y0 + M['m01'] / M['m00']
    masks[i] = {'polygon_px': c.tolist(), 'centroid_px': [round(cx, 1), round(cy, 1)], 'area_px': int(m.sum()), 'bbox_px': [x0, y0, x1, y1]}
json.dump(masks, open('data/plan_tank_polygons_raw.json', 'w'))
print({i: (v['centroid_px'], v['area_px']) for i, v in masks.items()})
