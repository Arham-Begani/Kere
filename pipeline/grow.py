"""Deterministic outline from a model's point: the model says WHERE, the scan's own pixels say WHAT SHAPE.
grow() returns (polygon, "ok") or (None, reason) when there is no water drawing under the point: that refusal
is the fence, and the app lists every refused point on screen.

Plan sheet (greyscale 1:25,000): water = hatching (diagonal stripes, period ~3.2 px, found with a Gabor
filter bank; built-up shading is a 1.6 px dot screen and scores ~0) OR solid dark fill (15x15 mean < 78).
Front sheet (colour 1:250,000): water = blue ink (B - (R+G)/2 > 14), closed.
"""
import numpy as np, cv2
from shapely.geometry import Polygon

WIN = 240          # half-window (sheet px) around the point
SNAP = 14          # the point may sit this many px off the drawing
MIN_AREA = 150     # px; smaller is text or a speck -> refused
SMALL_AREA = 1000  # px (~1.6 ha on the plan); below this only a solid black fill is trusted
EVID_HATCH, EVID_DARK, EVID_SMALL_DARK = 0.10, 50, 40  # water evidence thresholds (tuned on the answer key, 2026-09-25)
MAX_FILL = 0.6     # a component filling more of the window than this has leaked -> refused
HATCH_T, DARK_T = 5.0, 78


def hatch_energy(gray01):
    E = np.zeros_like(gray01)
    for th in np.deg2rad([30, 40, 50, 60, 120, 130, 140, 150]):
        ke = cv2.getGaborKernel((15, 15), 3.0, th, 3.2, 0.8, psi=0); ke -= ke.mean()
        ko = cv2.getGaborKernel((15, 15), 3.0, th, 3.2, 0.8, psi=np.pi / 2)
        E = np.maximum(E, cv2.filter2D(gray01, -1, ke) ** 2 + cv2.filter2D(gray01, -1, ko) ** 2)
    return cv2.blur(E, (11, 11))


def water_mask_plan(gray):
    g = gray.astype(np.float32)
    return ((hatch_energy(g / 255.0) > HATCH_T) | (cv2.blur(g, (15, 15)) < DARK_T)).astype(np.uint8)


def water_mask_front(bgr):
    b, g, r = [bgr[..., k].astype(np.int32) for k in range(3)]
    return cv2.morphologyEx(((b - (r + g) / 2) > 14).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))


def grow(sheet_img, x, y, kind="plan", bbox=None, pad=0.15):
    """x, y, bbox in sheet px. bbox (the model's claimed extent) limits where the outline may grow:
    pixels decide the shape, but only inside the extent the model claimed (+pad)."""
    H, W = sheet_img.shape[:2]
    x0, y0 = max(0, int(x) - WIN), max(0, int(y) - WIN)
    x1, y1 = min(W, int(x) + WIN), min(H, int(y) + WIN)
    win = sheet_img[y0:y1, x0:x1]
    m = water_mask_plan(win) if kind == "plan" else water_mask_front(win)
    if bbox is not None and len(bbox) == 4:
        bx0, by0, bx1, by1 = min(bbox[0], bbox[2]), min(bbox[1], bbox[3]), max(bbox[0], bbox[2]), max(bbox[1], bbox[3])
        px, py = max(10, pad * (bx1 - bx0)), max(10, pad * (by1 - by0))
        keep = np.zeros_like(m)
        keep[max(0, int(by0 - py - y0)):max(0, int(by1 + py - y0)), max(0, int(bx0 - px - x0)):max(0, int(bx1 + px - x0))] = 1
        m = m & keep
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab = cv2.connectedComponents(m)
    sx, sy = int(x) - x0, int(y) - y0
    oy, ox = max(0, sy - SNAP), max(0, sx - SNAP)
    ys, xs = np.nonzero(lab[oy:sy + SNAP + 1, ox:sx + SNAP + 1])
    if len(xs) == 0:
        return None, f"no water drawing within {SNAP} px of the point"
    d = (xs + ox - sx) ** 2 + (ys + oy - sy) ** 2
    comp = (lab == lab[ys[d.argmin()] + oy, xs[d.argmin()] + ox]).astype(np.uint8)
    area = int(comp.sum())
    if area < MIN_AREA:
        return None, f"drawing under the point is too small ({area} px): text or a speck"
    if area > MAX_FILL * comp.size:
        return None, "region leaks into surrounding shading"
    if kind == "plan":
        g = win.astype(np.float32)
        hatch_share = float((hatch_energy(g / 255.0)[comp > 0] > HATCH_T).mean())
        p20 = float(np.percentile(cv2.blur(g, (15, 15))[comp > 0], 20))
        if area < SMALL_AREA and p20 >= EVID_SMALL_DARK:
            return None, f"small ({area} px) and not a solid fill: could be text or a building"
        if hatch_share < EVID_HATCH and p20 >= EVID_DARK:
            return None, f"no hatching ({hatch_share:.2f}) and not dark enough ({p20:.0f}) for a water fill"
    cs, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 1.5, True)[:, 0, :] + np.array([x0, y0])
    return Polygon(c).buffer(0), "ok"
