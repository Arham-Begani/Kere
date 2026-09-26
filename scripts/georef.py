"""Georeferencing for the two AMS sheets (ND 44-13).
Front sheet (1:250,000): bilinear model from the four neatline corners, which carry
printed coordinates (77°30'-79°00' E, 12°00'-13°00' N). Measured corners in pixels.
City plan (1:25,000, sheet back): affine fit to ground control points (see gcp_plan.json)."""
import json, numpy as np

FRONT_CORNERS = {  # pixel (x, y) of neatline corners, measured on nd-44-13a.jpg (5000x3633)
    "tl": (463.5, 275.0),   # 77.5E, 13.0N
    "tr": (4595.0, 275.0),  # 79.0E, 13.0N
    "bl": (455.5, 3090.5),  # 77.5E, 12.0N
    "br": (4600.0, 3091.0), # 79.0E, 12.0N
}
LON0, LON1, LAT0, LAT1 = 77.5, 79.0, 13.0, 12.0

def front_lonlat_to_px(lon, lat):
    px = bilinear_lonlat_to_px(FRONT_CORNERS, LON0, LON1, LAT0, LAT1, lon, lat)
    return px if np.ndim(lon) else (float(px[0]), float(px[1]))

def front_px_to_lonlat(x, y, iters=8):
    return bilinear_px_to_lonlat(FRONT_CORNERS, LON0, LON1, LAT0, LAT1, x, y, iters)

# ---------------------------------------------------------------- generalized bilinear model
# Same method as front_lonlat_to_px/front_px_to_lonlat above, parameterized by any sheet's four
# neatline corners (px) and printed bounds, so it works for any U502 sheet, not just ND 44-13.
# lon_w/lon_e are the west/east printed longitudes (left/right edges); lat_n/lat_s are the
# north/south printed latitudes (top/bottom edges) -- matches how every AMS margin is labelled.

def bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon, lat):
    lon = np.atleast_1d(np.asarray(lon, dtype=float))
    lat = np.atleast_1d(np.asarray(lat, dtype=float))
    u = (lon - lon_w) / (lon_e - lon_w)
    v = (lat_n - lat) / (lat_n - lat_s)
    c = {k: np.asarray(p, dtype=float) for k, p in corners.items()}
    top = c["tl"] * (1 - u)[:, None] + c["tr"] * u[:, None]
    bot = c["bl"] * (1 - u)[:, None] + c["br"] * u[:, None]
    px = top * (1 - v)[:, None] + bot * v[:, None]
    return px[0] if px.shape[0] == 1 else px


def bilinear_px_to_lonlat(corners, lon_w, lon_e, lat_n, lat_s, x, y, iters=8):
    """Invert the bilinear map by Newton iterations (near-affine, converges in a few steps)."""
    tl = np.asarray(corners["tl"], dtype=float)
    tr = np.asarray(corners["tr"], dtype=float)
    bl = np.asarray(corners["bl"], dtype=float)
    w_px = max(np.linalg.norm(tr - tl), 1e-6)
    h_px = max(np.linalg.norm(bl - tl), 1e-6)
    lon = lon_w + (x - tl[0]) / w_px * (lon_e - lon_w)
    lat = lat_n - (y - tl[1]) / h_px * (lat_n - lat_s)
    for _ in range(iters):
        px = bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon, lat)
        e = 1e-5
        dx = (bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon + e, lat) - px) / e
        dy = (bilinear_lonlat_to_px(corners, lon_w, lon_e, lat_n, lat_s, lon, lat + e) - px) / e
        J = np.array([[dx[0], dy[0]], [dx[1], dy[1]]])
        d = np.linalg.solve(J, np.array([x, y]) - px)
        lon, lat = lon + float(d[0]), lat + float(d[1])
    return float(lon), float(lat)


def _longest_dark_run(row, dark_thresh):
    best = cur = 0
    for v in row:
        if v < dark_thresh:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def find_neatline_corner(gray, guess_x, guess_y, search=150, dark_thresh=140, min_run_frac=0.5):
    """Thin-line minimum search: refine an approximate neatline corner (guess_x, guess_y) to the
    precise pixel. AMS sheets print an outer decorative border as well as the inner neatline the
    printed coordinates and grid actually reference, so this doesn't just take the longest dark
    run in the window (the outer border, being uninterrupted by map content, usually wins that) --
    it takes the run closest to the a-priori guess among every row/column with a long-enough run."""
    H, W = gray.shape[:2]
    x0, y0 = max(0, int(guess_x - search)), max(0, int(guess_y - search))
    x1, y1 = min(W, int(guess_x + search)), min(H, int(guess_y + search))
    win = gray[y0:y1, x0:x1]
    wh, ww = win.shape
    row_runs = np.array([_longest_dark_run(win[r, :], dark_thresh) for r in range(wh)])
    col_runs = np.array([_longest_dark_run(win[:, c], dark_thresh) for c in range(ww)])
    local_gy, local_gx = guess_y - y0, guess_x - x0
    row_cand = np.where(row_runs >= min_run_frac * ww)[0]
    col_cand = np.where(col_runs >= min_run_frac * wh)[0]
    ry = row_cand[np.argmin(np.abs(row_cand - local_gy))] if len(row_cand) else int(np.argmax(row_runs))
    cx = col_cand[np.argmin(np.abs(col_cand - local_gx))] if len(col_cand) else int(np.argmax(col_runs))
    return x0 + int(cx), y0 + int(ry), int(row_runs[ry]), int(col_runs[cx])


# Fractional neatline margins calibrated once against the Bangalore front sheet (nd-44-13a,
# 5000x3633, neatline (463.5,275.0)-(4600,3091)): the U502 series prints a near-identical page
# template, so these are a good coarse guess to refine locally with find_neatline_corner().
GENERIC_MARGIN_FRAC = dict(left=0.0927, right=0.920, top=0.0757, bottom=0.8508)


def find_sheet_corners(gray, margin_frac=None, search=300):
    """Auto-detect all four neatline corners (px) of a U502 sheet scan."""
    m = margin_frac or GENERIC_MARGIN_FRAC
    H, W = gray.shape[:2]
    guesses = {
        "tl": (W * m["left"], H * m["top"]), "tr": (W * m["right"], H * m["top"]),
        "bl": (W * m["left"], H * m["bottom"]), "br": (W * m["right"], H * m["bottom"]),
    }
    corners, runs = {}, {}
    for k, (gx, gy) in guesses.items():
        x, y, rr, cr = find_neatline_corner(gray, gx, gy, search=search)
        corners[k] = [float(x), float(y)]
        runs[k] = dict(row_run=rr, col_run=cr)
    return corners, runs


def _first_qualifying_line(profile, ascending, min_value):
    """profile: 1D array of a per-index darkness score. Returns the first index (scanning from
    the start if ascending else from the end) whose score clears min_value, else the argmax."""
    idxs = range(len(profile)) if ascending else range(len(profile) - 1, -1, -1)
    for i in idxs:
        if profile[i] >= min_value:
            return i
    return int(np.argmax(profile))


def find_sheet_neatline(gray, top_band=700, bottom_band=1600, side_band=700,
                         x_swath_frac=(0.15, 0.85), y_swath_frac=(0.15, 0.75),
                         dark_thresh=170, min_dark_frac=0.4, edge_skip=20):
    """Find a single sheet's neatline as four independent edge lines (not four independent
    corners): the outermost row/column, scanning inward from each side of the scan, whose share
    of dark pixels within a central swath clears min_dark_frac. A solid neatline stays mostly
    dark across the whole swath even where grid-square tick numbers cross or interrupt it; plain
    margin or scattered text does not, which is why this uses the dark PIXEL FRACTION (robust to
    those small interruptions) rather than the single longest continuous dark run."""
    H, W = gray.shape[:2]
    xs0, xs1 = int(W * x_swath_frac[0]), int(W * x_swath_frac[1])
    ys0, ys1 = int(H * y_swath_frac[0]), int(H * y_swath_frac[1])
    e = edge_skip  # scans are trimmed of the outermost `e` px: physical scan-bed edges are often
    # a solid dark vignette one to a few pixels wide, which would otherwise look like a neatline.

    top_strip = gray[e:top_band, xs0:xs1] < dark_thresh
    top_y = e + _first_qualifying_line(top_strip.mean(axis=1), True, min_dark_frac)

    bot_strip = gray[H - bottom_band:H - e, xs0:xs1] < dark_thresh
    bot_y = (H - bottom_band) + _first_qualifying_line(bot_strip.mean(axis=1), False, min_dark_frac)

    left_strip = gray[ys0:ys1, e:side_band] < dark_thresh
    left_x = e + _first_qualifying_line(left_strip.mean(axis=0), True, min_dark_frac)

    right_strip = gray[ys0:ys1, W - side_band:W - e] < dark_thresh
    right_x = (W - side_band) + _first_qualifying_line(right_strip.mean(axis=0), False, min_dark_frac)

    corners = {
        "tl": [float(left_x), float(top_y)], "tr": [float(right_x), float(top_y)],
        "bl": [float(left_x), float(bot_y)], "br": [float(right_x), float(bot_y)],
    }
    return corners, dict(top_y=top_y, bot_y=bot_y, left_x=left_x, right_x=right_x)


def fit_affine(px, ll):
    """least-squares affine lon/lat -> pixel; returns (A, residuals_px)"""
    ll = np.asarray(ll, float); px = np.asarray(px, float)
    X = np.c_[ll, np.ones(len(ll))]
    A, *_ = np.linalg.lstsq(X, px, rcond=None)
    res = np.linalg.norm(X @ A - px, axis=1)
    return A, res

def apply_affine(A, lon, lat):
    return np.c_[np.atleast_1d(lon), np.atleast_1d(lat), np.ones(np.size(lon))] @ A
