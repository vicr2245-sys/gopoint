/* GoPoint Landing Page - Curated Route Presets Dataset (Zero API Key Required) */

window.GoPointPresets = [
  {
    id: "frogner-loop",
    title: "30km Hilly Cycling Loop from Frogner Park",
    activity: "cycling",
    activityLabel: "Cycling",
    promptText: "30km hilly bike loop from Frogner park, avoid busy streets",
    distanceKm: 31.4,
    elevationGainM: 480,
    estTime: "1h 22m",
    maxGradient: "8.2%",
    surfaceBreakdown: { paved: 70, gravel: 25, trail: 5 },
    startPoint: [59.9242, 10.7027], // Frogner Park, Oslo
    center: [59.9450, 10.6800],
    zoom: 12,
    // Realistic loop coordinates
    coordinates: [
      [59.9242, 10.7027],
      [59.9310, 10.6980],
      [59.9420, 10.6850],
      [59.9550, 10.6620],
      [59.9680, 10.6510],
      [59.9800, 10.6700],
      [59.9750, 10.7000],
      [59.9600, 10.7300],
      [59.9480, 10.7420],
      [59.9350, 10.7250],
      [59.9242, 10.7027]
    ],
    // Elevation profile points: [distanceKm, elevationM, gradientPct]
    elevationData: [
      [0.0, 42, 0.5],
      [3.2, 78, 2.1],
      [7.5, 145, 4.2],
      [12.1, 290, 7.8],
      [16.4, 420, 8.2], // Peak
      [20.0, 310, -4.5],
      [24.5, 185, -2.8],
      [28.0, 75, -1.2],
      [31.4, 42, 0.0]
    ]
  },
  {
    id: "central-park-run",
    title: "10km Scenic Park Trail Run",
    activity: "running",
    activityLabel: "Trail Run",
    promptText: "10km scenic trail run around Central Park loop with gentle hills",
    distanceKm: 10.2,
    elevationGainM: 165,
    estTime: "52m",
    maxGradient: "4.5%",
    surfaceBreakdown: { paved: 30, gravel: 50, trail: 20 },
    startPoint: [40.7674, -73.9742], // Central Park South
    center: [40.7812, -73.9665],
    zoom: 13,
    coordinates: [
      [40.7674, -73.9742],
      [40.7725, -73.9780],
      [40.7830, -73.9650],
      [40.7960, -73.9550],
      [40.7920, -73.9510],
      [40.7810, -73.9600],
      [40.7710, -73.9710],
      [40.7674, -73.9742]
    ],
    elevationData: [
      [0.0, 18, 0.2],
      [2.1, 35, 1.8],
      [4.8, 62, 3.5],
      [6.5, 88, 4.5],
      [8.2, 45, -2.1],
      [10.2, 18, 0.0]
    ]
  },
  {
    id: "gravel-adventure",
    title: "45km Forest Gravel Adventure",
    activity: "gravel",
    activityLabel: "Gravel / MTB",
    promptText: "45km gravel ride through deep forest, max elevation gain, avoid traffic",
    distanceKm: 46.8,
    elevationGainM: 840,
    estTime: "2h 35m",
    maxGradient: "11.4%",
    surfaceBreakdown: { paved: 10, gravel: 65, trail: 25 },
    startPoint: [59.9800, 10.7300], // Nordmarka entrance
    center: [60.0300, 10.7000],
    zoom: 11,
    coordinates: [
      [59.9800, 10.7300],
      [60.0050, 10.7100],
      [60.0350, 10.6800],
      [60.0700, 10.6600],
      [60.0850, 10.7200],
      [60.0500, 10.7700],
      [60.0100, 10.7600],
      [59.9800, 10.7300]
    ],
    elevationData: [
      [0.0, 160, 1.0],
      [8.5, 310, 3.8],
      [18.2, 580, 8.5],
      [26.4, 760, 11.4], // Peak summit
      [34.0, 520, -5.2],
      [41.0, 280, -3.1],
      [46.8, 160, 0.0]
    ]
  },
  {
    id: "coastal-road-trip",
    title: "120km Coastal Scenic Drive",
    activity: "driving",
    activityLabel: "Scenic Drive",
    promptText: "120km scenic coastal road trip avoiding highways with ocean views",
    distanceKm: 124.5,
    elevationGainM: 620,
    estTime: "2h 10m",
    maxGradient: "6.0%",
    surfaceBreakdown: { paved: 95, gravel: 5, trail: 0 },
    startPoint: [36.6002, -121.8947], // Monterey, CA
    center: [36.3500, -121.8500],
    zoom: 9,
    coordinates: [
      [36.6002, -121.8947],
      [36.5400, -121.9200],
      [36.4200, -121.9100],
      [36.2700, -121.8100],
      [36.1800, -121.6800],
      [36.3000, -121.7500],
      [36.4800, -121.8500],
      [36.6002, -121.8947]
    ],
    elevationData: [
      [0.0, 5, 0.1],
      [25.0, 120, 2.5],
      [58.0, 340, 5.8],
      [85.0, 480, 6.0],
      [110.0, 180, -4.2],
      [124.5, 5, 0.0]
    ]
  }
];
