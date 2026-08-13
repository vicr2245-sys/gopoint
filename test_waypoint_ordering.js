// Minimal mock of the Leaflet bits the extracted functions rely on.
var L = { latLng: function(lat, lon) { return { lat: lat, lng: lon }; } };

// ---- functions copied verbatim from map_view.py's embedded JS ----
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

function cumulativeDistances(coords) {
  var cum = [0];
  for (var i = 0; i < coords.length - 1; i++) {
    cum.push(cum[i] + distanceMeters(coords[i], coords[i + 1]));
  }
  return cum;
}

function projectPointToSegment(p, a, b) {
  var dx = b[0] - a[0];
  var dy = b[1] - a[1];
  var lenSq = dx * dx + dy * dy;
  var t = lenSq > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / lenSq : 0;
  t = Math.max(0, Math.min(1, t));
  return [a[0] + t * dx, a[1] + t * dy];
}

function distanceAlongRoute(latlng, coords, cumDist) {
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
// ---- end copied functions ----

// Synthetic route: a square loop traced counter-clockwise, roughly
// matching lon/lat deltas for a small area near Oslo.
// Corners: bottom-left -> bottom-right -> top-right -> top-left -> back
var coords = [];
function addLine(lon1, lat1, lon2, lat2, steps) {
  for (var i = 0; i <= steps; i++) {
    var t = i / steps;
    coords.push([lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t]);
  }
}
addLine(10.70, 59.90, 10.80, 59.90, 10); // bottom edge, west->east
addLine(10.80, 59.90, 10.80, 59.95, 10); // east edge, south->north
addLine(10.80, 59.95, 10.70, 59.95, 10); // top edge, east->west
addLine(10.70, 59.95, 10.70, 59.90, 10); // west edge, north->south

var cumDist = cumulativeDistances(coords);

function insertionIndexFor(clickLatLng, existingViaPoints) {
  var clickAlong = distanceAlongRoute(clickLatLng, coords, cumDist);
  var viaAlong = existingViaPoints.map(function(pt) {
    return distanceAlongRoute(L.latLng(pt.lat, pt.lon), coords, cumDist);
  });
  var idx = 0;
  while (idx < viaAlong.length && viaAlong[idx] < clickAlong) idx++;
  return idx;
}

// --- Test 1: two points already placed on the near (bottom + east) side,
// user now clicks on the FAR (west) side to round out the loop. The click
// is LATER along the route than both existing points, so it should insert
// at the END (index 2), not confuse the order.
var via1 = [
  { lat: 59.90, lon: 10.75 },  // on bottom edge
  { lat: 59.925, lon: 10.80 }, // on east edge
];
var click1 = L.latLng(59.95, 10.75); // on top edge -> later along route
var idx1 = insertionIndexFor(click1, via1);
console.log('Test 1 (click further along route than both existing points): insertIndex =', idx1, '(expected 2)');

// --- Test 2: same two existing points, but now click BETWEEN them
// geographically (near the SE corner along the east edge, before the
// second via point) -> should insert at index 1 (between the two), not
// appended at the end.
var click2 = L.latLng(59.91, 10.80); // early on east edge, before via1[1]
var idx2 = insertionIndexFor(click2, via1);
console.log('Test 2 (click between two existing points): insertIndex =', idx2, '(expected 1)');

// --- Test 3: click BEFORE the first existing point (early on bottom edge)
// -> should insert at index 0.
var click3 = L.latLng(59.90, 10.72);
var idx3 = insertionIndexFor(click3, via1);
console.log('Test 3 (click before first existing point): insertIndex =', idx3, '(expected 0)');

var pass = idx1 === 2 && idx2 === 1 && idx3 === 0;
console.log(pass ? '\nALL PASS' : '\nFAIL');
process.exit(pass ? 0 : 1);
