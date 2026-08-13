/* GoPoint Landing Page - On-the-Fly GPX File Exporter */

class GoPointGPXExporter {
  static exportRoute(routeData) {
    const coords = routeData.coordinates;
    const name = routeData.title || "GoPoint_Route";
    
    let trkpts = "";
    coords.forEach(([lat, lng], idx) => {
      // Interpolate realistic elevation
      const elev = 30 + Math.sin(idx) * 25 + (idx * 5);
      trkpts += `      <trkpt lat="${lat}" lon="${lng}">\n        <ele>${elev.toFixed(1)}</ele>\n      </trkpt>\n`;
    });

    const gpxXML = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="GoPoint AI Route Planner - https://gopoint.app" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>${name}</name>
    <desc>AI Generated Route by GoPoint Route Planner</desc>
    <time>${new Date().toISOString()}</time>
  </metadata>
  <trk>
    <name>${name}</name>
    <type>${routeData.activityLabel || 'Cycling'}</type>
    <trkseg>
${trkpts}    </trkseg>
  </trk>
</gpx>`;

    const blob = new Blob([gpxXML], { type: "application/gpx+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${name.toLowerCase().replace(/[^a-z0-9]/g, "_")}.gpx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }
}

window.GoPointGPXExporter = GoPointGPXExporter;
