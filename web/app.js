/* ParcelWatch public map. Vanilla JS + MapLibre GL. Public data is hex aggregates only. */
(function () {
  "use strict";

  var PC_TILEJSON = "https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json" +
    "?collection=naip&assets=image&asset_bidx=image%7C1%2C2%2C3&item=";
  var RAMP = ["#FEF0D9", "#FDCC8A", "#FC8D59", "#E34A33", "#B30000"];
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Math.round(n).toLocaleString("en-US"); };

  /* ---------- theme: system -> light -> dark ---------- */
  var THEMES = ["system", "light", "dark"];
  function applyTheme(t) {
    if (t === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", t);
    $("theme").setAttribute("aria-label", "Theme: " + t);
  }
  var theme = "system";
  try { theme = localStorage.getItem("pw-theme") || "system"; } catch (e) { /* storage blocked */ }
  applyTheme(theme);
  $("theme").addEventListener("click", function () {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % 3];
    applyTheme(theme);
    try { localStorage.setItem("pw-theme", theme); } catch (e) { /* ignore */ }
  });

  /* ---------- stats panel ---------- */
  function renderStats(s) {
    $("hero").textContent = fmt(s.n_flagged);
    $("n-new").textContent = fmt(s.n_new);
    $("n-expanded").textContent = fmt(s.n_expanded);
    $("n-demolished").textContent = fmt(s.n_demolished);
    $("study-label").textContent = "Wake County, NC · " + s.before_year + " → " + s.after_year;
    $("year-left").textContent = s.before_year;
    $("year-right").textContent = s.after_year;
    if (s.est_yearly_tax_usd_adjusted !== null && s.precision !== null) {
      var pct = Math.round(s.precision * 100);
      $("money").textContent = "$" + fmt(s.est_yearly_tax_usd_adjusted) + " / yr";
      var who = s.validation_status === "owner" ? "hand review" : "provisional review (owner check pending)";
      $("money-note").innerHTML = "adjusted for " + pct + "% precision " +
        '<span class="info"><button type="button" aria-label="About precision">ⓘ</button>' +
        '<span class="tip" role="tooltip">' + s.validation_tp + " of " + s.validation_n_flagged +
        " flags confirmed by " + who + ". Value per sq ft $" + s.value_per_sqft.toFixed(0) +
        ", tax year " + s.tax_year + " rates, fire tax excluded.</span></span>";
      if (s.validation_status !== "owner") $("money-note").classList.add("warn");
    } else {
      $("money").textContent = "Pending validation";
      $("money-note").textContent = "Shown once 200 parcels are hand-checked and precision is measured.";
    }
    var b = s.hex_breaks || [];
    $("ramp").innerHTML = RAMP.slice(0, Math.max(1, b.length + 1))
      .map(function (c) { return '<span style="background:' + c + '"></span>'; }).join("");
  }

  /* ---------- maps ---------- */
  function style() {
    return { version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#E3E6EA" } }] };
  }
  function makeMap(id) {
    return new maplibregl.Map({
      container: id, style: style(), attributionControl: false, dragRotate: false,
      pitchWithRotate: false, touchPitch: false, maxPitch: 0, fadeDuration: reduceMotion ? 0 : 300
    });
  }
  var before = makeMap("map-before");
  var after = makeMap("map-after");
  before.touchZoomRotate.disableRotation();
  after.touchZoomRotate.disableRotation();

  /* keep cameras in sync */
  var syncing = false;
  function sync(src, dst) {
    src.on("move", function () {
      if (syncing) return;
      syncing = true;
      dst.jumpTo({ center: src.getCenter(), zoom: src.getZoom(), bearing: 0, pitch: 0 });
      syncing = false;
    });
  }
  sync(before, after);
  sync(after, before);

  function hexColor(breaks) {
    var expr = ["step", ["get", "n_flagged"], RAMP[0]];
    breaks.forEach(function (v, i) { expr.push(v + 0.0001, RAMP[Math.min(i + 1, 4)]); });
    return expr;
  }

  function addImagery(map, items, prefix) {
    items.forEach(function (item, i) {
      map.addSource(prefix + i, { type: "raster", url: PC_TILEJSON + item, tileSize: 256, maxzoom: 19 });
      map.addLayer({ id: prefix + i, type: "raster", source: prefix + i });
    });
  }

  function addHexes(map, breaks) {
    map.addSource("hex", { type: "geojson", data: "data/changes_h3.geojson" });
    map.addLayer({
      id: "hex-fill", type: "fill", source: "hex", filter: [">", ["get", "n_flagged"], 0],
      paint: { "fill-color": hexColor(breaks), "fill-opacity": 0.65 }
    });
    map.addLayer({
      id: "hex-line", type: "line", source: "hex", filter: [">", ["get", "n_flagged"], 0],
      paint: { "line-color": "#FFFFFF", "line-width": 0.5 }
    });
    map.on("click", "hex-fill", function (e) {
      var p = e.features[0].properties;
      new maplibregl.Popup({ closeButton: true, maxWidth: "260px" })
        .setLngLat(e.lngLat)
        .setHTML('<div class="popup"><dl><dt>Parcels</dt><dd>' + fmt(p.n_parcels) +
          "</dd><dt>Changed</dt><dd>" + fmt(p.n_changed) + "</dd><dt>Unpermitted change</dt><dd>" +
          fmt(p.n_flagged) + "</dd><dt>Added sq ft</dt><dd>" + fmt(p.added_sqft) + "</dd></dl></div>")
        .addTo(map);
    });
    map.on("mouseenter", "hex-fill", function () { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", "hex-fill", function () { map.getCanvas().style.cursor = ""; });
  }

  var bounds;
  function fit(animate) {
    var opts = { padding: 24, animate: animate && !reduceMotion, duration: 400 };
    before.fitBounds(bounds, opts);
  }

  function setLayer(map, prefix, on) {
    map.getStyle().layers.forEach(function (l) {
      if (l.id.indexOf(prefix) === 0) map.setLayoutProperty(l.id, "visibility", on ? "visible" : "none");
    });
  }

  fetch("data/stats.json").then(function (r) {
    if (!r.ok) throw new Error("stats " + r.status);
    return r.json();
  }).then(function (s) {
    renderStats(s);
    var bb = s.bbox;
    bounds = [[bb[0], bb[1]], [bb[2], bb[3]]];
    before.setMaxBounds([[bb[0] - 0.05, bb[1] - 0.05], [bb[2] + 0.05, bb[3] + 0.05]]);
    after.setMaxBounds([[bb[0] - 0.05, bb[1] - 0.05], [bb[2] + 0.05, bb[3] + 0.05]]);
    fit(false);
    var ready = 0;
    function onLoad(map, items, prefix) {
      addImagery(map, items, prefix);
      addHexes(map, s.hex_breaks || []);
      map.addSource("box", { type: "geojson", data: { type: "Feature", geometry: { type: "Polygon",
        coordinates: [[[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]], [bb[0], bb[1]]]] } } });
      map.addLayer({ id: "box", type: "line", source: "box", paint: { "line-color": "#0F172A", "line-width": 1.5, "line-dasharray": [2, 2] } });
      if (++ready === 2) $("loading").remove();
    }
    if (before.loaded()) onLoad(before, s.naip_items.before, "naip-b"); else before.on("load", function () { onLoad(before, s.naip_items.before, "naip-b"); });
    if (after.loaded()) onLoad(after, s.naip_items.after, "naip-a"); else after.on("load", function () { onLoad(after, s.naip_items.after, "naip-a"); });
  }).catch(function () { $("error").classList.add("show"); });

  var tileErrors = 0;
  [before, after].forEach(function (m) {
    m.on("error", function () { if (++tileErrors > 40) $("error").classList.add("show"); });
  });

  /* ---------- layer toggles ---------- */
  document.querySelectorAll(".pill[data-layer]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var on = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(on));
      var which = btn.dataset.layer;
      if (which === "hex") { setLayer(before, "hex", on); setLayer(after, "hex", on); }
      if (which === "before") setLayer(before, "naip-b", on);
      if (which === "after") setLayer(after, "naip-a", on);
    });
  });

  /* ---------- swipe ---------- */
  var wrap = $("map-wrap"), handle = $("handle"), divider = $("divider"), pos = 50;
  function setSwipe(pct) {
    pos = Math.max(0, Math.min(100, pct));
    $("map-after").style.clipPath = "inset(0 0 0 " + pos + "%)";
    divider.style.left = pos + "%";
    handle.style.left = pos + "%";
    handle.setAttribute("aria-valuenow", String(Math.round(pos)));
  }
  var dragging = false;
  handle.addEventListener("pointerdown", function (e) { dragging = true; handle.setPointerCapture(e.pointerId); });
  handle.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    var r = wrap.getBoundingClientRect();
    setSwipe(((e.clientX - r.left) / r.width) * 100);
  });
  handle.addEventListener("pointerup", function () { dragging = false; });
  handle.addEventListener("keydown", function (e) {
    var k = { ArrowLeft: -5, ArrowRight: 5 }[e.key];
    if (k) { setSwipe(pos + k); e.preventDefault(); }
    if (e.key === "Home") { setSwipe(0); e.preventDefault(); }
    if (e.key === "End") { setSwipe(100); e.preventDefault(); }
  });
  setSwipe(50);

  /* ---------- zoom controls ---------- */
  $("zoom-in").addEventListener("click", function () { before.zoomIn({ animate: !reduceMotion }); });
  $("zoom-out").addEventListener("click", function () { before.zoomOut({ animate: !reduceMotion }); });
  $("zoom-fit").addEventListener("click", function () { if (bounds) fit(true); });

  /* ---------- legend (collapsible on mobile) ---------- */
  $("legend-toggle").addEventListener("click", function () {
    var c = $("legend").classList.toggle("collapsed");
    $("legend-toggle").setAttribute("aria-expanded", String(!c));
  });
  if (window.matchMedia("(max-width: 639px)").matches) {
    $("legend").classList.add("collapsed");
    $("legend-toggle").setAttribute("aria-expanded", "false");
  }

  /* ---------- method drawer ---------- */
  var drawer = $("drawer"), lastFocus = null;
  function openDrawer() {
    lastFocus = document.activeElement;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    $("close-method").focus();
  }
  function closeDrawer() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (lastFocus) lastFocus.focus();
  }
  $("open-method").addEventListener("click", openDrawer);
  $("close-method").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      if (drawer.classList.contains("open")) closeDrawer();
      document.querySelectorAll(".maplibregl-popup").forEach(function (p) { p.remove(); });
    }
  });

  /* ---------- mobile bottom sheet: peek 120 px, half, full ---------- */
  var panel = $("panel"), sheet = $("sheet-handle");
  function snaps() { var h = window.innerHeight - 56; return [120, Math.round(h * 0.5), h]; }
  var snapIdx = 0;
  function setSheet(i) {
    snapIdx = i;
    panel.style.setProperty("--sheet-h", snaps()[i] + "px");
    sheet.setAttribute("aria-label", i === 2 ? "Collapse statistics" : "Expand statistics");
  }
  var startY = null, startH = 0;
  sheet.addEventListener("pointerdown", function (e) { startY = e.clientY; startH = panel.offsetHeight; sheet.setPointerCapture(e.pointerId); });
  sheet.addEventListener("pointermove", function (e) {
    if (startY === null) return;
    panel.style.setProperty("--sheet-h", Math.max(120, startH + (startY - e.clientY)) + "px");
  });
  sheet.addEventListener("pointerup", function (e) {
    if (startY === null) return;
    var moved = Math.abs(startY - e.clientY), h = panel.offsetHeight, s = snaps();
    startY = null;
    if (moved < 6) { setSheet((snapIdx + 1) % 3); return; }
    var best = 0;
    s.forEach(function (v, i) { if (Math.abs(v - h) < Math.abs(s[best] - h)) best = i; });
    setSheet(best);
  });
  setSheet(0);
})();
