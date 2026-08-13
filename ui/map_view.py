"""
Embedded Leaflet map inside a QWebEngineView. We render Leaflet via a local
HTML string (loaded from CDN scripts) and push route geometry into it with
runJavaScript() rather than reloading the page each time — keeps map state
(zoom/pan) stable between route requests.
"""
import json
from typing import Optional

from core.surfaces import surface_styles_for_ui
from PyQt5.QtCore import QObject, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWebEngineWidgets import QWebEngineView

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <style>
    html, body, #map { height: 100%; margin: 0; padding: 0; cursor: crosshair !important; }
    .leaflet-container, .leaflet-grab, .leaflet-interactive, .leaflet-dragging .leaflet-grab { cursor: crosshair !important; }
    body.dark-theme #map, body.dark-theme .leaflet-container { background: #334155; }
    body.light-theme #map, body.light-theme .leaflet-container { background: #f4f6f8; }

    /* Brightened medium-grey dark tile style */
    .dark-grey-tiles {
      filter: brightness(1.7) contrast(0.8) saturate(0.85);
    }

    .route-arrow {
      background: transparent;
      border: 0;
    }
    .route-arrow-inner {
      width: 0;
      height: 0;
      border-top: 6px solid transparent;
      border-bottom: 6px solid transparent;
      border-left: 14px solid currentColor;
      filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.45));
      transform-origin: 40% 50%;
    }
    .route-point {
      align-items: center;
      border: 2px solid #fff;
      border-radius: 999px;
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.4);
      color: #fff;
      display: flex;
      font: 700 11px/1 Arial, sans-serif;
      height: 24px;
      justify-content: center;
      width: 24px;
    }
    .route-point.start {
      outline: 2px solid rgba(255, 255, 255, 0.65);
    }
    .route-point.loop {
      font-size: 9px;
      width: 34px;
    }
    .km-marker {
      align-items: center;
      border: 2px solid currentColor;
      border-radius: 999px;
      display: flex;
      font: 700 10px/1 Arial, sans-serif;
      height: 22px;
      justify-content: center;
      min-width: 22px;
      padding: 0 4px;
    }
    .surface-legend {
      border-radius: 8px;
      font: 700 11px/1.3 Arial, sans-serif;
      padding: 8px 10px;
    }
    .surface-legend-row {
      align-items: center;
      display: flex;
      gap: 6px;
      margin-top: 5px;
    }
    .surface-legend-swatch {
      border-radius: 999px;
      display: inline-block;
      height: 9px;
      width: 18px;
    }
    .edit-help {
      border-radius: 8px;
      font: 700 12px/1.35 Arial, sans-serif;
      padding: 9px 11px;
    }
    .edit-handle {
      background: #f97316;
      border: 3px solid #fff;
      border-radius: 999px;
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.4);
      height: 18px;
      width: 18px;
    }
    .hover-point-marker {
      background: #3b82f6;
      border: 2px solid #ffffff;
      border-radius: 999px;
      box-shadow: 0 0 10px rgba(59, 130, 246, 0.9), 0 1px 4px rgba(0, 0, 0, 0.5);
      width: 14px;
      height: 14px;
    }
    .route-play-control {
      background: #ffffff;
      border-radius: 4px;
      border: 2px solid rgba(0, 0, 0, 0.2);
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.4);
      cursor: pointer;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-top: 10px !important;
      transition: background 0.2s, border-color 0.2s;
    }
    .route-play-control:hover {
      background: #f8fafc;
      border-color: rgba(0, 0, 0, 0.35);
    }
    .route-play-btn {
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 100%;
      height: 100%;
    }
    body.dark-theme .route-play-control {
      background: #1e293b;
      border: 1px solid rgba(255, 255, 255, 0.2);
    }
    body.dark-theme .route-play-control:hover {
      background: #334155;
    }
    body.dark-theme .route-play-btn svg {
      fill: #f8fafc;
    }
    .anim-rider-dot {
      background: #22c55e;
      border: 3px solid #ffffff;
      border-radius: 999px;
      box-shadow: 0 0 12px rgba(34, 197, 94, 0.9), 0 2px 6px rgba(0, 0, 0, 0.5);
      width: 16px;
      height: 16px;
    }
    .strava-chevron-marker {
      background: transparent;
      border: none;
      display: flex;
      align-items: center;
      justify-content: center;
      filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.65));
    }

    /* Dark theme markers & overlays */
    body.dark-theme .km-marker {
      background: #334155; color: #f8fafc; border-color: #64748b; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.6);
    }
    body.dark-theme .surface-legend {
      background: rgba(30, 41, 59, 0.92); border: 1px solid rgba(255, 255, 255, 0.15); box-shadow: 0 1px 6px rgba(0, 0, 0, 0.5); color: #f8fafc;
    }
    body.dark-theme .edit-help {
      background: rgba(30, 41, 59, 0.92); border: 1px solid rgba(255, 255, 255, 0.15); color: #f8fafc;
    }
    body.dark-theme .route-point.finish {
      background: #f8fafc; color: #0f172a;
    }

    /* Light theme markers & overlays */
    body.light-theme .km-marker {
      background: #fff; color: #0f172a; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
    }
    body.light-theme .surface-legend {
      background: rgba(255, 255, 255, 0.92); border: 1px solid rgba(15, 23, 42, 0.14); box-shadow: 0 1px 6px rgba(0, 0, 0, 0.16); color: #0f172a;
    }
    body.light-theme .edit-help {
      background: rgba(15, 23, 42, 0.88); color: #fff;
    }
    /* Tile Pane Cross-Fade Transition */
    .leaflet-tile-pane {
      transition: opacity 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* Leaflet layer control animations & styling */
    .leaflet-control-layers {
      border-radius: 12px !important;
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 13px;
      font-weight: 600;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25) !important;
      transition: all 0.28s cubic-bezier(0.16, 1, 0.3, 1) !important;
      overflow: hidden;
    }
    .leaflet-control-layers-toggle {
      transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.28s ease, background-color 0.28s ease !important;
      border-radius: 10px !important;
    }
    .leaflet-control-layers-toggle:hover {
      transform: scale(1.12) rotate(-5deg) !important;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
    }
    .leaflet-control-layers-toggle:active {
      transform: scale(0.92) rotate(3deg) !important;
    }
    .leaflet-control-layers-expanded {
      animation: layerMenuExpand 0.28s cubic-bezier(0.16, 1, 0.3, 1) forwards;
      padding: 10px 14px !important;
    }
    .leaflet-control-layers-base label {
      display: flex !important;
      align-items: center !important;
      gap: 6px;
      padding: 5px 8px !important;
      border-radius: 6px !important;
      margin: 2px 0 !important;
      cursor: pointer !important;
      transition: background-color 0.2s ease, transform 0.2s cubic-bezier(0.16, 1, 0.3, 1) !important;
    }
    .leaflet-control-layers-base label:hover {
      transform: translateX(4px) !important;
    }

    /* Spin / Pulse animation on selection */
    .layer-icon-spin {
      animation: layerIconPulse 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
    }

    @keyframes layerMenuExpand {
      0% {
        opacity: 0;
        transform: scale(0.85) translateY(-8px);
      }
      100% {
        opacity: 1;
        transform: scale(1) translateY(0);
      }
    }

    @keyframes layerIconPulse {
      0% {
        transform: scale(1) rotate(0deg);
      }
      35% {
        transform: scale(1.28) rotate(-18deg);
      }
      75% {
        transform: scale(1.05) rotate(372deg);
      }
      100% {
        transform: scale(1) rotate(360deg);
      }
    }

    body.dark-theme .leaflet-control-layers {
      background: rgba(15, 23, 42, 0.92) !important;
      border: 1px solid rgba(255, 255, 255, 0.15) !important;
      color: #f8fafc !important;
    }
    body.dark-theme .leaflet-control-layers-base label:hover {
      background: rgba(255, 255, 255, 0.1) !important;
    }
    body.light-theme .leaflet-control-layers {
      background: rgba(255, 255, 255, 0.92) !important;
      border: 1px solid rgba(15, 23, 42, 0.14) !important;
      color: #0f172a !important;
    }
    body.light-theme .leaflet-control-layers-base label:hover {
      background: rgba(15, 23, 42, 0.06) !important;
    }

    /* Context menu popup styling */
    .map-context-menu { display: flex; flex-direction: column; gap: 6px; padding: 4px 2px; }
    .ctx-menu-btn {
      border: none;
      background: #2563eb;
      color: #ffffff;
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 13px;
      font-weight: 600;
      padding: 8px 14px;
      border-radius: 6px;
      cursor: pointer;
      text-align: left;
      transition: background 0.15s ease, transform 0.1s ease;
    }
    .ctx-menu-btn:hover { background: #1d4ed8; }
    .ctx-menu-btn.finish { background: #dc2626; }
    .ctx-menu-btn.finish:hover { background: #b91c1c; }
    .ctx-menu-btn.fuse { background: #059669; }
    .ctx-menu-btn.fuse:hover { background: #047857; }
    .ctx-menu-btn.remove { background: #64748b; }
    .ctx-menu-btn.remove:hover { background: #475569; }
    .custom-ctx-popup .leaflet-popup-content-wrapper { background: #1e293b; color: #f8fafc; border-radius: 10px; padding: 6px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.4); }
    .custom-ctx-popup .leaflet-popup-tip { background: #1e293b; }
  </style>
</head>
<body class="dark-theme">
  <div id="map"></div>
  <script>
    var map = L.map('map').setView([59.9139, 10.7522], 13); // default: Oslo

    var streetLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    });

    var darkGreyLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20,
      className: 'dark-grey-tiles'
    });

    var satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 19
    });

    var topoLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), and the GIS User Community',
      maxZoom: 19
    });

    var baseMaps = {
      "🗺️ Street": streetLayer,
      "🛰️ Satellite": satelliteLayer,
      "🏔️ Topographic": topoLayer
    };

    var currentTileLayer = darkGreyLayer;
    currentTileLayer.addTo(map);

    L.control.layers(baseMaps, null, { position: 'topright' }).addTo(map);

    var routePlayControl = L.control({ position: 'topright' });
    routePlayControl.onAdd = function(map) {
      var div = L.DomUtil.create('div', 'leaflet-control-layers leaflet-control route-play-control');
      div.title = "Play / Pause Route Animation";
      div.innerHTML = '<button class="route-play-btn" id="routePlayBtn" aria-label="Play route animation">' +
                      '<svg class="play-icon" viewBox="0 0 24 24" width="16" height="16" fill="#1e293b"><polygon points="6,4 20,12 6,20"/></svg>' +
                      '<svg class="pause-icon" viewBox="0 0 24 24" width="16" height="16" fill="#1e293b" style="display:none;"><rect x="5" y="4" width="4" height="16"/><rect x="15" y="4" width="4" height="16"/></svg>' +
                      '</button>';
      L.DomEvent.disableClickPropagation(div);
      div.onclick = function(e) {
        e.preventDefault();
        toggleRoutePlayback();
      };
      return div;
    };
    routePlayControl.addTo(map);

    map.on('baselayerchange', function(e) {
      var icon = document.querySelector('.leaflet-control-layers-toggle');
      if (icon) {
        icon.classList.remove('layer-icon-spin');
        void icon.offsetWidth;
        icon.classList.add('layer-icon-spin');
      }
      var pane = map.getPane('tilePane');
      if (pane) {
        pane.style.opacity = '0.3';
        setTimeout(function() {
          pane.style.opacity = '1';
        }, 60);
      }
    });

    function setTheme(theme) {
      if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
      }
      currentTileLayer = (theme === 'dark') ? darkGreyLayer : streetLayer;
      currentTileLayer.addTo(map);
      document.body.className = (theme === 'dark') ? 'dark-theme' : 'light-theme';
    }
    setTheme('dark');

    var routeLayers = [];
    var editLayers = [];
    var surfaceLegend = null;
    var surfaceColors = {};
    var editableRoute = null;
    var editBridge = null;
    var editMode = false;
    var editHelp = null;
    var currentViaPoints = [];
    // These are shared by route rendering and the independent playback
    // control. Keeping them at map scope is essential: the control's click
    // handler runs outside drawRoutes().
    var primaryCoords = null;
    var primaryColor = null;
    var primarySurfaceSegments = null;
    var createMode = false;
    var animTimeoutId = null;
    var animFrameId = null;
    var isPlayingRoute = false;
    var playbackProgressIndex = 0;
    var playbackAnimFrame = null;
    var animRiderMarker = null;

    function initBridge() {
      if (typeof qt !== 'undefined' && qt.webChannelTransport) {
        new QWebChannel(qt.webChannelTransport, function(channel) {
          editBridge = channel.objects.routeEditBridge;
        });
      } else {
        // qt.webChannelTransport not injected yet — retry shortly
        setTimeout(initBridge, 50);
      }
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initBridge);
    } else {
      initBridge();
    }

    function cancelCurrentAnimation() {
      if (animTimeoutId !== null) {
        clearTimeout(animTimeoutId);
        animTimeoutId = null;
      }
      if (animFrameId !== null) {
        cancelAnimationFrame(animFrameId);
        animFrameId = null;
      }
    }

    function toggleRoutePlayback() {
      if (isPlayingRoute) {
        pauseRoutePlayback();
      } else {
        startRoutePlayback();
      }
    }

    function startRoutePlayback() {
      if (!primaryCoords || primaryCoords.length < 2) return;
      isPlayingRoute = true;
      updatePlayBtnState(true);

      if (!animRiderMarker) {
        var startPt = primaryCoords[0];
        animRiderMarker = L.marker([startPt[1], startPt[0]], {
          interactive: false,
          icon: L.divIcon({
            className: 'anim-rider-marker',
            html: '<div class="anim-rider-dot"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8]
          })
        }).addTo(map);
        routeLayers.push(animRiderMarker);
      }

      var totalPoints = primaryCoords.length;
      var totalDist = 0;
      var pointDistances = [0];
      for (var i = 0; i < totalPoints - 1; i++) {
        var d = distanceMeters(primaryCoords[i], primaryCoords[i + 1]);
        totalDist += d;
        pointDistances.push(totalDist);
      }

      var lastTime = performance.now();
      var durationMs = Math.max(5000, Math.min(25000, (totalDist / 1000) * 800));

      function animateStep(now) {
        if (!isPlayingRoute) return;
        var elapsed = now - lastTime;
        lastTime = now;

        playbackProgressIndex += (elapsed / durationMs) * totalPoints;

        if (playbackProgressIndex >= totalPoints - 1) {
          playbackProgressIndex = 0;
          isPlayingRoute = false;
          updatePlayBtnState(false);
          if (animRiderMarker) {
            map.removeLayer(animRiderMarker);
            animRiderMarker = null;
          }
          if (editBridge) {
            editBridge.updatePlaybackProgress(0.0);
          }
          return;
        }

        var idx = Math.floor(playbackProgressIndex);
        var frac = playbackProgressIndex - idx;
        var p1 = primaryCoords[idx];
        var p2 = primaryCoords[idx + 1];
        var lon = p1[0] + (p2[0] - p1[0]) * frac;
        var lat = p1[1] + (p2[1] - p1[1]) * frac;

        if (animRiderMarker) {
          animRiderMarker.setLatLng([lat, lon]);
        }

        var curDist = pointDistances[idx] + (pointDistances[idx + 1] - pointDistances[idx]) * frac;
        var curKm = curDist / 1000.0;

        if (editBridge) {
          editBridge.updatePlaybackProgress(curKm);
        }

        playbackAnimFrame = requestAnimationFrame(animateStep);
      }

      playbackAnimFrame = requestAnimationFrame(animateStep);
    }

    function pauseRoutePlayback() {
      isPlayingRoute = false;
      if (playbackAnimFrame) {
        cancelAnimationFrame(playbackAnimFrame);
        playbackAnimFrame = null;
      }
      updatePlayBtnState(false);
    }

    function updatePlayBtnState(playing) {
      var btn = document.getElementById('routePlayBtn');
      if (!btn) return;
      var playIcon = btn.querySelector('.play-icon');
      var pauseIcon = btn.querySelector('.pause-icon');
      if (playing) {
        if (playIcon) playIcon.style.display = 'none';
        if (pauseIcon) pauseIcon.style.display = 'block';
      } else {
        if (playIcon) playIcon.style.display = 'block';
        if (pauseIcon) pauseIcon.style.display = 'none';
      }
    }

    function clearRoutes() {
      pauseRoutePlayback();
      playbackProgressIndex = 0;
      if (animRiderMarker) {
        map.removeLayer(animRiderMarker);
        animRiderMarker = null;
      }
      cancelCurrentAnimation();
      routeLayers.forEach(function(layer) { map.removeLayer(layer); });
      routeLayers = [];
      clearEditLayers();
      window.lastBestCoords = null;
      primaryCoords = null;
      primaryColor = null;
      primarySurfaceSegments = null;
      currentViaPoints = [];
      if (surfaceLegend) {
        map.removeControl(surfaceLegend);
        surfaceLegend = null;
      }
      setStartPoint(null, null);
    }

    function clearEditLayers() {
      editLayers.forEach(function(layer) { map.removeLayer(layer); });
      editLayers = [];
      editableRoute = null;
    }

    function routeCoordinates(geojson) {
      if (!geojson || !geojson.coordinates) return [];
      if (geojson.type === 'LineString') return geojson.coordinates;
      if (geojson.type === 'MultiLineString') return geojson.coordinates.flat();
      return [];
    }

    function distanceMeters(a, b) {
      var lat1 = a[1] * Math.PI / 180;
      var lat2 = b[1] * Math.PI / 180;
      var dLat = lat2 - lat1;
      var dLon = (b[0] - a[0]) * Math.PI / 180;
      var sinLat = Math.sin(dLat / 2);
      var sinLon = Math.sin(dLon / 2);
      var h = sinLat * sinLat + Math.cos(lat1) * Math.cos(lat2) * sinLon * sinLon;
      return 6371000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
    }

    function bearingDegrees(a, b) {
      var lat1 = a[1] * Math.PI / 180;
      var lat2 = b[1] * Math.PI / 180;
      var dLon = (b[0] - a[0]) * Math.PI / 180;
      var y = Math.sin(dLon) * Math.cos(lat2);
      var x = Math.cos(lat1) * Math.sin(lat2) -
              Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
      return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    }

    function cumulativeDistances(coords) {
      var cum = [0];
      for (var i = 0; i < coords.length - 1; i++) {
        cum.push(cum[i] + distanceMeters(coords[i], coords[i + 1]));
      }
      return cum;
    }

    function projectPointToSegment(p, a, b) {
      // Geodesic planar projection of point p onto segment a-b [lon, lat]
      var meanLat = (a[1] + b[1]) / 2.0;
      var cosLat = Math.cos(meanLat * Math.PI / 180.0) || 0.0001;
      var dx = (b[0] - a[0]) * cosLat;
      var dy = b[1] - a[1];
      var px = (p[0] - a[0]) * cosLat;
      var py = p[1] - a[1];
      var lenSq = dx * dx + dy * dy;
      var t = lenSq > 0 ? (px * dx + py * dy) / lenSq : 0;
      t = Math.max(0, Math.min(1, t));
      return [a[0] + (t * dx) / cosLat, a[1] + t * dy];
    }

    function distanceAlongRoute(latlng, coords, cumDist) {
      // Finds how far along the route (in meters from the start) the
      // closest point on the route is to the given latlng. Used to figure
      // out where a new/moved waypoint sits relative to the ones already
      // placed, so edits insert in route order rather than click order.
      var p = [latlng.lng, latlng.lat];
      var bestDist = Infinity;
      var bestAlong = 0;
      for (var i = 0; i < coords.length - 1; i++) {
        var a = coords[i];
        var b = coords[i + 1];
        var proj = projectPointToSegment(p, a, b);
        var d = distanceMeters(p, proj);
        if (d < bestDist) {
          bestDist = d;
          var alongSegment = distanceMeters(a, proj);
          bestAlong = cumDist[i] + alongSegment;
        }
      }
      return bestAlong;
    }

    function addPointMarker(coord, text, color, className) {
      var marker = L.marker([coord[1], coord[0]], {
        zIndexOffset: 2000,
        icon: L.divIcon({
          className: '',
          html: '<div class="route-point ' + className + '" style="background:' + color + '">' + text + '</div>',
          iconSize: [34, 24],
          iconAnchor: [17, 12]
        })
      }).addTo(map);
      routeLayers.push(marker);
    }

    function getSurfaceColorAtPoint(pointIndex, surfaceSegments, defaultColor) {
      if (!surfaceSegments || !surfaceSegments.length) return defaultColor;
      for (var s = 0; s < surfaceSegments.length; s++) {
        var seg = surfaceSegments[s];
        if (pointIndex >= seg.start && pointIndex <= seg.end) {
          return surfaceColors[seg.category] || defaultColor;
        }
      }
      return defaultColor;
    }

    function addDirectionArrows(coords, defaultColor, surfaceSegments) {
      if (coords.length < 2) return;

      var segmentLengths = [];
      var total = 0;
      for (var i = 0; i < coords.length - 1; i++) {
        var length = distanceMeters(coords[i], coords[i + 1]);
        segmentLengths.push(length);
        total += length;
      }
      if (total <= 0) return;

      var arrowCount = Math.max(3, Math.min(25, Math.floor(total / 600)));
      var nextTarget = total / (arrowCount + 1);
      var travelled = 0;
      var made = 0;

      for (var j = 0; j < segmentLengths.length && made < arrowCount; j++) {
        var segmentLength = segmentLengths[j];
        if (segmentLength <= 0) continue;

        while (travelled + segmentLength >= nextTarget && made < arrowCount) {
          var ratio = (nextTarget - travelled) / segmentLength;
          var start = coords[j];
          var end = coords[j + 1];
          var lon = start[0] + (end[0] - start[0]) * ratio;
          var lat = start[1] + (end[1] - start[1]) * ratio;
          var angle = bearingDegrees(start, end) - 90;

          var segColor = getSurfaceColorAtPoint(j, surfaceSegments, defaultColor);
          var arrow = L.marker([lat, lon], {
            interactive: false,
            icon: L.divIcon({
              className: 'strava-chevron-marker',
              html: '<div style="transform: rotate(' + angle + 'deg); display: flex; align-items: center; justify-content: center;">' +
                    '<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="' + segColor + '" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round">' +
                    '<polyline points="8 19 15 12 8 5"/>' +
                    '</svg></div>',
              iconSize: [28, 28],
              iconAnchor: [14, 14]
            })
          }).addTo(map);
          routeLayers.push(arrow);
          made += 1;
          nextTarget = total * (made + 1) / (arrowCount + 1);
        }
        travelled += segmentLength;
      }
    }

    function addKilometerMarkers(coords, color) {
      if (coords.length < 2) return;

      var segmentLengths = [];
      var total = 0;
      for (var i = 0; i < coords.length - 1; i++) {
        var length = distanceMeters(coords[i], coords[i + 1]);
        segmentLengths.push(length);
        total += length;
      }
      if (total < 1000) return;

      var nextTarget = 1000;
      var travelled = 0;
      var km = 1;

      for (var j = 0; j < segmentLengths.length && nextTarget < total; j++) {
        var segmentLength = segmentLengths[j];
        if (segmentLength <= 0) continue;

        while (travelled + segmentLength >= nextTarget && nextTarget < total) {
          var ratio = (nextTarget - travelled) / segmentLength;
          var start = coords[j];
          var end = coords[j + 1];
          var lon = start[0] + (end[0] - start[0]) * ratio;
          var lat = start[1] + (end[1] - start[1]) * ratio;
          var marker = L.marker([lat, lon], {
            interactive: false,
            icon: L.divIcon({
              className: '',
              html: '<div class="km-marker" style="border-color:' + color + '">' + km + '</div>',
              iconSize: [28, 22],
              iconAnchor: [14, 11]
            })
          }).addTo(map);
          routeLayers.push(marker);
          km += 1;
          nextTarget = km * 1000;
        }
        travelled += segmentLength;
      }
    }

    function addSurfaceSegments(coords, segments) {
      if (!segments || !segments.length || coords.length < 2) return false;
      var seen = {};

      segments.forEach(function(segment) {
        var start = Math.max(0, Math.min(segment.start || 0, coords.length - 1));
        var end = Math.max(start + 1, Math.min(segment.end || start + 1, coords.length - 1));
        var category = segment.category || 'Other';
        var color = surfaceColors[category] || '#64748b';
        var latLngs = coords.slice(start, end + 1).map(function(coord) {
          return [coord[1], coord[0]];
        });
        if (latLngs.length < 2) return;

        var layer = L.polyline(latLngs, {
          color: color,
          weight: 7,
          opacity: 0.9,
          lineCap: 'round',
          lineJoin: 'round'
        }).addTo(map);
        routeLayers.push(layer);
        seen[category] = true;
      });

      addSurfaceLegend(seen);
      return true;
    }

    function addSurfaceLegend(categories) {
      var names = Object.keys(surfaceColors).filter(function(name) { return categories[name]; });
      if (!names.length) return;

      surfaceLegend = L.control({ position: 'bottomright' });
      surfaceLegend.onAdd = function() {
        var div = L.DomUtil.create('div', 'surface-legend');
        div.innerHTML = '<div>Surface</div>' + names.map(function(name) {
          return '<div class="surface-legend-row">' +
            '<span class="surface-legend-swatch" style="background:' + surfaceColors[name] + '"></span>' +
            '<span>' + name + '</span>' +
          '</div>';
        }).join('');
        return div;
      };
      surfaceLegend.addTo(map);
    }

    function addEndpointMarkers(coords, color) {
      if (coords.length < 2) return;
      var start = coords[0];
      var finish = coords[coords.length - 1];
      if (distanceMeters(start, finish) < 40) {
        addPointMarker(start, 'S/F', color, 'loop');
        return;
      }
      addPointMarker(start, 'S', color, 'start');
      addPointMarker(finish, 'F', color, 'finish');
    }

    function addWaypointFromMapClick(e) {
      var bridge = editBridge || (window.qtChannel ? window.qtChannel.objects.routeEditBridge : null);
      if (!editMode || !e || !e.latlng) return;
      if (bridge) {
        if (createMode) {
          createMode = false;
          bridge.setManualStart(e.latlng.lat, e.latlng.lng);
          return;
        }
        // If clicking near start point (< 100 meters), auto-fuse Start & Finish (S/F)
        if (currentStartPoint && distanceMeters([currentStartPoint.lon, currentStartPoint.lat], [e.latlng.lng, e.latlng.lat]) < 100) {
          bridge.fuseStartFinish();
          return;
        }
        // If clicking on an existing route segment (< 30 meters), cut the route at that location
        if (primaryCoords && primaryCoords.length >= 2) {
          var clickPt = [e.latlng.lng, e.latlng.lat];
          var minRouteDist = Infinity;
          for (var i = 0; i < primaryCoords.length - 1; i++) {
            var proj = projectPointToSegment(clickPt, primaryCoords[i], primaryCoords[i + 1]);
            var d = distanceMeters(clickPt, proj);
            if (d < minRouteDist) minRouteDist = d;
          }
          if (minRouteDist < 30) {
            bridge.setManualFinish(e.latlng.lat, e.latlng.lng);
            return;
          }
        }
        var insertIndex = currentViaPoints ? currentViaPoints.length : 0;
        bridge.addWaypoint(e.latlng.lat, e.latlng.lng, insertIndex);
      }
    }

    function handleMapContextMenu(e) {
      if (!editMode || !e || !e.latlng) return;
      if (e.originalEvent) {
        L.DomEvent.preventDefault(e.originalEvent);
        L.DomEvent.stopPropagation(e.originalEvent);
      }
      var bridge = editBridge || (window.qtChannel ? window.qtChannel.objects.routeEditBridge : null);
      if (!bridge) return;

      var lat = e.latlng.lat;
      var lon = e.latlng.lng;

      // If near start point (< 100 meters), auto-fuse S/F
      if (currentStartPoint && distanceMeters([currentStartPoint.lon, currentStartPoint.lat], [lon, lat]) < 100) {
        bridge.fuseStartFinish();
        return;
      }

      var content = document.createElement('div');
      content.className = 'map-context-menu';

      var cutBtn = document.createElement('button');
      cutBtn.className = 'ctx-menu-btn cut';
      cutBtn.innerHTML = '✂️ Cut Route Here (Set Finish)';
      cutBtn.onclick = function() {
        map.closePopup();
        bridge.setManualFinish(lat, lon);
      };
      content.appendChild(cutBtn);

      if (currentStartPoint) {
        var fuseBtn = document.createElement('button');
        fuseBtn.className = 'ctx-menu-btn fuse';
        fuseBtn.innerHTML = '🔄 Fuse with Start (S/F)';
        fuseBtn.onclick = function() {
          map.closePopup();
          bridge.fuseStartFinish();
        };
        content.appendChild(fuseBtn);
      }

      L.popup({ className: 'custom-ctx-popup', closeButton: true })
        .setLatLng(e.latlng)
        .setContent(content)
        .openOn(map);
    }

    function setCreateMode(enabled) {
      createMode = !!enabled;
    }

    function drawWaypointMarkers() {
      if (!editMode) return;
      var coords = primaryCoords || window.lastBestCoords;
      if (!coords || coords.length < 2) return;

      var finishCoord = coords[coords.length - 1];
      var startCoord = coords[0];

      // Only draw finish handle if start and finish are not fused in a tight loop (< 40m)
      if (distanceMeters(startCoord, finishCoord) < 40) return;

      var finishMarker = L.marker([finishCoord[1], finishCoord[0]], {
        draggable: true,
        zIndexOffset: 1500,
        icon: L.divIcon({
          className: '',
          html: '<div class="edit-handle"></div>',
          iconSize: [24, 24],
          iconAnchor: [12, 12]
        })
      }).addTo(map);

      finishMarker.bindTooltip('Drag to move finish point', { direction: 'top' });

      finishMarker.on('click', function(event) {
        if (event.originalEvent) L.DomEvent.stop(event.originalEvent);
      });

      finishMarker.on('dragend', function(event) {
        var latlng = event.target.getLatLng();
        if (currentStartPoint && distanceMeters([currentStartPoint.lon, currentStartPoint.lat], [latlng.lng, latlng.lat]) < 100) {
          if (editBridge) editBridge.fuseStartFinish();
          return;
        }
        if (currentViaPoints && currentViaPoints.length > 0) {
          var lastIdx = currentViaPoints.length - 1;
          if (editBridge) editBridge.moveWaypoint(lastIdx, lastIdx, latlng.lat, latlng.lng);
        } else if (editBridge) {
          editBridge.setManualFinish(latlng.lat, latlng.lng);
        }
      });

      editLayers.push(finishMarker);
    }

    function setEditMode(enabled) {
      editMode = enabled;
      if (!enabled) createMode = false;
      cancelCurrentAnimation();
      map.off('click', addWaypointFromMapClick);
      map.off('contextmenu', handleMapContextMenu);
      clearEditLayers();
      if (editHelp) {
        map.removeControl(editHelp);
        editHelp = null;
      }
      if (enabled) {
        map.on('click', addWaypointFromMapClick);
        map.on('contextmenu', handleMapContextMenu);
        editHelp = L.control({ position: 'topleft' });
        editHelp.onAdd = function() {
          var div = L.DomUtil.create('div', 'edit-help');
          div.innerHTML = 'Click map to edit route. Complete route to create start and finish';
          return div;
        };
        editHelp.addTo(map);
      }
      if (window.lastViaPoints) {
        currentViaPoints = window.lastViaPoints;
      }
      if (enabled) {
        drawWaypointMarkers();
      }
    }

    function animateRouteDrawIn(geoJsonLayer, durationMs, onComplete) {
      function tryAnimate(attemptsLeft) {
        var animatedAny = false;

        geoJsonLayer.eachLayer(function(sublayer) {
          if (typeof sublayer.setLatLngs !== 'function' || typeof sublayer.getLatLngs !== 'function') return;

          var fullLatLngs = sublayer.getLatLngs();
          var flat = Array.isArray(fullLatLngs) && fullLatLngs.length && !Array.isArray(fullLatLngs[0])
            ? fullLatLngs
            : null;
          if (!flat || flat.length < 2) return;

          sublayer.setLatLngs([flat[0]]);

          var startTime = null;
          function step(timestamp) {
            if (startTime === null) startTime = timestamp;
            var elapsed = timestamp - startTime;
            var t = Math.min(elapsed / durationMs, 1);
            var eased = 1 - Math.pow(1 - t, 3);
            var pointCount = Math.max(2, Math.round(eased * (flat.length - 1)) + 1);
            sublayer.setLatLngs(flat.slice(0, pointCount));
            if (t < 1) {
              animFrameId = requestAnimationFrame(step);
            } else {
              animFrameId = null;
              sublayer.setLatLngs(flat);
              if (typeof onComplete === 'function') onComplete();
            }
          }
          animFrameId = requestAnimationFrame(step);
          animatedAny = true;
        });

        if (!animatedAny && attemptsLeft > 0) {
          animFrameId = requestAnimationFrame(function() { tryAnimate(attemptsLeft - 1); });
        } else if (!animatedAny) {
          animFrameId = null;
          if (typeof onComplete === 'function') onComplete();
        }
      }

      animFrameId = requestAnimationFrame(function() { tryAnimate(10); });
    }

    var hoverMarker = null;

    function setHoverPoint(lat, lon) {
      if (lat === null || lon === null || typeof lat === 'undefined' || typeof lon === 'undefined') {
        if (hoverMarker) {
          map.removeLayer(hoverMarker);
          hoverMarker = null;
        }
        return;
      }
      var latLng = L.latLng(lat, lon);
      if (!hoverMarker) {
        hoverMarker = L.marker(latLng, {
          interactive: false,
          icon: L.divIcon({
            className: 'hover-point-marker',
            iconSize: [14, 14],
            iconAnchor: [7, 7]
          })
        }).addTo(map);
      } else {
        hoverMarker.setLatLng(latLng);
      }
    }

    var standaloneStartMarker = null;
    var standaloneFinishMarker = null;
    var currentStartPoint = null;

    function setStartPoint(lat, lon, label) {
      if (standaloneStartMarker) {
        map.removeLayer(standaloneStartMarker);
        standaloneStartMarker = null;
      }
      if (lat === null || lon === null || typeof lat === 'undefined' || typeof lon === 'undefined') {
        currentStartPoint = null;
        return;
      }
      currentStartPoint = { lat: lat, lon: lon };
      var badgeText = label || 'S';
      var badgeClass = badgeText === 'S/F' ? 'route-point loop' : 'route-point start';
      standaloneStartMarker = L.marker([lat, lon], {
        icon: L.divIcon({
          className: '',
          html: '<div class="' + badgeClass + '" style="background:#2563eb">' + badgeText + '</div>',
          iconSize: [34, 24],
          iconAnchor: [17, 12]
        })
      }).addTo(map);
      map.panTo([lat, lon]);
    }

    function setFinishPoint(lat, lon) {
      if (standaloneFinishMarker) {
        map.removeLayer(standaloneFinishMarker);
        standaloneFinishMarker = null;
      }
    }

    function panToPoint(lat, lon) {
      if (typeof lat === 'number' && typeof lon === 'number') {
        var zoom = Math.max(map.getZoom(), 14);
        map.flyTo([lat, lon], zoom, { duration: 0.8 });
      }
    }

    // Called from Python via runJavaScript(). Accepts a list of
    // {geojson, color, label} objects so multiple provider routes can be
    // shown at once for comparison.
    function drawRoutes(routesJson, animate, fitBounds) {
      if (typeof animate === 'undefined') animate = true;
      if (typeof fitBounds === 'undefined') fitBounds = true;
      clearRoutes();
      var routes = routesJson;
      while (typeof routes === 'string') {
        try {
          routes = JSON.parse(routes);
        } catch (e) {
          console.error("Failed to parse routesJson:", e);
          return;
        }
      }
      if (!Array.isArray(routes)) return;
      var bounds = [];
      var primaryLayer = null;
      routes.forEach(function(r) {
        if (r.showDistanceMarkers) {
          currentViaPoints = r.viaPoints || [];
          window.lastViaPoints = currentViaPoints;
        }
        var layer = L.geoJSON(r.geojson, {
          style: { color: r.color, weight: 5, opacity: r.opacity || 0.85 }
        }).addTo(map);
        layer.bindPopup(r.label);
        routeLayers.push(layer);
        var coords = routeCoordinates(r.geojson);
        if (r.showDistanceMarkers) {
          primaryLayer = layer;
          primaryCoords = coords;
          primaryColor = r.color;
          primarySurfaceSegments = r.surfaceSegments;
          window.lastBestCoords = coords;
        }
        layer.eachLayer(function(l) {
          if (l.getBounds) bounds.push(l.getBounds());
        });
      });
      if (fitBounds && bounds.length > 0) {
        var combined = bounds[0];
        bounds.slice(1).forEach(function(b) { combined.extend(b); });
        map.fitBounds(combined, { padding: [30, 30], animate: false });
      }
      if (primaryLayer) {
        addSurfaceSegments(primaryCoords, primarySurfaceSegments);
        addDirectionArrows(primaryCoords, primaryColor, primarySurfaceSegments);
        addKilometerMarkers(primaryCoords, primaryColor);
        addEndpointMarkers(primaryCoords, primaryColor);
        if (editMode) drawWaypointMarkers();
      }
    }
  </script>
</body>
</html>
"""


class RouteEditBridge(QObject):
    waypoint_added = pyqtSignal(float, float, int)
    waypoint_moved = pyqtSignal(int, int, float, float)
    waypoint_removed = pyqtSignal(int)
    manual_start_selected = pyqtSignal(float, float)
    manual_finish_selected = pyqtSignal(float, float)
    fuse_start_finish_requested = pyqtSignal()
    playback_progress = pyqtSignal(float)

    @pyqtSlot(float, float, int)
    def addWaypoint(self, lat: float, lon: float, index: int):
        self.waypoint_added.emit(lat, lon, index)

    @pyqtSlot(int, int, float, float)
    def moveWaypoint(self, old_index: int, new_index: int, lat: float, lon: float):
        self.waypoint_moved.emit(old_index, new_index, lat, lon)

    @pyqtSlot(int)
    def removeWaypoint(self, index: int):
        self.waypoint_removed.emit(index)

    @pyqtSlot(float, float)
    def setManualStart(self, lat: float, lon: float):
        self.manual_start_selected.emit(lat, lon)

    @pyqtSlot(float, float)
    def setManualFinish(self, lat: float, lon: float):
        self.manual_finish_selected.emit(lat, lon)

    @pyqtSlot()
    def fuseStartFinish(self):
        self.fuse_start_finish_requested.emit()

    @pyqtSlot(float)
    def updatePlaybackProgress(self, dist_km: float):
        self.playback_progress.emit(dist_km)


class MapView(QWebEngineView):
    waypoint_added = pyqtSignal(float, float, int)
    waypoint_moved = pyqtSignal(int, int, float, float)
    waypoint_removed = pyqtSignal(int)
    manual_start_selected = pyqtSignal(float, float)
    manual_finish_selected = pyqtSignal(float, float)
    fuse_start_finish_requested = pyqtSignal()
    playback_progress = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = RouteEditBridge()
        self.bridge.waypoint_added.connect(self.waypoint_added)
        self.bridge.waypoint_moved.connect(self.waypoint_moved)
        self.bridge.waypoint_removed.connect(self.waypoint_removed)
        self.bridge.manual_start_selected.connect(self.manual_start_selected)
        self.bridge.manual_finish_selected.connect(self.manual_finish_selected)
        self.bridge.fuse_start_finish_requested.connect(self.fuse_start_finish_requested)
        self.bridge.playback_progress.connect(self.playback_progress)
        self.channel = QWebChannel(self.page())
        self.channel.registerObject("routeEditBridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self._page_loaded = False
        self._pending_js: list[str] = []
        self.loadFinished.connect(self._on_page_loaded)
        self.setHtml(MAP_HTML, QUrl("https://localhost/"))

    def _on_page_loaded(self, ok: bool):
        self._page_loaded = True
        for js in self._pending_js:
            self.page().runJavaScript(js)
        self._pending_js.clear()

    def _run_js(self, js: str):
        """Run JavaScript, queuing the call if the page hasn't loaded yet."""
        if self._page_loaded:
            self.page().runJavaScript(js)
        else:
            self._pending_js.append(js)

    def show_routes(self, routes_with_style: list[dict], animate: bool = True, fit_bounds: bool = True):
        """
        routes_with_style: list of {"geojson": dict, "color": str, "label": str}
        Call this after the page has finished loading (see MainWindow).
        """
        payload = json.dumps(routes_with_style)
        surface_styles = json.dumps(surface_styles_for_ui())
        # Escape for embedding inside a JS string literal passed to runJavaScript
        js = (
            f"surfaceColors = {surface_styles}; "
            f"drawRoutes({payload}, {str(animate).lower()}, {str(fit_bounds).lower()});"
        )
        self._run_js(js)

    def set_edit_mode(self, enabled: bool):
        self._run_js(f"setEditMode({str(enabled).lower()});")

    def set_create_mode(self, enabled: bool):
        self._run_js(f"setCreateMode({str(enabled).lower()});")

    def set_theme(self, theme: str):
        js_theme = "dark" if theme == "dark" else "light"
        self._run_js(f"setTheme('{js_theme}');")

    def set_hover_point(self, lat: Optional[float], lon: Optional[float]):
        if lat is None or lon is None:
            self._run_js("setHoverPoint(null, null);")
        else:
            self._run_js(f"setHoverPoint({lat}, {lon});")

    def set_start_point(self, lat: Optional[float], lon: Optional[float], label: str = "S"):
        if lat is None or lon is None:
            self._run_js("setStartPoint(null, null);")
        else:
            self._run_js(f"setStartPoint({lat}, {lon}, '{label}');")

    def set_finish_point(self, lat: Optional[float], lon: Optional[float]):
        if lat is None or lon is None:
            self._run_js("setFinishPoint(null, null);")
        else:
            self._run_js(f"setFinishPoint({lat}, {lon});")

    def pan_to_point(self, lat: float, lon: float):
        self._run_js(f"panToPoint({lat}, {lon});")
