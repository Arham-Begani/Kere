"""P2 (optional): where water would pool on today's terrain -- NEVER a flood prediction.

Fetches a DEM mosaic for a study box around the demo's camera presets from the same AWS
Terrarium tiles the app uses for 3D terrain, runs priority-flood depression filling (the
standard algorithm: every border cell drains by definition; an interior cell's "filled"
elevation is the lowest continuous path to the border), and saves depth = filled - original
as a greyscale PNG. Depth is exactly zero everywhere water already drains off the study box;
positive only where the terrain traps it -- an internally-drained depression on TODAY'S DEM,
nothing to do with 1954, MOD's lakes, or the flood-point lists.

  python pipeline/rain.py

Writes app/data/rain_depth.png (8-bit greyscale, depth normalised to its own max) and
app/data/rain.json (corners in the same TL,TR,BR,BL convention as sheets.json, max_depth_m,
downsample factor, and the exact disclaimer text the app must show).
"""
import io, json, math, os, urllib.request
from heapq import heappush, heappop

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
OUT = P("app", "data")

ZOOM = 14
TERRARIUM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
# covers the Stadium/City/HSR presets and all 18 plan tanks with margin (see app/main.js PRESETS
# and data/plan_tanks.geojson, whose combined bounds are lon 77.546-77.651, lat 12.944-13.015)
STUDY_BOX = dict(west=77.53, south=12.88, east=77.70, north=13.04)
DOWNSAMPLE = 2
SMOOTH_SIGMA_PX = 5.0  # priority-flood on a raw DEM turns every vertical-quantization step
                        # into a spurious micro-pit; a Gaussian pre-smooth (standard
                        # hydrological "pit removal" preprocessing) lets real basins show
                        # through instead of pixel-scale sensor noise
MIN_COMPONENT_PX = 25   # drop connected depressions smaller than this many cells (~3.6 ha at
                        # this resolution) after filling: isolated single/few-cell "pools" left
                        # over after smoothing are still DEM noise, not a real low-lying area
DISCLAIMER = "Where water would pool on today's terrain, from a same-day terrain model — not a flood prediction."


def deg2num(lat_deg, lon_deg, zoom):
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    x = int((lon_deg + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def num2deg(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    return math.degrees(lat_rad), lon_deg  # lat, lon


TILE_CACHE = os.environ.get("KERE_DEM_CACHE")  # set to a local dir to avoid re-downloading while tuning


def fetch_tile(z, x, y):
    if TILE_CACHE:
        cached = os.path.join(TILE_CACHE, f"{z}_{x}_{y}.png")
        if os.path.exists(cached):
            return np.array(Image.open(cached).convert("RGB"), dtype=np.float64)
    url = TERRARIUM.format(z=z, x=x, y=y)
    with urllib.request.urlopen(url, timeout=20) as r:
        data = r.read()
    if TILE_CACHE:
        os.makedirs(TILE_CACHE, exist_ok=True)
        open(os.path.join(TILE_CACHE, f"{z}_{x}_{y}.png"), "wb").write(data)
    return np.array(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float64)


def terrarium_to_elevation(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return (r * 256 + g + b / 256) - 32768


def build_mosaic():
    x0, y0 = deg2num(STUDY_BOX["north"], STUDY_BOX["west"], ZOOM)
    x1, y1 = deg2num(STUDY_BOX["south"], STUDY_BOX["east"], ZOOM)
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    nx, ny = x1 - x0 + 1, y1 - y0 + 1
    print(f"fetching {nx}x{ny} = {nx*ny} DEM tiles at z{ZOOM}...")
    mosaic = np.zeros((ny * 256, nx * 256), dtype=np.float64)
    for j in range(ny):
        for i in range(nx):
            rgb = fetch_tile(ZOOM, x0 + i, y0 + j)
            mosaic[j * 256:(j + 1) * 256, i * 256:(i + 1) * 256] = terrarium_to_elevation(rgb)
    north, west = num2deg(x0, y0, ZOOM)
    south, east = num2deg(x1 + 1, y1 + 1, ZOOM)
    return mosaic, dict(west=west, south=south, east=east, north=north)


def downsample(a, k):
    h, w = a.shape
    h, w = h - h % k, w - w % k
    return a[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def priority_flood(dem):
    """Barnes et al. priority-flood: every border cell is a drain by definition; an interior
    cell's filled elevation is max(own elevation, the lowest pass-through elevation on the
    cheapest path already reached). depth = filled - dem is 0 on any cell that already drains
    and positive only inside a true closed depression."""
    H, W = dem.shape
    filled = dem.astype(np.float64).copy()
    visited = np.zeros((H, W), dtype=bool)
    heap = []
    for x in range(W):
        for y in (0, H - 1):
            if not visited[y, x]:
                visited[y, x] = True
                heappush(heap, (dem[y, x], y, x))
    for y in range(H):
        for x in (0, W - 1):
            if not visited[y, x]:
                visited[y, x] = True
                heappush(heap, (dem[y, x], y, x))
    while heap:
        h, y, x = heappop(heap)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W and not visited[ny, nx]:
                visited[ny, nx] = True
                nh = dem[ny, nx] if dem[ny, nx] > h else h
                filled[ny, nx] = nh
                heappush(heap, (nh, ny, nx))
    return filled


def main():
    os.makedirs(OUT, exist_ok=True)
    mosaic, bounds = build_mosaic()
    dem = downsample(mosaic, DOWNSAMPLE)
    dem = cv2.GaussianBlur(dem.astype(np.float32), (0, 0), SMOOTH_SIGMA_PX).astype(np.float64)
    print(f"priority-flood on {dem.shape[1]}x{dem.shape[0]} cells (Gaussian pre-smoothed, sigma={SMOOTH_SIGMA_PX}px)...")
    filled = priority_flood(dem)
    depth = filled - dem
    depth[depth < 0.05] = 0  # numerical noise floor

    n, lab, stats, _ = cv2.connectedComponentsWithStats((depth > 0.05).astype(np.uint8), connectivity=8)
    small = {i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] < MIN_COMPONENT_PX}
    if small:
        depth[np.isin(lab, list(small))] = 0

    max_depth = float(depth.max())
    n_pooling = int((depth > 0.1).sum())
    print(f"max pooling depth {max_depth:.1f} m, {n_pooling} of {depth.size} cells pool at all "
          f"({100*n_pooling/depth.size:.1f}%)")
    scaled = np.clip(depth / max_depth * 255, 0, 255).astype(np.uint8) if max_depth > 0 else depth.astype(np.uint8)
    Image.fromarray(scaled, mode="L").save(os.path.join(OUT, "rain_depth.png"))

    corners = [[bounds["west"], bounds["north"]], [bounds["east"], bounds["north"]],
               [bounds["east"], bounds["south"]], [bounds["west"], bounds["south"]]]
    json.dump(dict(image="rain_depth.png", corners=corners, corner_order="TL,TR,BR,BL",
                    width=int(dem.shape[1]), height=int(dem.shape[0]), zoom=ZOOM,
                    downsample=DOWNSAMPLE, max_depth_m=round(max_depth, 2),
                    pooling_cells=n_pooling, total_cells=int(depth.size),
                    source="AWS Terrain Tiles (Terrarium encoding), priority-flood depression filling",
                    disclaimer=DISCLAIMER),
              open(os.path.join(OUT, "rain.json"), "w"), indent=1)
    print("wrote app/data/rain_depth.png + app/data/rain.json")


if __name__ == "__main__":
    main()
