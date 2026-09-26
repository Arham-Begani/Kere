/* ==========================================================================
   Kere — app logic
   Static site. No backend, no API key, nothing the judge has to log into.
   Every number rendered below is read at runtime from app/data/*; nothing
   here is a literal statistic. Tank geometry is never drawn — only the
   polygons already computed by pipeline/grow.py and shipped in the geojson.
   ========================================================================== */

'use strict';

const DATA = 'data/';

const PRESETS = {
  stadium: { center: [77.6117, 12.9686], zoom: 16.5, pitch: 60, bearing: -20 },
  city:    { center: [77.60,   12.97],   zoom: 12.3, pitch: 45, bearing: 0 },
  hsr:     { center: [77.6389, 12.9116], zoom: 15,   pitch: 55, bearing: 0 },
};

const FLOOD_SWATCH = {
  'KGIS flood-vulnerable': '#e4572e',
  'flood-prone':           '#f2905f',
  'BBMP low-lying':        '#c1121f',
  'news':                  '#ff5a3c',
};

const state = {
  floodVisible: false,
  rainVisible: false,
  map: null,
  activeDrawer: null,
  cityMode: false,   // true for any city other than bengaluru (no flood/scoreboard/rain data)
  cityKey: 'bengaluru',
  lastSearchPoint: null, // { lon, lat, name } — drives the "lost lakes near you" drawer
};

const CITY_PRESETS = {
  chennai:   { zoom: 12.6, pitch: 45 },
  hyderabad: { zoom: 12.4, pitch: 45 },
  pune:      { zoom: 12.6, pitch: 45 },
  kolkata:   { zoom: 12.4, pitch: 45 },
};

function urlParams() { return new URLSearchParams(window.location.search); }

// Bengaluru's assets live under data/; every other city's under data/cities/<key>/ — this is
// the one place that distinction is resolved, so template code just calls assetBase().
function assetBase() { return state.cityMode ? `${DATA}cities/${state.cityKey}/` : DATA; }

function currentCityKey(citiesIndex) {
  const fromUrl = urlParams().get('city');
  const known = new Set((citiesIndex.cities || []).map((c) => c.key));
  if (fromUrl && known.has(fromUrl)) return fromUrl;
  return 'bengaluru';
}

/* -------------------------------------------------------------------------
   Small utilities
   ------------------------------------------------------------------------- */

async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function toast(msg) {
  const stack = document.getElementById('toast-stack');
  if (!stack) return;
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// Equirectangular approximation — fine at city scale, no turf dependency.
function distanceMeters(lon1, lat1, lon2, lat2) {
  const R = 6371000;
  const rad = Math.PI / 180;
  const x = (lon2 - lon1) * rad * Math.cos(((lat1 + lat2) / 2) * rad);
  const y = (lat2 - lat1) * rad;
  return Math.sqrt(x * x + y * y) * R;
}

// Anchor point for a label / nearest-tank lookup only — never used to draw
// the tank itself. The polygon rendered on the map always comes straight
// from the geojson geometry.
function polygonCentroid(geometry) {
  const ring = geometry.type === 'Polygon' ? geometry.coordinates[0] : geometry.coordinates[0][0];
  let x = 0, y = 0, n = 0;
  ring.forEach((pt) => { x += pt[0]; y += pt[1]; n += 1; });
  return [x / n, y / n];
}

function nearestTank(lon, lat) {
  let best = null, bestDist = Infinity;
  (state.tanksWithCentroid || []).forEach((t) => {
    const d = distanceMeters(lon, lat, t.centroid[0], t.centroid[1]);
    if (d < bestDist) { bestDist = d; best = t; }
  });
  return best ? { props: best.props, distance: bestDist } : null;
}

// "Lost lakes near you" — every lost tank within radiusM, nearest first. Distance-and-record
// only, per CLAUDE.md rule 6 ("never predict flooding for an address").
function nearbyLostTanks(lon, lat, radiusM) {
  return (state.tanksWithCentroid || [])
    .filter((t) => t.props.status === 'lost')
    .map((t) => ({ props: t.props, distance: distanceMeters(lon, lat, t.centroid[0], t.centroid[1]) }))
    .filter((t) => t.distance <= radiusM)
    .sort((a, b) => a.distance - b.distance);
}

function tankDisplayName(props) {
  return props.name_as_printed || props.display_name || props.mod_name || 'Unnamed tank';
}

function sheetLabel(sheet, meta) {
  if (meta) return `1954 sheet · 1:250,000 · ${meta.sheet_title || meta.sheet || ''}`;
  if (sheet === 'plan_25k') return '1954 city plan · 1:25,000';
  if (sheet === 'front_250k') return '1954 front sheet · 1:250,000';
  return sheet || '';
}

/* -------------------------------------------------------------------------
   Demo-data banner (Rule: model output that stands in for the real thing
   must be shown, not quietly passed off as real)
   ------------------------------------------------------------------------- */

function applyDemoBanner(demoData) {
  const banner = document.getElementById('demo-banner');
  const text = document.getElementById('demo-banner-text');
  const standIn = !!(demoData && demoData.stand_in);
  text.textContent = (demoData && demoData.note) || 'DEMO DATA: standing in for real model output.';
  banner.hidden = !standIn;
  const setH = () => {
    const h = banner.hidden ? 0 : banner.getBoundingClientRect().height;
    document.documentElement.style.setProperty('--banner-h', `${h}px`);
  };
  requestAnimationFrame(setH);
  window.addEventListener('resize', setH);
}

/* -------------------------------------------------------------------------
   Map bootstrap
   ------------------------------------------------------------------------- */

function initMap() {
  if (typeof maplibregl === 'undefined') {
    return Promise.reject(new Error('MapLibre GL JS did not load from the CDN.'));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const map = new maplibregl.Map({
      container: 'map',
      style: 'https://tiles.openfreemap.org/styles/liberty',
      center: PRESETS.stadium.center,
      zoom: PRESETS.stadium.zoom,
      pitch: PRESETS.stadium.pitch,
      bearing: PRESETS.stadium.bearing,
      attributionControl: false,
      antialias: true,
    });
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.on('load', () => { if (!settled) { settled = true; resolve(map); } });
    map.on('error', (e) => {
      console.error('MapLibre error', e && e.error);
      if (!settled) { settled = true; reject((e && e.error) || new Error('MapLibre failed to load the style.')); }
    });
  });
}

// Dusk sky/fog: warm horizon, cool zenith. Neither API is universally
// guaranteed across MapLibre builds, so both are best-effort.
function setupTerrainAndSky(map) {
  try {
    map.addSource('terrain-dem', {
      type: 'raster-dem',
      tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 15,
      encoding: 'terrarium',
    });
    map.setTerrain({ source: 'terrain-dem', exaggeration: 4 });
  } catch (err) {
    console.warn('Terrain unavailable', err);
  }

  try {
    if (typeof map.setFog === 'function') {
      map.setFog({
        range: [0.5, 10],
        color: 'rgba(255,196,140,0.85)',
        'high-color': 'rgba(36,38,74,0.9)',
        'horizon-blend': 0.18,
        'space-color': 'rgba(8,9,20,1)',
        'star-intensity': 0.15,
      });
    }
  } catch (err) {
    console.warn('Fog unavailable', err);
  }

  // A MapLibre "sky" layer (warm-horizon/cool-zenith gradient) was tried
  // here first, per the instruction to verify rendering before committing.
  // Live testing showed this maplibre-gl@5 build's style validator rejects
  // type: "sky" outright — it isn't in its enum of supported layer types
  // (fill/line/symbol/circle/heatmap/fill-extrusion/raster/hillshade/
  // color-relief/background), so addLayer throws a style-validation error
  // every time. Dropped in favour of setFog above (which this build does
  // support) plus a static CSS atmosphere gradient behind the canvas
  // (#sky-backdrop in index.html / style.css), which reliably gives the
  // same warm-horizon / cool-zenith read without depending on an
  // unsupported API.
}

// Find the buildings layer and a safe insertion point at runtime — never a
// hardcoded layer id, since the style is fetched live from openfreemap.
function analyzeStyleLayers(map) {
  const layers = (map.getStyle() || {}).layers || [];
  const building = layers.find((l) => l.type === 'fill-extrusion');
  const firstSymbol = layers.find((l) => l.type === 'symbol');
  return {
    buildingsLayerId: building ? building.id : null,
    rasterBeforeId: building ? building.id : (firstSymbol ? firstSymbol.id : undefined),
    symbolLayerIds: layers.filter((l) => l.type === 'symbol').map((l) => l.id),
  };
}

function safeBeforeId(map, id) {
  return (typeof id === 'string' && map.getLayer(id)) ? id : undefined;
}

function addSheetLayers(map, sheets, beforeId) {
  const before = safeBeforeId(map, beforeId);
  ['plan', 'front'].forEach((key) => {
    const sheet = sheets[key];
    if (!sheet) return;
    const srcId = `sheet-${key}`;
    map.addSource(srcId, { type: 'image', url: DATA + sheet.image, coordinates: sheet.corners });
    const opts = { id: `${srcId}-layer`, type: 'raster', source: srcId, paint: { 'raster-opacity': 0 } };
    if (before) map.addLayer(opts, before); else map.addLayer(opts);
  });
}

// Tanks: fill + two line layers split by status. line-dasharray is not
// reliably data-driven across GL style implementations, so "dashed for
// lost, solid for surviving" is done as two filtered layers rather than a
// single case/match expression on line-dasharray — guaranteed to render
// correctly rather than gambling on expression support.
function addTankLayers(map, tanksGeojson, beforeId) {
  const before = safeBeforeId(map, beforeId);
  map.addSource('tanks', { type: 'geojson', data: tanksGeojson });
  const layers = [
    { id: 'tanks-fill', type: 'fill', source: 'tanks', paint: { 'fill-color': '#2f6f9f', 'fill-opacity': 0.15 } },
    { id: 'tanks-line-lost', type: 'line', source: 'tanks', filter: ['==', ['get', 'status'], 'lost'],
      paint: { 'line-color': '#6fb2df', 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.15 } },
    { id: 'tanks-line-surviving', type: 'line', source: 'tanks', filter: ['==', ['get', 'status'], 'surviving'],
      paint: { 'line-color': '#6fb2df', 'line-width': 2, 'line-opacity': 0.15 } },
  ];
  layers.forEach((l) => { if (before) map.addLayer(l, before); else map.addLayer(l); });
}

function addFloodLayers(map, floodGeojson, beforeId) {
  const before = safeBeforeId(map, beforeId);
  map.addSource('flood', { type: 'geojson', data: floodGeojson });
  const layer = {
    id: 'flood-circles',
    type: 'circle',
    source: 'flood',
    filter: ['!=', ['get', 'list'], 'news'],
    layout: { visibility: state.floodVisible ? 'visible' : 'none' },
    paint: {
      'circle-radius': 5,
      'circle-color': ['match', ['get', 'list'],
        'KGIS flood-vulnerable', FLOOD_SWATCH['KGIS flood-vulnerable'],
        'flood-prone', FLOOD_SWATCH['flood-prone'],
        'BBMP low-lying', FLOOD_SWATCH['BBMP low-lying'],
        FLOOD_SWATCH['KGIS flood-vulnerable']],
      'circle-stroke-width': 1,
      'circle-stroke-color': 'rgba(10,8,6,0.75)',
      'circle-opacity': 0.88,
    },
  };
  if (before) map.addLayer(layer, before); else map.addLayer(layer);

  map.on('click', 'flood-circles', (e) => {
    const f = e.features && e.features[0];
    if (!f) return;
    new maplibregl.Popup({ offset: 10 })
      .setLngLat(e.lngLat)
      .setHTML(`<strong>${escapeHtml(f.properties.name || 'Flood point')}</strong><br>`
        + `<span style="color:var(--text-secondary);font-size:12px;">${escapeHtml(f.properties.list)}</span>`)
      .addTo(map);
  });
  map.on('mouseenter', 'flood-circles', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'flood-circles', () => { map.getCanvas().style.cursor = ''; });

  state.newsMarkerEls = [];
  floodGeojson.features.filter((f) => f.properties.list === 'news').forEach((f) => {
    const el = document.createElement('div');
    el.className = `news-marker${state.floodVisible ? '' : ' is-hidden'}`;
    el.title = f.properties.name || 'News-reported flooding';
    el.addEventListener('click', () => {
      new maplibregl.Popup({ offset: 12 })
        .setLngLat(f.geometry.coordinates)
        .setHTML(`<strong>${escapeHtml(f.properties.name || 'Reported flooding')}</strong><br>`
          + `<span style="color:var(--text-secondary);font-size:12px;">${escapeHtml(f.properties.date || '')}</span><br>`
          + `<a href="${escapeHtml(f.properties.source)}" target="_blank" rel="noopener" style="color:var(--accent);">source →</a>`)
        .addTo(map);
    });
    new maplibregl.Marker({ element: el }).setLngLat(f.geometry.coordinates).addTo(map);
    state.newsMarkerEls.push(el);
  });
}

function setFloodVisible(v) {
  state.floodVisible = v;
  if (state.map && state.map.getLayer('flood-circles')) {
    state.map.setLayoutProperty('flood-circles', 'visibility', v ? 'visible' : 'none');
  }
  (state.newsMarkerEls || []).forEach((el) => el.classList.toggle('is-hidden', !v));
}

/* -------------------------------------------------------------------------
   Rain pooling (CLAUDE.md P2) — "where water would pool on today's
   terrain", built from the SAME AWS Terrarium tiles already used for the
   3D terrain above, run through priority-flood depression filling by
   pipeline/rain.py. Ships as app/data/rain.json + rain_depth.png. This is
   an additional, off-by-default layer: it never replaces or conflicts with
   the 1954 sheets/tanks/flood layers, and every number shown about it
   (max depth, pooling %) is read from rain.json at runtime, never
   hardcoded here.

   Rule: never call or imply this is a flood prediction, anywhere in copy.

   Approach chosen: a MapLibre `canvas` source (as CLAUDE.md specifies)
   feeding an ordinary `raster` layer — the same layer *type* already used
   successfully for the 1954 sheets. That's a meaningful difference from
   the earlier "sky" investigation in setupTerrainAndSky() above: `sky` was
   rejected because it's a style *layer type* missing from this build's
   validator enum, whereas `canvas` is a *source* type consumed by a
   `raster` layer, which this build already proves out. Testing confirmed
   addSource({type:'canvas', ...}) works here. Using a canvas source (and
   not a plain `image` source) is what lets the reveal do a genuine depth
   threshold sweep client-side — redraw the canvas's pixels each animation
   frame, call source.play()/triggerRepaint(), and deeper pools cross the
   falling threshold before shallow fringes do, rather than everything
   fading in together. If addSource/addLayer ever throws in some other
   environment, ensureRainLayer() below falls back to a static `image`
   source (pre-tinted once via canvas.toDataURL()) and playRainReveal()
   just fades raster-opacity 0 → target over the same 3s — no threshold
   sweep, but same layer type, same corners, same disclaimer.
   ------------------------------------------------------------------------- */

const RAIN_REVEAL_MS = 3000;
const RAIN_TINT = [47, 111, 159]; // --water, #2f6f9f — same water colour family as tanks/flood
const RAIN_MAX_ALPHA = 217; // ~0.85 * 255 — matches the spec's "water is #2f6f9f at 0.85"

function loadImageEl(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load ${src}`));
    img.src = src;
  });
}

// Renders one animation frame of the threshold sweep into the live render
// canvas that backs the MapLibre canvas source. `progress` is 0..1 across
// RAIN_REVEAL_MS. The threshold falls from ~max depth to 0 as progress
// advances, so only the deepest depressions (highest pixel value) pass it
// early on; shallow fringes (low but nonzero value) only cross it near the
// end — the "water rising" look the spec asks for.
function drawRainThresholdFrame(progress) {
  const depth = state.rainDepth, ctx = state.rainRenderCtx, meta = state.rain;
  if (!depth || !ctx || !meta) return;
  const w = meta.width, h = meta.height;
  const out = ctx.createImageData(w, h);
  const eased = 1 - Math.pow(1 - progress, 2); // ease-out: quick to start, settles at the end
  const threshold = 255 * (1 - eased);
  const feather = 24; // soft edge in 8-bit pixel-value units, avoids a hard binary edge
  for (let i = 0; i < depth.length; i += 4) {
    const v = depth[i]; // rain_depth.png is greyscale: R === G === B
    let a = 0;
    if (v > 0) {
      let reveal = (v - threshold + feather) / feather;
      if (reveal < 0) reveal = 0; else if (reveal > 1) reveal = 1;
      a = reveal * (0.35 + 0.65 * (v / 255)) * RAIN_MAX_ALPHA; // deeper pixels read more opaque too
    }
    out.data[i] = RAIN_TINT[0];
    out.data[i + 1] = RAIN_TINT[1];
    out.data[i + 2] = RAIN_TINT[2];
    out.data[i + 3] = a;
  }
  ctx.putImageData(out, 0, 0);
}

// Lazy: only decode rain_depth.png and touch the map once the layer is
// first switched on, so the off-by-default toggle costs nothing at boot.
async function ensureRainLayer(map) {
  if (state.rainReady) return state.rainMode;
  const meta = state.rain;
  if (!meta) throw new Error('rain.json not loaded');

  const img = await loadImageEl(DATA + meta.image);
  const off = document.createElement('canvas');
  off.width = meta.width; off.height = meta.height;
  const offCtx = off.getContext('2d');
  offCtx.drawImage(img, 0, 0, meta.width, meta.height);
  state.rainDepth = offCtx.getImageData(0, 0, meta.width, meta.height).data;

  const renderCanvas = document.createElement('canvas');
  renderCanvas.width = meta.width; renderCanvas.height = meta.height;
  state.rainRenderCtx = renderCanvas.getContext('2d');
  state.rainRenderCanvas = renderCanvas;

  try {
    map.addSource('rain', { type: 'canvas', canvas: renderCanvas, coordinates: meta.corners, animate: false });
    map.addLayer({
      id: 'rain-layer',
      type: 'raster',
      source: 'rain',
      layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0 },
    }, state.rainBeforeId);
    state.rainMode = 'canvas';
  } catch (err) {
    console.warn('Canvas source unavailable for the rain layer; falling back to a static tinted raster.', err);
    try { if (map.getLayer('rain-layer')) map.removeLayer('rain-layer'); } catch (e) { /* no-op */ }
    try { if (map.getSource('rain')) map.removeSource('rain'); } catch (e) { /* no-op */ }
    drawRainThresholdFrame(1); // pre-tint the fallback at full reveal; only raster-opacity animates from here
    map.addSource('rain', { type: 'image', url: renderCanvas.toDataURL(), coordinates: meta.corners });
    map.addLayer({
      id: 'rain-layer',
      type: 'raster',
      source: 'rain',
      layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0 },
    }, state.rainBeforeId);
    state.rainMode = 'image';
  }

  state.rainReady = true;
  return state.rainMode;
}

function stopRainAnimation() {
  if (state.rainAnimId) cancelAnimationFrame(state.rainAnimId);
  state.rainAnimId = null;
}

function playRainReveal(map) {
  stopRainAnimation();
  if (!map.getLayer('rain-layer')) return;
  map.setLayoutProperty('rain-layer', 'visibility', 'visible');

  if (state.rainMode === 'canvas') {
    const src = map.getSource('rain');
    if (src && typeof src.play === 'function') src.play();
    map.setPaintProperty('rain-layer', 'raster-opacity', 0.92);
    const start = performance.now();
    let lastDraw = 0;
    const step = (now) => {
      if (!state.rainVisible) return; // toggled off mid-animation
      const progress = Math.min(1, (now - start) / RAIN_REVEAL_MS);
      if (now - lastDraw > 45 || progress >= 1) {
        drawRainThresholdFrame(progress);
        lastDraw = now;
        map.triggerRepaint();
      }
      if (progress < 1) {
        state.rainAnimId = requestAnimationFrame(step);
      } else {
        const s = map.getSource('rain');
        if (s && typeof s.pause === 'function') s.pause();
      }
    };
    state.rainAnimId = requestAnimationFrame(step);
  } else {
    // Fallback path: fade raster-opacity 0 -> target over the same 3s.
    const start = performance.now();
    const target = 0.85;
    const step = (now) => {
      if (!state.rainVisible) return;
      const progress = Math.min(1, (now - start) / RAIN_REVEAL_MS);
      const eased = 1 - Math.pow(1 - progress, 2);
      map.setPaintProperty('rain-layer', 'raster-opacity', eased * target);
      if (progress < 1) state.rainAnimId = requestAnimationFrame(step);
    };
    state.rainAnimId = requestAnimationFrame(step);
  }
}

function hideRainLayer(map) {
  stopRainAnimation();
  if (map.getLayer('rain-layer')) {
    map.setLayoutProperty('rain-layer', 'visibility', 'none');
    map.setPaintProperty('rain-layer', 'raster-opacity', 0);
  }
  if (state.rainMode === 'canvas') {
    const src = map.getSource('rain');
    if (src && typeof src.pause === 'function') src.pause();
  }
}

async function setRainVisible(map, v) {
  state.rainVisible = v;
  if (!v) { hideRainLayer(map); return; }
  try {
    await ensureRainLayer(map);
    playRainReveal(map);
  } catch (err) {
    console.error('Rain layer failed to load', err);
    toast('Rain layer failed to load — check the console.');
    state.rainVisible = false;
    const input = document.getElementById('rain-toggle-input');
    if (input) input.checked = false;
  }
}

// Tank name labels: HTML overlays in italic serif, positioned via
// map.project(). openfreemap's "liberty" style ships its own glyph PBFs
// (Noto Sans family) for symbol-layer text; it does not carry an italic
// serif face, so a MapLibre symbol layer with text-font: ['EB Garamond
// Italic'] would silently fall back to whatever glyph range the style
// server has, not the serif the spec asks for ("echoing the map's own
// lettering"). HTML overlays guarantee the actual webfont renders.
function setupLabels(map, tanksGeojson) {
  const container = document.getElementById('tank-label-layer');
  const labeled = tanksGeojson.features
    .filter((f) => f.properties.name_as_printed)
    .map((f) => ({ id: f.properties.id, name: f.properties.name_as_printed, center: polygonCentroid(f.geometry) }));

  const els = {};
  labeled.forEach((t) => {
    const el = document.createElement('div');
    el.className = 'tank-label';
    el.textContent = t.name;
    container.appendChild(el);
    els[t.id] = el;
  });

  function update() {
    labeled.forEach((t) => {
      const el = els[t.id];
      if (!el) return;
      const p = map.project(t.center);
      if (p.x < -80 || p.x > window.innerWidth + 80 || p.y < -40 || p.y > window.innerHeight + 40) {
        el.style.display = 'none';
      } else {
        el.style.display = '';
        el.style.left = `${p.x}px`;
        el.style.top = `${p.y}px`;
      }
    });
  }
  map.on('move', update);
  map.on('resize', update);
  update();
}

/* -------------------------------------------------------------------------
   Year slider — 0 = 2026, 1 = 1954
   ------------------------------------------------------------------------- */

function safeSetPaint(map, id, prop, val) {
  if (map.getLayer(id)) { try { map.setPaintProperty(id, prop, val); } catch (e) { /* no-op */ } }
}

function applyYearBlend(t) {
  document.documentElement.style.setProperty('--t', String(t));
  const now = document.getElementById('year-label-now');
  const then = document.getElementById('year-label-then');
  if (now) now.style.opacity = String(1 - t * 0.6);
  if (then) then.style.opacity = String(0.4 + t * 0.6);

  const map = state.map;
  if (!map) return;

  safeSetPaint(map, 'sheet-plan-layer', 'raster-opacity', t);
  safeSetPaint(map, 'sheet-front-layer', 'raster-opacity', t);
  safeSetPaint(map, 'tanks-fill', 'fill-opacity', 0.15 + 0.7 * t);
  safeSetPaint(map, 'tanks-line-lost', 'line-opacity', 0.15 + 0.7 * t);
  safeSetPaint(map, 'tanks-line-surviving', 'line-opacity', 0.15 + 0.7 * t);

  if (state.buildingsLayerId) {
    try {
      map.setPaintProperty(state.buildingsLayerId, 'fill-extrusion-height',
        ['*', ['coalesce', ['get', 'render_height'], 0], 1 - t]);
    } catch (e) { /* style may not expose render_height the same way on all zooms */ }
  }
  (state.symbolLayerIds || []).forEach((id) => {
    try { map.setPaintProperty(id, 'text-opacity', 1 - 0.8 * t); } catch (e) { /* no-op */ }
    try { map.setPaintProperty(id, 'icon-opacity', 1 - 0.8 * t); } catch (e) { /* no-op */ }
  });
}

function wireSlider() {
  const slider = document.getElementById('year-slider');
  slider.addEventListener('input', () => applyYearBlend(parseFloat(slider.value)));
}

function wirePresets(map) {
  const buttons = document.querySelectorAll('.presets__btn');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      buttons.forEach((b) => b.setAttribute('aria-pressed', String(b === btn)));
      map.flyTo({ ...PRESETS[btn.dataset.preset], essential: true, duration: 1800 });
    });
  });
  const initial = document.querySelector('.presets__btn[data-preset="stadium"]');
  if (initial) initial.setAttribute('aria-pressed', 'true');
}

/* -------------------------------------------------------------------------
   Drawers
   ------------------------------------------------------------------------- */

const DRAWER_NAMES = ['source', 'flood', 'scoreboard', 'fence', 'rain', 'nearby'];

function closeDrawer() {
  state.activeDrawer = null;
  DRAWER_NAMES.forEach((n) => {
    const el = document.getElementById(`drawer-${n}`);
    el.classList.remove('is-open');
    el.setAttribute('aria-hidden', 'true');
  });
  document.querySelectorAll('.rail__btn').forEach((b) => b.setAttribute('aria-pressed', 'false'));
  const bd = document.getElementById('drawer-backdrop');
  bd.classList.remove('is-open');
  bd.hidden = true;
  document.body.classList.remove('drawer-open');
}

function openDrawer(name) {
  state.activeDrawer = name;
  // Every other drawer is populated once at boot from static data; "nearby" depends on wherever
  // the user last searched, which can change after boot, so it re-renders on every open.
  if (name === 'nearby') populateNearbyDrawer();
  DRAWER_NAMES.forEach((n) => {
    const el = document.getElementById(`drawer-${n}`);
    const open = n === name;
    el.classList.toggle('is-open', open);
    el.setAttribute('aria-hidden', String(!open));
  });
  document.querySelectorAll('.rail__btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.drawer === name)));
  const bd = document.getElementById('drawer-backdrop');
  bd.hidden = false;
  requestAnimationFrame(() => bd.classList.add('is-open'));
  // Shift the rail and the bottom control bar clear of the open drawer so
  // neither is visually clipped underneath it (drawer sits above both).
  document.body.classList.add('drawer-open');
}

function toggleDrawer(name) {
  if (state.activeDrawer === name) closeDrawer(); else openDrawer(name);
}

function wireRailAndDrawers() {
  document.querySelectorAll('.rail__btn').forEach((btn) => {
    // Flood/Score/Rain are Bengaluru-only data (build-2 rule 2: no flood claims for other
    // cities; scoreboard and rain are Bengaluru-eval/terrain-specific outputs that don't exist
    // for other cities either) — hide those rail entries entirely rather than show empty panels.
    if (btn.dataset.cityOnly === 'bengaluru' && state.cityMode) { btn.hidden = true; return; }
    btn.addEventListener('click', () => toggleDrawer(btn.dataset.drawer));
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('.panel-close')) closeDrawer();
    const copyBtn = e.target.closest('#copy-link-btn');
    if (copyBtn) copyShareLink(copyBtn.dataset.lon, copyBtn.dataset.lat);
    const shareBtn = e.target.closest('#native-share-btn');
    if (shareBtn) nativeShare(shareBtn.dataset.lon, shareBtn.dataset.lat, shareBtn.dataset.label);
    const nearbyItem = e.target.closest('.nearby-item');
    if (nearbyItem && nearbyItem.dataset.id) flyToTankId(nearbyItem.dataset.id);
  });
  document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
}

function shareURLFor(lon, lat) {
  const url = new URL(window.location.href);
  url.searchParams.set('city', state.cityKey);
  url.searchParams.set('at', `${parseFloat(lat).toFixed(6)},${parseFloat(lon).toFixed(6)}`);
  return url.toString();
}

async function copyShareLink(lon, lat) {
  const url = shareURLFor(lon, lat);
  try {
    await navigator.clipboard.writeText(url);
    toast('Link copied.');
  } catch (err) {
    toast(url);
  }
}

async function nativeShare(lon, lat, label) {
  const url = shareURLFor(lon, lat);
  if (navigator.share) {
    try { await navigator.share({ title: `Kere — ${label || 'a location'}`, url }); } catch (err) { /* user cancelled */ }
  } else {
    copyShareLink(lon, lat);
  }
}

function flyToTankId(id) {
  const entry = (state.tanksWithCentroid || []).find((t) => t.props.id === id);
  if (!entry) return;
  state.map.flyTo({ center: entry.centroid, zoom: 15.5, pitch: 52, essential: true, duration: 1400 });
  openSourceDrawer(entry.props);
}

function closeButtonHTML() {
  return '<button class="panel-close" aria-label="Close panel"><svg viewBox="0 0 14 14" aria-hidden="true">'
    + '<path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>';
}

/* --- Source card ---------------------------------------------------------- */

function openSourceDrawer(props, searchCtx) {
  document.getElementById('drawer-source-body').innerHTML = buildSourceCardHTML(props, searchCtx);
  openDrawer('source');
}

// Clicking a tank should feel responsive on a big screen, not just open a panel with no camera
// motion — a short fly-in toward whatever was clicked, then the source card.
function onTankClick(map, e) {
  const f = e.features && e.features[0];
  if (!f) return;
  const center = polygonCentroid(f.geometry);
  map.flyTo({ center, zoom: Math.max(map.getZoom(), 15), essential: true, duration: 900 });
  openSourceDrawer(f.properties);
}

function shareRowHTML(lon, lat, label) {
  return `<div class="share-row">`
    + `<button class="share-btn" id="copy-link-btn" type="button" data-lon="${lon}" data-lat="${lat}">`
    + `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.5 9.5 9.5 6.5M6 4.5 7 3.5a2.4 2.4 0 0 1 3.4 3.4L9.3 8M10 11.5 9 12.5a2.4 2.4 0 0 1-3.4-3.4L6.7 8" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>Copy link</button>`
    + `<button class="share-btn" id="native-share-btn" type="button" data-lon="${lon}" data-lat="${lat}" data-label="${escapeHtml(label || '')}">`
    + `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2v8m0-8L5.5 4.5M8 2l2.5 2.5M3 9v3.5a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>Share</button>`
    + `</div>`;
}

// Bengaluru's tank properties (MOD-sourced name/current_use/redated, georef.json for alignment)
// and a city's (display_name/now_osm/nearest_place_as_printed, meta.json for alignment) shape
// differently -- this reads whichever set of fields the current tank actually has, never
// invents a name or a source (CLAUDE.md rule 3).
function buildSourceCardHTML(props, searchCtx) {
  const hasPrinted = !!props.name_as_printed;
  const hasModName = !!props.mod_name;
  const heading = tankDisplayName(props);
  let nameSource;
  if (hasPrinted) nameSource = 'printed on the 1954 sheet';
  else if (hasModName) nameSource = 'MOD Foundation record';
  else if (props.nearest_place_as_printed) nameSource = `not printed for this tank — nearest place printed on the sheet is "${props.nearest_place_as_printed}"`;
  else nameSource = 'no name recorded — geometry only';
  const statusLabel = props.status === 'surviving' ? 'Surviving' : 'Lost';
  const georef = state.georef;
  const gcpCount = georef && georef.gcps ? Object.keys(georef.gcps).length : null;
  const meta = state.cityMeta;

  let html = '';
  html += `<div class="panel-head"><div><h2>${escapeHtml(heading)}</h2><p>${sheetLabel(props.sheet, meta)}</p></div>${closeButtonHTML()}</div>`;

  if (searchCtx) {
    html += `<div class="card-search-context">Nearest 1954 tank to <strong>${escapeHtml(searchCtx.queryName)}</strong>: `
      + `${Math.round(searchCtx.distanceM).toLocaleString()} m away. Distance and record only — never a flood prediction.</div>`;
    if (searchCtx.lon != null && searchCtx.lat != null) {
      html += shareRowHTML(searchCtx.lon, searchCtx.lat, searchCtx.queryName);
    }
  }

  if (props.crop) {
    html += `<div class="card-crop"><img src="${assetBase()}${props.crop}" alt="Crop of the 1954 sheet around ${escapeHtml(heading)}" loading="lazy"></div>`;
  }

  html += `<p class="card-meta">Name source</p><p class="card-name-source">${escapeHtml(nameSource)}</p>`;

  html += '<div class="badge-row">';
  html += `<span class="badge badge--${props.status}"><span class="badge__dot${props.status === 'lost' ? ' badge__dot--dashed' : ''}"></span>${statusLabel}</span>`;
  if (props.style) html += `<span class="badge">${escapeHtml(props.style)}</span>`;
  html += '</div>';

  html += '<div class="fact-list">';
  if (props.redated && props.mod_last_mapped) {
    html += `<div class="fact fact--redated"><p class="fact__label">Still drawn in 1954</p>`
      + `<p class="fact__value">Last surveyed by MOD: ${escapeHtml(props.mod_last_mapped)}, still drawn on the 1954 compilation.</p></div>`;
  }
  if (props.mod_current_use) {
    html += `<div class="fact"><p class="fact__label">What's there now</p>`
      + `<p class="fact__value">${escapeHtml(props.mod_current_use)} (MOD Foundation)</p></div>`;
  } else if (props.now_osm && props.now_osm.name) {
    html += `<div class="fact"><p class="fact__label">What's there now</p>`
      + `<p class="fact__value">${escapeHtml(props.now_osm.name)}${props.now_osm.type ? ` (${escapeHtml(props.now_osm.type)})` : ''} — ${escapeHtml(props.now_osm.source)}</p></div>`;
  } else if (props.status === 'lost') {
    html += `<div class="fact"><p class="fact__label">What's there now</p>`
      + `<p class="fact__value">not recorded${meta ? ' by OpenStreetMap' : ' by MOD'}</p></div>`;
  }
  if (hasModName && hasPrinted) {
    html += `<div class="fact"><p class="fact__label">MOD record</p>`
      + `<p class="fact__value">${escapeHtml(props.mod_name)}${props.mod_last_mapped ? ` · last surveyed ${escapeHtml(props.mod_last_mapped)}` : ''}</p></div>`;
  }
  if (props.area_m2) {
    html += `<div class="fact"><p class="fact__label">Traced extent</p>`
      + `<p class="fact__value">${(props.area_m2 / 10000).toFixed(1)} ha, from pipeline/grow.py on the scan</p></div>`;
  }
  html += '</div>';

  if (meta) {
    const compiledYear = /Compiled in 1955/.test(meta.compiled_note || '') ? '1955' : '1954';
    html += `<p class="card-footnote">On a map compiled in ${compiledYear} (${escapeHtml(meta.sheet_title || '')}, ${escapeHtml(meta.sheet || '')}), `
      + `aligned to ±${meta.alignment_median_offset_m}&nbsp;m using its own printed neatline corners.</p>`;
  } else if (props.sheet === 'plan_25k' && georef && georef.rms_m != null && gcpCount != null) {
    html += `<p class="card-footnote">On the 1954 compilation, aligned ±${georef.rms_m} m using ${gcpCount} tanks.</p>`;
  } else if (props.sheet === 'front_250k') {
    html += '<p class="card-footnote">From the 1954 front sheet (1:250,000; front sheet: Survey of India 1945–46), aligned to its printed neatline corners.</p>';
  }

  return html;
}

/* --- Flood drawer ----------------------------------------------------------- */

function formatBacktestRow(row) {
  return { pct: Math.round(row.share * 100), randomPct: Math.round(row.random_share * 100) };
}

function populateFloodDrawer() {
  const body = document.getElementById('drawer-flood-body');
  const bt = state.backtest;
  const total = state.floodPoints.features.length;
  const counts = {};
  state.floodPoints.features.forEach((f) => { counts[f.properties.list] = (counts[f.properties.list] || 0) + 1; });

  let html = `<div class="panel-head"><div><h2>Flood points</h2>`
    + `<p>${total.toLocaleString()} official flood points in the study area, from KGIS/BBMP plus two newsroom reports.</p></div>${closeButtonHTML()}</div>`;

  html += `<div class="flood-toggle"><span class="flood-toggle__label">Show on map`
    + `<span class="flood-toggle__hint">Circles by list · pulsing pins are news reports</span></span>`
    + `<label class="switch"><input type="checkbox" id="flood-toggle-input" ${state.floodVisible ? 'checked' : ''}><span class="switch__track"></span></label></div>`;

  if (bt && bt.this_layer) {
    const rows = bt.this_layer.rows.filter((r) => r.radius_m === 250);
    const lost = rows.find((r) => /lost/i.test(r.layer));
    const surv = rows.find((r) => /surviving/i.test(r.layer));
    if (lost && surv) {
      const l = formatBacktestRow(lost), s = formatBacktestRow(surv);
      html += `<div class="legend-block"><p class="legend-block__stat"><strong>${l.pct}%</strong> of ${bt.this_layer.n_flood_points} flood points `
        + `are within 250&nbsp;m of a lost lake vs <strong>${l.randomPct}%</strong> of random points; `
        + `surviving lakes <strong>${s.pct}%</strong> vs <strong>${s.randomPct}%</strong>.</p>`
        + `<p class="legend-block__source">Opus 5.5's reading of the 1954 plan, ${bt.area_km2} km² study area · scripts/backtest.py</p></div>`;
    }
  }
  if (bt && bt.reference_MOD_hand_traced) {
    const rows = bt.reference_MOD_hand_traced.rows.filter((r) => r.radius_m === 250);
    const lost = rows.find((r) => /lost/i.test(r.layer));
    const surv = rows.find((r) => /existing/i.test(r.layer));
    if (lost && surv) {
      const l = formatBacktestRow(lost), s = formatBacktestRow(surv);
      html += `<div class="legend-block"><p class="legend-block__stat">MOD's own hand-traced layer, for reference: `
        + `<strong>${l.pct}%</strong> vs ${l.randomPct}% random near lost lakes; <strong>${s.pct}%</strong> vs ${s.randomPct}% near surviving ones.</p>`
        + `<p class="legend-block__source">${bt.reference_MOD_hand_traced.n_flood_points} flood points</p></div>`;
    }
  }

  html += '<p class="card-meta">By list</p><ul class="legend-list">';
  Object.keys(counts).forEach((list) => {
    html += `<li><span class="legend-swatch" style="background:${FLOOD_SWATCH[list] || '#e4572e'}"></span>${escapeHtml(list)}<span class="legend-count">${counts[list]}</span></li>`;
  });
  html += '</ul>';

  const newsItems = state.floodPoints.features.filter((f) => f.properties.list === 'news');
  if (newsItems.length) {
    html += '<p class="card-meta">News-reported</p><ul class="news-list">';
    newsItems.forEach((f) => {
      html += `<li class="news-item"><p class="news-item__name">${escapeHtml(f.properties.name || 'Unnamed locality')}</p>`
        + `<span class="news-item__date">${escapeHtml(f.properties.date || '')}</span><br>`
        + `<a href="${escapeHtml(f.properties.source)}" target="_blank" rel="noopener">source →</a></li>`;
    });
    html += '</ul>';
  }

  body.innerHTML = html;
  document.getElementById('flood-toggle-input').addEventListener('change', (e) => setFloodVisible(e.target.checked));
}

/* --- Scoreboard drawer ------------------------------------------------------ */

function round1(x) { return Math.round(x * 10) / 10; }
function fMeanSd(arr) {
  if (!arr) return '—';
  const [m, s] = arr;
  return (s && s > 0.05) ? `${round1(m)} ± ${round1(s)}` : `${round1(m)}`;
}
function fPct(arr) { return arr ? `${Math.round(arr[0] * 100)}%` : '—'; }
function fRatio(arr) { return arr ? arr[0].toFixed(2) : '—'; }
function fUsd(v) { return (v == null) ? '—' : `$${v.toFixed(2)}`; }
function fSecs(v) { return (v == null) ? '—' : `${v.toFixed(1)}s`; }

const SCORE_ROWS = [
  { label: 'Tanks found (of 18)', get: (e) => fMeanSd(e.plan_25k && e.plan_25k.unique_tanks_found_of_18) },
  { label: 'Invented tanks per run (plan, 16 tiles)', get: (e) => fMeanSd(e.plan_25k && e.plan_25k.invented_per_run) },
  { label: 'Printed names read exactly', get: (e) => fPct(e.plan_25k && e.plan_25k.names_correct_rate) },
  { label: 'Unsourced names per run', get: (e) => fMeanSd(e.plan_25k && e.plan_25k.names_unsourced_per_run) },
  { label: 'Extent accuracy (box IoU)', get: (e) => fRatio(e.plan_25k && e.plan_25k.bbox_iou) },
  { label: 'Colour-sheet recall (front)', get: (e) => fPct(e.front_250k && e.front_250k.recall) },
  { label: 'API cost, eval run (USD)', get: (e) => fUsd(e.cost_usd_total) },
  { label: 'Mean latency per call', get: (e) => fSecs(e.mean_latency_s) },
];

// The Breakthrough finding as a chart, not a table row: Opus 5 invents far more phantom tanks
// per run on the hard sheet, and finds far fewer of the real ones. Two bars per metric, direct
// value labels (no color-only identity, no hover needed for a two-series static comparison),
// one categorical hue per model reused from the model's OWN meaning elsewhere in this app
// (--accent already marks Opus 5.5 as the headline column in the table above).
function breakthroughChartHTML(nar) {
  const fs = nar && nar.supporting_numbers && nar.supporting_numbers.front_250k;
  if (!fs) return '';
  const W = 380, barH = 14, gap = 6, groupGap = 26, labelW = 150, valueW = 46;
  const trackW = W - labelW - valueW;
  const metrics = [
    { key: 'invented_per_run', label: 'Invented tanks / run (front sheet)', max: 12, fmt: (v) => v.toFixed(1) },
    { key: 'recall', label: 'Verified tanks found (front sheet)', max: 1, fmt: (v) => `${Math.round(v * 100)}%` },
  ];
  const models = [
    { key: 'opus-5', label: 'Opus 5', color: 'var(--text-tertiary)' },
    { key: 'opus-5-5', label: 'Opus 5.5', color: 'var(--accent)' },
  ];
  let y = 28; // room for the legend row
  const bars = [];
  metrics.forEach((m) => {
    bars.push(`<text x="0" y="${y - 6}" class="chart-metric-label">${escapeHtml(m.label)}</text>`);
    y += 4;
    models.forEach((model) => {
      const v = fs[m.key] && fs[m.key][model.key] ? fs[m.key][model.key][0] : 0;
      const w = Math.max(2, (v / m.max) * trackW);
      bars.push(
        `<rect x="${labelW}" y="${y}" width="${trackW}" height="${barH}" rx="3" class="chart-track"/>`
        + `<rect x="${labelW}" y="${y}" width="${w}" height="${barH}" rx="3" fill="${model.color}"/>`
        + `<text x="${labelW - 8}" y="${y + barH - 3}" text-anchor="end" class="chart-model-label">${model.label}</text>`
        + `<text x="${labelW + trackW + 8}" y="${y + barH - 3}" class="chart-value-label">${m.fmt(v)}</text>`
      );
      y += barH + gap;
    });
    y += groupGap - gap;
  });
  const legend = models.map((m) => `<span class="chart-legend__item"><span class="chart-legend__swatch" style="background:${m.color}"></span>${m.label}</span>`).join('');
  return `<div class="breakthrough-chart">
    <div class="chart-legend">${legend}</div>
    <svg viewBox="0 0 ${W} ${y}" role="img" aria-label="Opus 5 vs Opus 5.5 on the front sheet: invented tanks per run and recall">${bars.join('')}</svg>
  </div>`;
}

function populateScoreboardDrawer() {
  const body = document.getElementById('drawer-scoreboard-body');
  const sb = state.scoreboard.scoreboard;
  const cols = [
    { key: 'claude-opus-5', label: 'Opus 5' },
    { key: 'claude-opus-5-5', label: 'Opus 5.5', headline: true },
    { key: 'hand-traced (answer key)', label: 'Hand-traced' },
  ];

  let html = `<div class="panel-head"><div><h2>Scoreboard</h2>`
    + `<p>Same prompt, same effort, both models — scored against a hand-traced answer key by eval/score.py.</p></div>${closeButtonHTML()}</div>`;

  const nar = state.narrative;
  if (nar && nar.headline) {
    html += `<div class="legend-block"><p class="legend-block__stat">${escapeHtml(nar.headline)}</p>`
      + `<p class="legend-block__source">${escapeHtml(nar.subhead || '')}</p></div>`;
    html += breakthroughChartHTML(nar);
  }

  html += '<table class="score-table"><thead><tr><th></th>';
  cols.forEach((c) => { html += `<th class="${c.headline ? 'col-headline' : ''}">${c.label}</th>`; });
  html += '</tr></thead><tbody>';
  SCORE_ROWS.forEach((row) => {
    html += `<tr><td>${row.label}</td>`;
    cols.forEach((c) => {
      const entry = sb[c.key] || {};
      html += `<td class="${c.headline ? 'col-headline' : ''}">${row.get(entry)}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';

  html += '<p class="overlay-group-label">Tile overlays — green circle = hit, red X = invented</p>';
  ['claude-opus-5', 'claude-opus-5-5'].forEach((model) => {
    const label = model === 'claude-opus-5' ? 'Opus 5' : 'Opus 5.5';
    html += `<p class="overlay-group-label">${label}</p><div class="overlay-grid">`;
    ['plan_r2c2__run1.jpg', 'plan_r1c1__run1.jpg'].forEach((tile) => {
      html += `<figure class="overlay-card"><img src="${DATA}overlays/${model}/${tile}" alt="${label} overlay, ${tile}" loading="lazy">`
        + `<figcaption>${tile.replace('__run1.jpg', '')}</figcaption></figure>`;
    });
    html += '</div>';
  });

  body.innerHTML = html;
}

/* --- Fence drawer ------------------------------------------------------------ */

function populateFenceDrawer() {
  const body = document.getElementById('drawer-fence-body');
  const groups = state.cityMode
    ? [{ label: 'Opus 5.5', items: state.cityRefused || [] }]
    : [{ label: 'Opus 5.5', items: state.refused55 || [] }, { label: 'Opus 5', items: state.refused5 || [] }];
  const total = groups.reduce((n, g) => n + g.items.length, 0);

  let html = `<div class="panel-head"><div><h2>The Fence</h2><p>&ldquo;The model pointed here. The map says no.&rdquo;</p></div>${closeButtonHTML()}</div>`;
  html += `<p class="fence-count"><strong>${total}</strong> point${total === 1 ? '' : 's'} refused by pipeline/grow.py — `
    + `${groups.map((g) => `${g.items.length} from ${g.label}`).join(', ')}.</p>`;

  groups.forEach((g) => {
    html += `<div class="fence-group"><h3>${g.label} (${g.items.length})</h3>`;
    if (!g.items.length) {
      html += `<p class="empty-note">No refusals from ${g.label}.</p>`;
    }
    g.items.forEach((item) => {
      const runs = item.runs || [];
      const tiles = item.tile || [];
      html += '<div class="fence-item">'
        + `<div class="fence-item__crop"><img src="${assetBase()}${item.crop}" alt="" loading="lazy"></div>`
        + `<div><p class="fence-item__reason">${escapeHtml(item.reason)}</p>`
        + `<p class="fence-item__meta">${escapeHtml(sheetLabel(item.sheet, state.cityMeta))} · tiles: ${tiles.map(escapeHtml).join(', ')} · seen in ${runs.length} run${runs.length === 1 ? '' : 's'}</p></div>`
        + '</div>';
    });
    html += '</div>';
  });

  body.innerHTML = html;
}

/* --- Nearby drawer ("Lost lakes near you") ---------------------------------- */

const NEARBY_RADIUS_M = 2000;

function populateNearbyDrawer() {
  const body = document.getElementById('drawer-nearby-body');
  const pt = state.lastSearchPoint;
  let html = `<div class="panel-head"><div><h2>Lost lakes near you</h2>`
    + `<p>Every lost tank within 2&nbsp;km of your last search, nearest first. Distance and record only.</p></div>${closeButtonHTML()}</div>`;

  if (!pt) {
    html += '<p class="empty-note">Search an address or locality first — this list fills in from that point.</p>';
    body.innerHTML = html;
    return;
  }
  const nearby = nearbyLostTanks(pt.lon, pt.lat, NEARBY_RADIUS_M);
  html += `<p class="card-search-context">Around <strong>${escapeHtml(pt.name)}</strong>: ${nearby.length} lost lake${nearby.length === 1 ? '' : 's'} within ${NEARBY_RADIUS_M / 1000}&nbsp;km.</p>`;
  if (!nearby.length) {
    html += '<p class="empty-note">No lost tank found within 2 km of this point in the current data.</p>';
  } else {
    nearby.forEach((t) => {
      const p = t.props;
      const now = p.mod_current_use || (p.now_osm && p.now_osm.name) || 'not recorded';
      html += `<button class="nearby-item" type="button" data-id="${escapeHtml(p.id)}">`
        + `<div><p class="nearby-item__name">${escapeHtml(tankDisplayName(p))}</p>`
        + `<p class="nearby-item__meta">now: ${escapeHtml(now)}</p></div>`
        + `<span class="nearby-item__dist">${Math.round(t.distance)}&nbsp;m</span></button>`;
    });
  }
  body.innerHTML = html;
}

/* --- Rain drawer -------------------------------------------------------------
   Everything below is read straight from state.rain (app/data/rain.json) at
   render time — the max depth and the pooling share are never retyped as
   literals here, and the disclaimer text is the file's own wording, not a
   paraphrase, per the "never a flood prediction" rule. */

function populateRainDrawer() {
  const body = document.getElementById('drawer-rain-body');
  const meta = state.rain;
  const disclaimer = (meta && meta.disclaimer) || '';

  const railBtn = document.querySelector('.rail__btn[data-drawer="rain"]');
  if (railBtn && disclaimer) railBtn.title = disclaimer;

  let html = `<div class="panel-head"><div><h2>Rain pooling</h2>`
    + `<p>${escapeHtml(disclaimer)}</p></div>${closeButtonHTML()}</div>`;

  html += `<div class="flood-toggle"><span class="flood-toggle__label">Show on map`
    + `<span class="flood-toggle__hint">Reveals over ~3s — deepest pools first, shallow fringes last</span></span>`
    + `<label class="switch"><input type="checkbox" id="rain-toggle-input" ${state.rainVisible ? 'checked' : ''}><span class="switch__track"></span></label></div>`;

  if (meta) {
    const pct = meta.total_cells ? (meta.pooling_cells / meta.total_cells) * 100 : null;
    const pctStr = pct == null ? '—' : (pct < 10 ? pct.toFixed(1) : Math.round(pct));
    html += `<div class="legend-block"><p class="legend-block__stat">Up to <strong>${meta.max_depth_m}&nbsp;m</strong> of standing depth on today's terrain model — `
      + `<strong>${pctStr}%</strong> of the study grid (${meta.pooling_cells.toLocaleString()} of ${meta.total_cells.toLocaleString()} cells, zoom ${meta.zoom}) would pool.</p>`
      + `<p class="legend-block__source">${escapeHtml(meta.source || '')} · pipeline/rain.py → app/data/rain.json</p></div>`;
  }

  html += `<p class="card-footnote">${escapeHtml(disclaimer || 'Where water would pool on today\'s terrain — not a flood prediction.')}</p>`;

  body.innerHTML = html;
  const toggle = document.getElementById('rain-toggle-input');
  if (toggle) toggle.addEventListener('change', (e) => setRainVisible(state.map, e.target.checked));
}

/* -------------------------------------------------------------------------
   Search — client-side gazetteer match only, no geocoding, ever
   ------------------------------------------------------------------------- */

// Photon (https://photon.komoot.io), biased to the current city — only ever called as a
// fallback when the local gazetteer comes up short, never during demo mode (build-2 rule:
// "no geocoding calls during the demo"; the gazetteer is tried first always).
async function photonSearch(query, biasLon, biasLat) {
  const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(query)}&lat=${biasLat}&lon=${biasLon}&limit=5`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Photon ${res.status}`);
  const data = await res.json();
  return (data.features || []).map((f) => ({
    name: [f.properties.name, f.properties.city, f.properties.state].filter(Boolean).join(', ') || query,
    lon: f.geometry.coordinates[0],
    lat: f.geometry.coordinates[1],
    fromPhoton: true,
  }));
}

function wireSearch(map) {
  const input = document.getElementById('search-input');
  const list = document.getElementById('search-suggestions');
  let activeIndex = -1;
  let currentMatches = [];
  let photonTimer = null;
  let photonQueryToken = 0;

  function renderMatches(matches, query) {
    currentMatches = matches;
    activeIndex = -1;
    if (!matches.length) {
      list.innerHTML = query ? `<li class="is-empty">No locality matches "${escapeHtml(query)}"</li>` : '';
      list.hidden = !query;
      input.setAttribute('aria-expanded', String(!!query));
      return;
    }
    const lower = query.toLowerCase();
    list.innerHTML = matches.map((m, i) => {
      const suffix = m.fromPhoton ? ' <span style="color:var(--text-tertiary);font-size:11px;">· web</span>' : '';
      const idx = m.name.toLowerCase().indexOf(lower);
      if (idx < 0) return `<li role="option" data-index="${i}">${escapeHtml(m.name)}${suffix}</li>`;
      const before = escapeHtml(m.name.slice(0, idx));
      const mid = escapeHtml(m.name.slice(idx, idx + query.length));
      const after = escapeHtml(m.name.slice(idx + query.length));
      return `<li role="option" data-index="${i}">${before}<mark>${mid}</mark>${after}${suffix}</li>`;
    }).join('');
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }

  function highlight() {
    Array.from(list.children).forEach((li, i) => li.classList.toggle('is-active', i === activeIndex));
  }

  function select(entry) {
    input.value = entry.name;
    list.hidden = true;
    map.flyTo({ center: [entry.lon, entry.lat], zoom: 15.2, pitch: 52, bearing: 0, essential: true, duration: 1600 });
    state.lastSearchPoint = { lon: entry.lon, lat: entry.lat, name: entry.name };
    const url = new URL(window.location.href);
    url.searchParams.set('city', state.cityKey);
    url.searchParams.set('at', `${entry.lat.toFixed(6)},${entry.lon.toFixed(6)}`);
    window.history.replaceState({}, '', url.toString());
    const nearest = nearestTank(entry.lon, entry.lat);
    if (nearest) {
      openSourceDrawer(nearest.props, { queryName: entry.name, distanceM: nearest.distance, lon: entry.lon, lat: entry.lat });
    } else {
      toast('No tank data available yet.');
    }
    if (state.activeDrawer === 'nearby') populateNearbyDrawer();
  }
  state.selectSearchResult = select; // used by ?at= handling on boot

  function localMatches(query) {
    const lower = query.toLowerCase();
    const starts = [], contains = [];
    for (const entry of (state.gazetteer || [])) {
      const nl = entry.name.toLowerCase();
      if (nl.startsWith(lower)) starts.push(entry);
      else if (nl.includes(lower)) contains.push(entry);
      if (starts.length + contains.length > 80) break;
    }
    return starts.concat(contains).slice(0, 8);
  }

  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(photonTimer);
    if (q.length < 1) { renderMatches([], ''); return; }
    const local = localMatches(q);
    renderMatches(local, q);
    if (q.length >= 3 && local.length < 3) {
      const myToken = ++photonQueryToken;
      const bias = state.cityCenter || [0, 0];
      photonTimer = setTimeout(() => {
        photonSearch(q, bias[0], bias[1]).then((webMatches) => {
          if (myToken !== photonQueryToken || input.value.trim() !== q) return; // stale
          const merged = local.concat(webMatches.filter((w) => !local.some((l) => l.name === w.name))).slice(0, 8);
          renderMatches(merged, q);
        }).catch(() => { /* Photon unavailable — local matches (if any) still stand */ });
      }, 350);
    }
  });

  input.addEventListener('keydown', (e) => {
    if (list.hidden || !currentMatches.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, currentMatches.length - 1); highlight(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); highlight(); }
    else if (e.key === 'Enter') { e.preventDefault(); select(currentMatches[activeIndex >= 0 ? activeIndex : 0]); }
    else if (e.key === 'Escape') { list.hidden = true; }
  });

  list.addEventListener('click', (e) => {
    const li = e.target.closest('li[data-index]');
    if (!li) return;
    select(currentMatches[Number(li.dataset.index)]);
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search')) list.hidden = true;
  });

  // ?at=lat,lon on load: fly straight there and open its nearest-tank card, no typing needed —
  // this is what makes a "Copy link"/shared result reproducible for whoever opens it.
  const atParam = urlParams().get('at');
  if (atParam) {
    const parts = atParam.split(',').map((s) => parseFloat(s.trim()));
    if (parts.length === 2 && parts.every((n) => Number.isFinite(n))) {
      select({ name: 'this location', lon: parts[1], lat: parts[0] });
    }
  }
}

/* -------------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------------- */

function finishLoading() {
  const el = document.getElementById('loading');
  el.classList.add('is-done');
}

/* -------------------------------------------------------------------------
   City picker + downloads — shared by both boot paths
   ------------------------------------------------------------------------- */

function wireCityPicker(citiesIndex) {
  const select = document.getElementById('city-select');
  select.innerHTML = citiesIndex.cities.map((c) =>
    `<option value="${escapeHtml(c.key)}"${c.key === state.cityKey ? ' selected' : ''}>${escapeHtml(c.name)}</option>`).join('');
  select.addEventListener('change', () => {
    const url = new URL(window.location.href);
    url.searchParams.set('city', select.value);
    url.searchParams.delete('at');
    window.location.href = url.toString();
  });

  const entry = citiesIndex.cities.find((c) => c.key === state.cityKey);
  const badge = document.getElementById('city-badge');
  if (entry) {
    badge.textContent = entry.hand_traced ? 'Checked against a hand-traced map' : 'Read by Opus 5.5 · not yet checked by hand';
    badge.classList.toggle('is-verified', !!entry.hand_traced);
    badge.classList.toggle('is-unverified', !entry.hand_traced);
  }
}

function tanksToCSV(fc) {
  const cols = ['id', 'display_name', 'status', 'now_text', 'now_source', 'area_m2', 'runs_found', 'model', 'prompt_version', 'crop'];
  const csvEscape = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
  const rows = [cols.join(',')];
  fc.features.forEach((f) => {
    const p = f.properties;
    const now = p.mod_current_use || (p.now_osm && p.now_osm.name) || '';
    const nowSource = p.mod_current_use ? 'MOD Foundation' : (p.now_osm ? p.now_osm.source : '');
    rows.push([
      p.id, tankDisplayName(p), p.status, now, nowSource, p.area_m2 || '',
      (p.runs_found || []).length, state.cityMode ? 'claude-opus-5-5' : 'claude-opus-5-5 / claude-opus-5',
      state.cityMode ? 'kere-city-v1' : 'kere-tanks-v2', p.crop || '',
    ].map(csvEscape).join(','));
  });
  return rows.join('\n');
}

function downloadBlob(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function wireDownloads() {
  const btn = document.getElementById('download-btn');
  const menu = document.getElementById('download-menu-list');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    btn.setAttribute('aria-expanded', String(willOpen));
  });
  document.addEventListener('click', () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); });
  menu.addEventListener('click', (e) => {
    const fmtBtn = e.target.closest('button[data-format]');
    if (!fmtBtn) return;
    const fc = state.currentTanksGeoJSON;
    if (!fc) { toast('No lake data loaded yet.'); return; }
    if (fmtBtn.dataset.format === 'geojson') {
      downloadBlob(`kere-${state.cityKey}-tanks.geojson`, JSON.stringify(fc, null, 1), 'application/geo+json');
    } else {
      downloadBlob(`kere-${state.cityKey}-tanks.csv`, tanksToCSV(fc), 'text/csv');
    }
  });
}

/* -------------------------------------------------------------------------
   Boot — Bengaluru (the full, scored build) vs any other city (read by
   Opus 5.5 only, no flood layer, no scoreboard, no rain — build-2 rules)
   ------------------------------------------------------------------------- */

async function bootBengaluru() {
  const [sheets, tanks55, tanks5, refused55, refused5, floodPoints, gazetteer, scoreboard, backtest, georef, demoData, rain, narrative] = await Promise.all([
    fetchJSON(`${DATA}sheets.json`),
    fetchJSON(`${DATA}tanks_claude-opus-5-5.geojson`),
    fetchJSON(`${DATA}tanks_claude-opus-5.geojson`),
    fetchJSON(`${DATA}refused_claude-opus-5-5.json`),
    fetchJSON(`${DATA}refused_claude-opus-5.json`),
    fetchJSON(`${DATA}flood_points.geojson`),
    fetchJSON(`${DATA}gazetteer.json`),
    fetchJSON(`${DATA}scoreboard.json`),
    fetchJSON(`${DATA}backtest.json`),
    fetchJSON(`${DATA}plan_georef.json`),
    fetchJSON(`${DATA}demo_data.json`),
    fetchJSON(`${DATA}rain.json`),
    fetchJSON(`${DATA}narrative.json`).catch(() => null),
  ]);

  Object.assign(state, {
    sheets, tanks55, tanks5, refused55, refused5, floodPoints, gazetteer, scoreboard, backtest, georef, rain, narrative,
    cityMode: false, cityKey: 'bengaluru', cityCenter: PRESETS.city.center,
    currentTanksGeoJSON: tanks55,
    tanksWithCentroid: tanks55.features.map((f) => ({ props: f.properties, centroid: polygonCentroid(f.geometry) })),
  });

  applyDemoBanner(demoData);

  const map = await initMap();
  state.map = map;

  setupTerrainAndSky(map);
  const analysis = analyzeStyleLayers(map);
  state.buildingsLayerId = analysis.buildingsLayerId;
  state.symbolLayerIds = analysis.symbolLayerIds;
  if (!analysis.buildingsLayerId) {
    console.warn('No fill-extrusion buildings layer found in the style; the year slider will still fade the sheets and tanks.');
  }

  addSheetLayers(map, sheets, analysis.rasterBeforeId);
  const tankBeforeId = analysis.buildingsLayerId || analysis.rasterBeforeId;
  addTankLayers(map, tanks55, tankBeforeId);
  addFloodLayers(map, floodPoints, tankBeforeId);
  state.rainBeforeId = tankBeforeId; // rain layer added lazily on first toggle; see ensureRainLayer()
  setupLabels(map, tanks55);

  map.on('click', 'tanks-fill', (e) => onTankClick(map, e));
  map.on('mouseenter', 'tanks-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'tanks-fill', () => { map.getCanvas().style.cursor = ''; });

  wireSlider();
  wirePresets(map);
  wireRailAndDrawers();
  wireSearch(map);
  wireDownloads();

  populateFloodDrawer();
  populateScoreboardDrawer();
  populateFenceDrawer();
  populateRainDrawer();
  populateNearbyDrawer();

  applyYearBlend(0);
}

async function bootCity(cityKey, indexEntry) {
  const base = `${DATA}cities/${cityKey}/`;
  const [corners, tanks, refused, meta, gazetteer] = await Promise.all([
    fetchJSON(`${base}corners.json`),
    fetchJSON(`${base}tanks.geojson`),
    fetchJSON(`${base}refused.json`),
    fetchJSON(`${base}meta.json`),
    fetchJSON(`${base}gazetteer.json`).catch(() => []),
  ]);

  Object.assign(state, {
    cityMode: true, cityKey, cityMeta: meta, cityRefused: refused, gazetteer,
    georef: null, floodPoints: { type: 'FeatureCollection', features: [] },
    cityCenter: (indexEntry && indexEntry.city_center_lonlat) || [meta.window_lonlat[0], meta.window_lonlat[1]],
    currentTanksGeoJSON: tanks,
    tanksWithCentroid: tanks.features.map((f) => ({ props: f.properties, centroid: polygonCentroid(f.geometry) })),
  });

  applyDemoBanner(null); // no stand-in path for cities: they only ever ship once real, QA-passed data exists

  const map = await initMap();
  state.map = map;
  map.jumpTo({ center: state.cityCenter, zoom: (CITY_PRESETS[cityKey] || {}).zoom || 12.5,
               pitch: (CITY_PRESETS[cityKey] || {}).pitch || 45, bearing: 0 });

  setupTerrainAndSky(map);
  const analysis = analyzeStyleLayers(map);
  state.buildingsLayerId = analysis.buildingsLayerId;
  state.symbolLayerIds = analysis.symbolLayerIds;

  // Reuses the 'plan' sheet-layer id (see addSheetLayers) so the existing year-slider logic in
  // applyYearBlend() needs no city-mode branch of its own — one sheet layer, same id, same fade.
  addSheetLayers(map, { plan: { image: `cities/${cityKey}/sheet.jpg`, corners: corners.corners } }, analysis.rasterBeforeId);
  const tankBeforeId = analysis.buildingsLayerId || analysis.rasterBeforeId;
  addTankLayers(map, tanks, tankBeforeId);
  setupLabels(map, tanks);

  map.on('click', 'tanks-fill', (e) => onTankClick(map, e));
  map.on('mouseenter', 'tanks-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', 'tanks-fill', () => { map.getCanvas().style.cursor = ''; });

  wireSlider();
  document.querySelector('.presets').hidden = true; // Bengaluru-specific camera presets
  wireRailAndDrawers();
  wireSearch(map);
  wireDownloads();

  populateFenceDrawer();
  populateNearbyDrawer();

  applyYearBlend(0);
}

/* -------------------------------------------------------------------------
   Demo mode (?demo=1) — a scripted, rehearsable 2-minute flow. Fully inert
   unless the URL param is present, so the deployed link everyone else opens
   never runs any of this. Digit keys jump steps; typing in the search box is
   never intercepted (guarded below).
   ------------------------------------------------------------------------- */

const SHULE_TANK_ID = 'claude-opus-5-5_plan_011'; // "Shūle Tank" -- the Ashok Nagar stadium story
const CITY_DEMO_TANK = { chennai: 'chennai_000' }; // "Pulal Tank", surviving, named -- strongest 2nd-city beat

function tweenSlider(target, ms) {
  return new Promise((resolve) => {
    const slider = document.getElementById('year-slider');
    const start = parseFloat(slider.value);
    const t0 = performance.now();
    function step(now) {
      // Clamp p to [0,1]: requestAnimationFrame's timestamp can predate the performance.now()
      // captured just before scheduling it by a fraction of a ms, which without this clamp
      // makes p (and then eased, and then v) briefly negative on the first frame -- enough for
      // MapLibre's paint-property validator to reject an out-of-[0,1]-range opacity and log an
      // error on every single reveal.
      const p = Math.min(1, Math.max(0, (now - t0) / ms));
      const eased = 1 - (1 - p) * (1 - p); // ease-out
      const v = Math.min(1, Math.max(0, start + (target - start) * eased));
      slider.value = String(v);
      applyYearBlend(v);
      if (p < 1) requestAnimationFrame(step); else resolve();
    }
    requestAnimationFrame(step);
  });
}

function demoFindTank(id) {
  const entry = (state.tanksWithCentroid || []).find((t) => t.props.id === id);
  return entry || (state.tanksWithCentroid || [])[0] || null;
}

function showEndCard() {
  closeDrawer();
  const card = document.getElementById('end-card');
  const urlEl = document.getElementById('end-card-url');
  if (urlEl) urlEl.textContent = (state.deployUrl || window.location.origin + window.location.pathname);
  card.hidden = false;
  requestAnimationFrame(() => card.classList.add('is-visible'));
}

function hideEndCard() {
  const card = document.getElementById('end-card');
  card.classList.remove('is-visible');
  setTimeout(() => { card.hidden = true; }, 260);
}

const DEMO_STEPS_BENGALURU = [
  // 1: opening shot
  () => {
    closeDrawer();
    hideEndCard();
    document.getElementById('year-slider').value = '0';
    applyYearBlend(0);
    state.map.flyTo({ ...PRESETS.stadium, essential: true, duration: 1400 });
  },
  // 2: the reveal — 1954 sheet fades in, Shūle Tank fills in, source card opens
  async () => {
    closeDrawer();
    await tweenSlider(1, 2600);
    const t = demoFindTank(SHULE_TANK_ID);
    if (t) openSourceDrawer(t.props);
  },
  // 3: pull back over the city, flood points on
  () => {
    closeDrawer();
    state.map.flyTo({ ...PRESETS.city, essential: true, duration: 1800 });
    setFloodVisible(true);
    const input = document.getElementById('flood-toggle-input');
    if (input) input.checked = true;
  },
  // 4: hand off to search — prefilled, not auto-submitted
  () => {
    closeDrawer();
    const input = document.getElementById('search-input');
    input.value = 'HSR Layout';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  },
  // 5: scoreboard, with the chart and the narrative line
  () => { openDrawer('scoreboard'); },
  // 6: hand off to a second city — proves this generalizes beyond Bengaluru
  () => { window.location.href = '?city=chennai&demo=1'; },
];

const DEMO_STEPS_CITY = [
  // 1: the named, surviving tank in the second city
  () => {
    closeDrawer();
    const id = CITY_DEMO_TANK[state.cityKey];
    const t = id ? demoFindTank(id) : (state.tanksWithCentroid || [])[0];
    if (!t) return;
    state.map.flyTo({ center: t.centroid, zoom: 15.5, pitch: 52, essential: true, duration: 1600 });
    openSourceDrawer(t.props);
  },
  // 2: the fence — refusals shown, not hidden
  () => { openDrawer('fence'); },
  // 3: end card
  () => { showEndCard(); },
];

function wireDemoMode() {
  if (!state.demoMode) return;
  const steps = state.cityMode ? DEMO_STEPS_CITY : DEMO_STEPS_BENGALURU;
  document.addEventListener('keydown', (e) => {
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
    const n = parseInt(e.key, 10);
    if (!Number.isNaN(n) && n >= 1 && n <= steps.length) steps[n - 1]();
  });
  document.getElementById('end-card-close').addEventListener('click', hideEndCard);
  if (state.cityMode) steps[0](); // auto-resume the flow on the far side of the city-switch reload
}

async function main() {
  try {
    state.demoMode = urlParams().get('demo') === '1';
    const citiesIndex = await fetchJSON(`${DATA}cities.json`).catch(() => ({ cities: [{ key: 'bengaluru', name: 'Bengaluru', hand_traced: true }] }));
    const cityKey = currentCityKey(citiesIndex);
    const entry = citiesIndex.cities.find((c) => c.key === cityKey);
    state.cityKey = cityKey;

    wireCityPicker(citiesIndex);
    if (cityKey === 'bengaluru') {
      await bootBengaluru();
    } else {
      document.getElementById('intro-kicker').textContent = `Kere — 1954 tanks over 2026 ${entry ? entry.name : cityKey}`;
      document.getElementById('intro-line').innerHTML = `The lakes ${escapeHtml(entry ? entry.name : cityKey)} forgot, read off a 1954 map by <em>Claude&nbsp;Opus&nbsp;5.5</em>.`;
      document.title = `Kere — the lakes ${entry ? entry.name : cityKey} forgot`;
      await bootCity(cityKey, entry);
    }
    wireDemoMode();
    finishLoading();
  } catch (err) {
    console.error('Kere failed to start', err);
    toast('Something failed to load — check the console.');
    const p = document.querySelector('.loading p');
    if (p) p.textContent = 'Something went wrong loading the map. Check the console.';
  }
}

main();
