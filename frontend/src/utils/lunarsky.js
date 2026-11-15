// src/utils/lunarsky.js
// Real Sun and Earth positions as seen from a point on the Moon's surface.
import * as Astronomy from "astronomy-engine";

const DEG = Math.PI / 180;
const MOON_RADIUS_KM = 1737.4; // IAU mean radius
const AU_KM = 149597870.7;

// ---- tiny vector helpers ([x, y, z] arrays) ----
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];
const len = (a) => Math.hypot(a[0], a[1], a[2]);

// Passive frame rotations (same convention as the IAU / SPICE formulas)
const rotZ = (v, t) => {
  const c = Math.cos(t), s = Math.sin(t);
  return [c * v[0] + s * v[1], -s * v[0] + c * v[1], v[2]];
};
const rotX = (v, t) => {
  const c = Math.cos(t), s = Math.sin(t);
  return [v[0], c * v[1] + s * v[2], -s * v[1] + c * v[2]];
};

// J2000 equatorial vector -> Moon body-fixed vector (x = 0° meridian, y = east, z = north pole)
// Formula: R = Rz(W) · Rx(90° − dec) · Rz(90° + ra)
function toBodyFixed(vEqj, axis) {
  const n = axis.north;
  const ra = Math.atan2(n.y, n.x);
  const dec = Math.asin(n.z / Math.hypot(n.x, n.y, n.z));
  const W = axis.spin * DEG;
  return rotZ(rotX(rotZ(vEqj, Math.PI / 2 + ra), Math.PI / 2 - dec), W);
}

const wrap180 = (d) => ((((d + 180) % 360) + 360) % 360) - 180;

/**
 * Sun and Earth altitude/azimuth (degrees) for a lunar site at a given time.
 * site = { lat, lon } in degrees (lat north positive, lon east positive).
 * Azimuth: 0 = north, 90 = east. Altitude: 0 = horizon, 90 = overhead.
 */
export function skyAt(date, site, { withCheck = false } = {}) {
  const axis = Astronomy.RotationAxis(Astronomy.Body.Moon, date);

  const m = Astronomy.GeoMoon(date); // Earth -> Moon, AU, J2000 equatorial
  const s = Astronomy.GeoVector(Astronomy.Body.Sun, date, false); // Earth -> Sun
  const moonKm = [m.x * AU_KM, m.y * AU_KM, m.z * AU_KM];
  const sunKm = [s.x * AU_KM, s.y * AU_KM, s.z * AU_KM];

  // Vectors from the Moon's centre, in the Moon's body-fixed frame
  const earthBf = toBodyFixed(scale(moonKm, -1), axis);
  const sunBf = toBodyFixed(sub(sunKm, moonKm), axis);

  // Local frame at the site
  const lat = site.lat * DEG;
  const lon = site.lon * DEG;
  const up = [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
  const east = [-Math.sin(lon), Math.cos(lon), 0];
  const north = [-Math.sin(lat) * Math.cos(lon), -Math.sin(lat) * Math.sin(lon), Math.cos(lat)];
  const sitePos = scale(up, MOON_RADIUS_KM);

  // Direction from the site (on the surface) to a body, not from the Moon's centre
  const altAz = (bodyBf) => {
    const d = sub(bodyBf, sitePos);
    const alt = Math.asin(dot(d, up) / len(d)) / DEG;
    let az = Math.atan2(dot(d, east), dot(d, north)) / DEG;
    az = (az + 360) % 360;
    return { alt, az };
  };

  const result = { sun: altAz(sunBf), earth: altAz(earthBf) };

  if (withCheck) {
    // Cross-check: where does our frame say Earth sits in the Moon's sky (libration)?
    // Compare with the library's independent libration model.
    const lib = Astronomy.Libration(date);
    const lonE = Math.atan2(earthBf[1], earthBf[0]) / DEG;
    const latE = Math.asin(earthBf[2] / len(earthBf)) / DEG;
    const dLat = latE - lib.elat;
    const dLon = wrap180(lonE - lib.elon);
    result.check = {
      dLat,
      dLon,
      maxDiff: Math.max(Math.abs(dLat), Math.abs(dLon)),
      ok: Math.abs(dLat) < 1 && Math.abs(dLon) < 1,
    };
  }
  return result;
}

/** Positions every `stepHours` for the next `days` days, starting at `start`. */
export function skyTrail(start, site, days = 30, stepHours = 12) {
  const out = [];
  const steps = Math.round((days * 24) / stepHours);
  for (let i = 0; i <= steps; i++) {
    const d = new Date(start.getTime() + i * stepHours * 3600 * 1000);
    out.push({ t: d, ...skyAt(d, site) });
  }
  return out;
}