// src/services/api.js

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
const BASE_URL = import.meta.env.VITE_API_URL || "";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`Server error ${res.status}`);
  return res.json();
}

// ---------- Mock data (placeholder values, same coordinates give same output) ----------

function seededRandom(lat, lon) {
  let s = Math.abs(Math.sin(lat * 12.9898 + lon * 78.233) * 43758.5453) % 1;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

function mockAnalysis(lat, lon) {
  const r = seededRandom(lat, lon);
  const between = (a, b, d = 1) => Number((a + r() * (b - a)).toFixed(d));
  const pick = (list) => list[Math.floor(r() * list.length)];

  const slopeDeg = between(1, 15);
  const psrDistanceKm = between(0.5, 25);
  const iceLikelihood = psrDistanceKm < 5 ? "High" : psrDistanceKm < 12 ? "Moderate" : "Low";

  const sunAlt = between(-3, 6);
  const illumination = Math.round(between(25, 90, 0));

  const earthAlt = between(-5, 8);
  const earthPercent = Math.round(between(20, 80, 0));

  const breakdown = {
    power: Number((illumination / 10).toFixed(1)),
    comms: Number((earthPercent / 10).toFixed(1)),
    terrain: Number(Math.max(0, 10 - slopeDeg * 0.5).toFixed(1)),
    resources: iceLikelihood === "High" ? 9 : iceLikelihood === "Moderate" ? 6.5 : 4,
  };
  const score = Number(
    ((breakdown.power + breakdown.comms + breakdown.terrain + breakdown.resources) / 4).toFixed(1)
  );

  return {
    meta: { source: "mock" },
    site: {
      terrain: pick(["Crater rim", "Crater floor", "Highland ridge", "Smooth plain", "Massif slope"]),
      elevationM: Math.round(between(-1500, 2500, 0)),
      slopeDeg,
      psrDistanceKm,
      iceLikelihood,
    },
    sun: {
      altitudeDeg: sunAlt,
      azimuthDeg: Math.round(between(0, 360, 0)),
      sunlit: sunAlt > 0,
      nextChangeHours: between(20, 300),
      longestSunlightDays: between(2, 14),
      longestDarknessDays: between(1, 10),
    },
    illumination: { percent: illumination },
    earthVisibility: {
      percent: earthPercent,
      visibleNow: earthAlt > 0,
      altitudeDeg: earthAlt,
      azimuthDeg: Math.round(between(0, 360, 0)),
      nextWindowHours: between(2, 150),
    },
    communication: {
      directToEarth: earthPercent >= 40,
      relayNeeded: earthPercent < 60,
      oneWayDelayS: 1.3,
    },
    environment: {
      dayTempC: Math.round(between(-120, -30, 0)),
      nightTempC: Math.round(between(-240, -170, 0)),
    },
    breakdown,
    score,
    explanation:
      "Placeholder explanation. The real scoring and explanation will come from the backend once it is connected.",
  };
}

// ---------- Public API ----------

/** POST /api/analyze  body { lat, lon, datetime }  (shape: see mockAnalysis) */
export async function analyzeSite({ lat, lon, datetime }) {
  if (USE_MOCK) {
    await sleep(400);
    return mockAnalysis(lat, lon);
  }
  return request("/api/analyze", {
    method: "POST",
    body: JSON.stringify({ lat, lon, datetime }),
  });
}

export async function compareSites(sites, datetime) {
  return Promise.all(sites.map((s) => analyzeSite({ lat: s.lat, lon: s.lon, datetime })));
}