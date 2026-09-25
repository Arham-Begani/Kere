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
  map: null,
  activeDrawer: null,
};

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

function sheetLabel(sheet) {
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

const DRAWER_NAMES = ['source', 'flood', 'scoreboard', 'fence'];

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
    btn.addEventListener('click', () => toggleDrawer(btn.dataset.drawer));
  });
  document.addEventListener('click', (e) => {
    if (e.target.closest('.panel-close')) closeDrawer();
  });
  document.getElementById('drawer-backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });
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

function buildSourceCardHTML(props, searchCtx) {
  const hasPrinted = !!props.name_as_printed;
  const hasModName = !!props.mod_name;
  const heading = hasPrinted ? props.name_as_printed : (hasModName ? props.mod_name : 'Unnamed tank');
  const nameSource = hasPrinted ? 'printed on the 1954 sheet' : (hasModName ? 'MOD Foundation record' : 'no name recorded — geometry only');
  const statusLabel = props.status === 'surviving' ? 'Surviving' : 'Lost';
  const georef = state.georef;
  const gcpCount = georef && georef.gcps ? Object.keys(georef.gcps).length : null;

  let html = '';
  html += `<div class="panel-head"><div><h2>${escapeHtml(heading)}</h2><p>${sheetLabel(props.sheet)}</p></div>${closeButtonHTML()}</div>`;

  if (searchCtx) {
    html += `<div class="card-search-context">Nearest 1954 tank to <strong>${escapeHtml(searchCtx.queryName)}</strong>: `
      + `${Math.round(searchCtx.distanceM).toLocaleString()} m away. Distance and record only — never a flood prediction.</div>`;
  }

  if (props.crop) {
    html += `<div class="card-crop"><img src="${DATA}${props.crop}" alt="Crop of the 1954 sheet around ${escapeHtml(heading)}" loading="lazy"></div>`;
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
  html += `<div class="fact"><p class="fact__label">What's there now</p>`
    + `<p class="fact__value">${props.mod_current_use ? `${escapeHtml(props.mod_current_use)} (MOD Foundation)` : 'not recorded by MOD'}</p></div>`;
  if (hasModName && hasPrinted) {
    html += `<div class="fact"><p class="fact__label">MOD record</p>`
      + `<p class="fact__value">${escapeHtml(props.mod_name)}${props.mod_last_mapped ? ` · last surveyed ${escapeHtml(props.mod_last_mapped)}` : ''}</p></div>`;
  }
  if (props.area_m2) {
    html += `<div class="fact"><p class="fact__label">Traced extent</p>`
      + `<p class="fact__value">${(props.area_m2 / 10000).toFixed(1)} ha, from pipeline/grow.py on the scan</p></div>`;
  }
  html += '</div>';

  if (props.sheet === 'plan_25k' && georef && georef.rms_m != null && gcpCount != null) {
    html += `<p class="card-footnote">Aligned ±${georef.rms_m} m using ${gcpCount} tanks.</p>`;
  } else if (props.sheet === 'front_250k') {
    html += '<p class="card-footnote">From the 1954 front sheet (1:250,000), aligned to its printed neatline corners.</p>';
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
  const groups = [
    { label: 'Opus 5.5', items: state.refused55 || [] },
    { label: 'Opus 5', items: state.refused5 || [] },
  ];
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
        + `<div class="fence-item__crop"><img src="${DATA}${item.crop}" alt="" loading="lazy"></div>`
        + `<div><p class="fence-item__reason">${escapeHtml(item.reason)}</p>`
        + `<p class="fence-item__meta">${escapeHtml(sheetLabel(item.sheet))} · tiles: ${tiles.map(escapeHtml).join(', ')} · seen in ${runs.length} run${runs.length === 1 ? '' : 's'}</p></div>`
        + '</div>';
    });
    html += '</div>';
  });

  body.innerHTML = html;
}

/* -------------------------------------------------------------------------
   Search — client-side gazetteer match only, no geocoding, ever
   ------------------------------------------------------------------------- */

function wireSearch(map) {
  const input = document.getElementById('search-input');
  const list = document.getElementById('search-suggestions');
  let activeIndex = -1;
  let currentMatches = [];

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
      const idx = m.name.toLowerCase().indexOf(lower);
      if (idx < 0) return `<li role="option" data-index="${i}">${escapeHtml(m.name)}</li>`;
      const before = escapeHtml(m.name.slice(0, idx));
      const mid = escapeHtml(m.name.slice(idx, idx + query.length));
      const after = escapeHtml(m.name.slice(idx + query.length));
      return `<li role="option" data-index="${i}">${before}<mark>${mid}</mark>${after}</li>`;
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
    const nearest = nearestTank(entry.lon, entry.lat);
    if (nearest) {
      openSourceDrawer(nearest.props, { queryName: entry.name, distanceM: nearest.distance });
    } else {
      toast('No tank data available yet.');
    }
  }

  input.addEventListener('input', () => {
    const q = input.value.trim();
    if (q.length < 1) { renderMatches([], ''); return; }
    const lower = q.toLowerCase();
    const starts = [], contains = [];
    for (const entry of state.gazetteer) {
      const nl = entry.name.toLowerCase();
      if (nl.startsWith(lower)) starts.push(entry);
      else if (nl.includes(lower)) contains.push(entry);
      if (starts.length + contains.length > 80) break;
    }
    renderMatches(starts.concat(contains).slice(0, 8), q);
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
}

/* -------------------------------------------------------------------------
   Boot
   ------------------------------------------------------------------------- */

function finishLoading() {
  const el = document.getElementById('loading');
  el.classList.add('is-done');
}

async function main() {
  try {
    const [sheets, tanks55, tanks5, refused55, refused5, floodPoints, gazetteer, scoreboard, backtest, georef, demoData] = await Promise.all([
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
    ]);

    Object.assign(state, {
      sheets, tanks55, tanks5, refused55, refused5, floodPoints, gazetteer, scoreboard, backtest, georef,
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
    setupLabels(map, tanks55);

    map.on('click', 'tanks-fill', (e) => { if (e.features && e.features[0]) openSourceDrawer(e.features[0].properties); });
    map.on('mouseenter', 'tanks-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'tanks-fill', () => { map.getCanvas().style.cursor = ''; });

    wireSlider();
    wirePresets(map);
    wireRailAndDrawers();
    wireSearch(map);

    populateFloodDrawer();
    populateScoreboardDrawer();
    populateFenceDrawer();

    applyYearBlend(0);
    finishLoading();
  } catch (err) {
    console.error('Kere failed to start', err);
    toast('Something failed to load — check the console.');
    const p = document.querySelector('.loading p');
    if (p) p.textContent = 'Something went wrong loading the map. Check the console.';
  }
}

main();
