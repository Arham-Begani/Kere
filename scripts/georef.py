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
    u = (np.asarray(lon) - LON0) / (LON1 - LON0)
    v = (np.asarray(lat) - LAT0) / (LAT1 - LAT0)
    c = {k: np.array(p) for k, p in FRONT_CORNERS.items()}
    top = c["tl"] * (1 - u)[..., None] + c["tr"] * u[..., None] if np.ndim(u) else c["tl"] * (1 - u) + c["tr"] * u
    bot = c["bl"] * (1 - u)[..., None] + c["br"] * u[..., None] if np.ndim(u) else c["bl"] * (1 - u) + c["br"] * u
    return top * (1 - v)[..., None] + bot * v[..., None] if np.ndim(v) else top * (1 - v) + bot * v

def front_px_to_lonlat(x, y, iters=8):
    # invert the bilinear map by Newton iterations (map is near-affine)
    lon, lat = 77.5 + (x - 463.5) / 4132 * 1.5, 13.0 - (y - 275) / 2815.5
    for _ in range(iters):
        px = front_lonlat_to_px(lon, lat)
        e = 1e-5
        dx = (front_lonlat_to_px(lon + e, lat) - px) / e
        dy = (front_lonlat_to_px(lon, lat + e) - px) / e
        J = np.array([[dx[0], dy[0]], [dx[1], dy[1]]])
        d = np.linalg.solve(J, np.array([x, y]) - px)
        lon, lat = lon + d[0], lat + d[1]
    return lon, lat

def fit_affine(px, ll):
    """least-squares affine lon/lat -> pixel; returns (A, residuals_px)"""
    ll = np.asarray(ll, float); px = np.asarray(px, float)
    X = np.c_[ll, np.ones(len(ll))]
    A, *_ = np.linalg.lstsq(X, px, rcond=None)
    res = np.linalg.norm(X @ A - px, axis=1)
    return A, res

def apply_affine(A, lon, lat):
    return np.c_[np.atleast_1d(lon), np.atleast_1d(lat), np.ones(np.size(lon))] @ A
