/* GoPoint Landing Page - Leaflet Dark Map Showcase Engine */

class GoPointMapShowcase {
  constructor(mapElementId) {
    this.mapElementId = mapElementId;
    this.map = null;
    this.routePolyline = null;
    this.glowPolyline = null;
    this.startMarker = null;
    this.hoverMarker = null;
    this.currentRoute = null;
  }

  init() {
    if (!document.getElementById(this.mapElementId)) return;

    // Initialize Leaflet map with dark theme CartoDB tiles
    this.map = L.map(this.mapElementId, {
      zoomControl: true,
      scrollWheelZoom: false,
      attributionControl: false
    }).setView([59.9450, 10.6800], 12);

    // CartoDB Dark Matter tile layer (Free, fast, no API key required)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      subdomains: 'abcd'
    }).addTo(this.map);

    // Custom attribution subtle styling
    L.control.attribution({ position: 'bottomright' })
      .addAttribution('&copy; <a href="https://carto.com/" target="_blank" style="color:#64748B">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" style="color:#64748B">OpenStreetMap</a>')
      .addTo(this.map);

    // Custom glowing SVG marker for hover sync
    const hoverIcon = L.divIcon({
      className: 'custom-hover-marker',
      html: `<div style="width:16px; height:16px; background:#00FF9D; border:2px solid #FFFFFF; border-radius:50%; box-shadow:0 0 15px #00FF9D; transform:translate(-50%, -50%);"></div>`,
      iconSize: [16, 16],
      iconAnchor: [8, 8]
    });

    this.hoverMarker = L.marker([0, 0], { icon: hoverIcon, opacity: 0 }).addTo(this.map);
  }

  renderRoute(routeData) {
    if (!this.map) this.init();

    this.currentRoute = routeData;

    // Remove existing polylines/markers
    if (this.routePolyline) this.map.removeLayer(this.routePolyline);
    if (this.glowPolyline) this.map.removeLayer(this.glowPolyline);
    if (this.startMarker) this.map.removeLayer(this.startMarker);

    const coords = routeData.coordinates;

    // Create glowing background trail
    this.glowPolyline = L.polyline(coords, {
      color: '#00FF9D',
      weight: 9,
      opacity: 0.35,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(this.map);

    // Main sharp polyline
    this.routePolyline = L.polyline(coords, {
      color: '#00FF9D',
      weight: 4,
      opacity: 0.95,
      lineCap: 'round',
      lineJoin: 'round'
    }).addTo(this.map);

    // Start / Finish Waypoint Icon
    const startIcon = L.divIcon({
      className: 'custom-start-marker',
      html: `<div style="width:28px; height:28px; background:linear-gradient(135deg, #00FF9D, #0070FF); border:2px solid #FFFFFF; border-radius:50%; display:flex; align-items:center; justify-content:center; color:#0B0F19; font-weight:800; font-size:12px; box-shadow:0 0 20px rgba(0,255,157,0.6); transform:translate(-50%, -50%);">🚩</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14]
    });

    this.startMarker = L.marker(routeData.startPoint, { icon: startIcon }).addTo(this.map);
    this.startMarker.bindPopup(`<b>${routeData.title}</b><br>Start & Finish Point`).openPopup();

    // Auto-fit bounds with padding
    const bounds = L.latLngBounds(coords);
    this.map.fitBounds(bounds, { padding: [40, 40], animate: true });
  }

  updateHoverPosition(lat, lng) {
    if (!this.hoverMarker || !this.map) return;
    this.hoverMarker.setLatLng([lat, lng]);
    this.hoverMarker.setOpacity(1);
  }

  hideHoverPosition() {
    if (this.hoverMarker) {
      this.hoverMarker.setOpacity(0);
    }
  }
}

window.GoPointMapShowcase = GoPointMapShowcase;
