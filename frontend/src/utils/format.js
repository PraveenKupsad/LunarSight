export const MOON_RADIUS_KM = 1737.4;

export const fmtLat = (lat) => `${Math.abs(lat).toFixed(3)}° ${lat < 0 ? "S" : "N"}`;
export const fmtLon = (lon) => `${Math.abs(lon).toFixed(3)}° ${lon < 0 ? "W" : "E"}`;

// 12.3456 -> 12° 20′ 44.2″ N
export function toDMS(value, pos, neg) {
  const hemi = value < 0 ? neg : pos;
  const total = Math.round(Math.abs(value) * 36000) / 10; // arc-seconds, 0.1 precision
  const d = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = (total % 60).toFixed(1);
  return `${d}° ${m}′ ${s}″ ${hemi}`;
}

const rad = (deg) => (deg * Math.PI) / 180;

// Great-circle distance on the Moon, in km
export function haversineKm(a, b) {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * MOON_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

// Surface distance from the nearest pole, in km
export const distanceToPoleKm = (lat) => rad(90 - Math.abs(lat)) * MOON_RADIUS_KM;

export function moonSide(lon) {
  const l = ((((lon + 180) % 360) + 360) % 360) - 180; // normalise to [-180, 180]
  return Math.abs(l) <= 90 ? "Near side (faces Earth)" : "Far side";
}

export function regionLabel(lat) {
  const a = Math.abs(lat);
  const hemi = lat < 0 ? "South" : "North";
  if (a >= 85) return `${hemi} polar cap`;
  if (a >= 80) return `${hemi} polar region`;
  if (a >= 60) return `${hemi} high latitude`;
  if (a >= 30) return `${hemi} mid-latitude`;
  return "Equatorial band";
}