/* GoPoint Landing Page - Interactive SVG Elevation Profile Chart */

class GoPointElevationPreview {
  constructor(containerId, mapShowcase) {
    this.containerId = containerId;
    this.mapShowcase = mapShowcase;
    this.container = null;
    this.currentRoute = null;
  }

  render(routeData) {
    this.container = document.getElementById(this.containerId);
    if (!this.container) return;

    this.currentRoute = routeData;
    const elevationPoints = routeData.elevationData;
    const coords = routeData.coordinates;

    const width = this.container.clientWidth || 320;
    const height = 130;
    const padding = { top: 15, right: 15, bottom: 25, left: 35 };

    const maxDist = routeData.distanceKm;
    const minElev = Math.min(...elevationPoints.map(p => p[1])) * 0.8;
    const maxElev = Math.max(...elevationPoints.map(p => p[1])) * 1.15;

    const scaleX = (dist) => padding.left + (dist / maxDist) * (width - padding.left - padding.right);
    const scaleY = (elev) => height - padding.bottom - ((elev - minElev) / (maxElev - minElev)) * (height - padding.top - padding.bottom);

    // Build SVG path string
    let pathD = `M ${scaleX(elevationPoints[0][0])} ${scaleY(elevationPoints[0][1])}`;
    elevationPoints.forEach((p, idx) => {
      if (idx > 0) {
        pathD += ` L ${scaleX(p[0])} ${scaleY(p[1])}`;
      }
    });

    const areaD = `${pathD} L ${scaleX(maxDist)} ${height - padding.bottom} L ${scaleX(0)} ${height - padding.bottom} Z`;

    // Highpoint marker
    const peakPoint = elevationPoints.reduce((prev, current) => (prev[1] > current[1]) ? prev : current);
    const peakX = scaleX(peakPoint[0]);
    const peakY = scaleY(peakPoint[1]);

    const svgHTML = `
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow: visible;">
        <defs>
          <linearGradient id="elevationGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#00FF9D" stop-opacity="0.4"/>
            <stop offset="100%" stop-color="#00FF9D" stop-opacity="0.0"/>
          </linearGradient>
        </defs>

        <!-- Grid Lines -->
        <line x1="${padding.left}" y1="${scaleY(minElev)}" x2="${width - padding.right}" y2="${scaleY(minElev)}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4"/>
        <line x1="${padding.left}" y1="${scaleY(maxElev)}" x2="${width - padding.right}" y2="${scaleY(maxElev)}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="4"/>

        <!-- Area Fill -->
        <path d="${areaD}" fill="url(#elevationGrad)" />

        <!-- Line Path -->
        <path d="${pathD}" fill="none" stroke="#00FF9D" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />

        <!-- Peak Point Dot & Label -->
        <circle cx="${peakX}" cy="${peakY}" r="4" fill="#FFFFFF" stroke="#00FF9D" stroke-width="2" />
        <text x="${peakX}" y="${peakY - 8}" fill="#00FF9D" font-size="10" font-weight="700" text-anchor="middle">Peak: ${peakPoint[1]}m</text>

        <!-- Axes Labels -->
        <text x="${padding.left}" y="${height - 5}" fill="#64748B" font-size="10">0 km</text>
        <text x="${width - padding.right}" y="${height - 5}" fill="#64748B" font-size="10" text-anchor="end">${maxDist} km</text>

        <!-- Dynamic Hover Tracking Line & Dot -->
        <line id="elev-hover-line" x1="0" y1="${padding.top}" x2="0" y2="${height - padding.bottom}" stroke="#0070FF" stroke-width="1.5" stroke-dasharray="3" style="display:none;" />
        <circle id="elev-hover-dot" cx="0" cy="0" r="5" fill="#0070FF" stroke="#FFFFFF" stroke-width="2" style="display:none;" />
      </svg>
    `;

    this.container.innerHTML = svgHTML;

    // Attach Mouseover Tracking
    const svgEl = this.container.querySelector('svg');
    const hoverLine = this.container.querySelector('#elev-hover-line');
    const hoverDot = this.container.querySelector('#elev-hover-dot');

    svgEl.addEventListener('mousemove', (e) => {
      const rect = svgEl.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;

      if (mouseX >= padding.left && mouseX <= width - padding.right) {
        const ratio = (mouseX - padding.left) / (width - padding.left - padding.right);
        const currentDist = ratio * maxDist;

        // Find nearest elevation point
        let nearestIndex = 0;
        let minDiff = Infinity;
        elevationPoints.forEach((p, i) => {
          const diff = Math.abs(p[0] - currentDist);
          if (diff < minDiff) {
            minDiff = diff;
            nearestIndex = i;
          }
        });

        const targetPoint = elevationPoints[nearestIndex];
        const targetX = scaleX(targetPoint[0]);
        const targetY = scaleY(targetPoint[1]);

        hoverLine.setAttribute('x1', targetX);
        hoverLine.setAttribute('x2', targetX);
        hoverLine.style.display = 'block';

        hoverDot.setAttribute('cx', targetX);
        hoverDot.setAttribute('cy', targetY);
        hoverDot.style.display = 'block';

        // Map Sync
        if (this.mapShowcase && coords.length > 0) {
          const coordIndex = Math.min(Math.floor(ratio * coords.length), coords.length - 1);
          const [lat, lng] = coords[coordIndex];
          this.mapShowcase.updateHoverPosition(lat, lng);
        }
      }
    });

    svgEl.addEventListener('mouseleave', () => {
      if (hoverLine) hoverLine.style.display = 'none';
      if (hoverDot) hoverDot.style.display = 'none';
      if (this.mapShowcase) this.mapShowcase.hideHoverPosition();
    });
  }
}

window.GoPointElevationPreview = GoPointElevationPreview;
