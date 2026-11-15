import { useEffect, useMemo, useState } from "react";
import { skyAt, skyTrail } from "../utils/lunarsky";
import "./realskydial.css";

// Default site: just off the lunar south pole (azimuth is undefined exactly at the pole)
const DEFAULT_SITE = { name: "Near the south pole", lat: -89.9, lon: 0 };

const SIZE = 440;
const C = SIZE / 2;
const R = 150; // horizon radius

const SUN_HALF = 0.27;   // Sun's apparent radius, degrees
const EARTH_HALF = 0.95; // Earth's apparent radius seen from the Moon, degrees

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (az) => COMPASS[Math.round(az / 22.5) % 16];

const signed = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}°`;
const fmtLat = (lat) => `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? "S" : "N"}`;
const fmtLon = (lon) => `${Math.abs(lon).toFixed(2)}° ${lon < 0 ? "W" : "E"}`;

function status(alt, half) {
  if (alt > half) return { label: "Above horizon", cls: "up" };
  if (alt > -half) return { label: "On the horizon", cls: "edge" };
  return { label: "Below horizon", cls: "down" };
}

// All-sky view looking up: zenith at the centre, horizon on the rim, north at the top, east on the LEFT.
function place(alt, az) {
  const a = (az * Math.PI) / 180;
  const r = alt >= 0 ? (R * (90 - Math.min(alt, 90))) / 90 : R + Math.min(-alt, 6) * 6;
  return { x: C - r * Math.sin(a), y: C - r * Math.cos(a) };
}

export default function RealSkyDial({ site = DEFAULT_SITE }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 10000);
    return () => clearInterval(id);
  }, []);

  const tick = Math.floor(now.getTime() / 10000);
  const trailTick = Math.floor(now.getTime() / 900000); // refresh the 30-day trail every 15 min

  const sky = useMemo(() => {
    try {
      return { data: skyAt(new Date(tick * 10000), site, { withCheck: true }) };
    } catch (e) {
      return { error: e.message };
    }
  }, [tick, site.lat, site.lon]);

  const trail = useMemo(() => {
    try {
      return skyTrail(new Date(trailTick * 900000), site);
    } catch {
      return [];
    }
  }, [trailTick, site.lat, site.lon]);

  const siteLabel = site.name || "Selected site";
  const utc = now.toISOString().replace("T", " ").slice(0, 19);

  if (sky.error) {
    return (
      <div className="rsd">
        <div className="rsd-head"><span>Sky view</span><span>Live</span></div>
        <p className="rsd-error">Could not compute the sky: {sky.error}</p>
      </div>
    );
  }

  const { sun, earth, check } = sky.data;
  const sunPos = place(sun.alt, sun.az);
  const earthPos = place(earth.alt, earth.az);
  const sunSt = status(sun.alt, SUN_HALF);
  const earthSt = status(earth.alt, EARTH_HALF);

  return (
    <div className="rsd">
      <div className="rsd-head">
        <span>Sky view · live</span>
        <span className="rsd-live">● computed</span>
      </div>

      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
        aria-label={`Sun and Earth positions in the sky at ${siteLabel}`}>
        {/* rings: horizon, 30°, 60° altitude */}
        <circle cx={C} cy={C} r={R} className="rsd-horizon" />
        <circle cx={C} cy={C} r={(R * 2) / 3} className="rsd-ring" />
        <circle cx={C} cy={C} r={R / 3} className="rsd-ring" />
        <line x1={C} y1={C - R} x2={C} y2={C + R} className="rsd-axis" />
        <line x1={C - R} y1={C} x2={C + R} y2={C} className="rsd-axis" />

        {/* cardinal directions (east on the left: we are looking up) */}
        <text x={C} y={C - R - 40} className="rsd-card">N</text>
        <text x={C} y={C + R + 52} className="rsd-card">S</text>
        <text x={C - R - 40} y={C + 5} className="rsd-card">E</text>
        <text x={C + R + 40} y={C + 5} className="rsd-card">W</text>

        {/* 30-day trails: one dot every 12 hours */}
        {trail.map((p, i) => {
          const s = place(p.sun.alt, p.sun.az);
          const e = place(p.earth.alt, p.earth.az);
          return (
            <g key={i}>
              <circle cx={s.x} cy={s.y} r="1.8"
                className={p.sun.alt > -SUN_HALF ? "rsd-trail-sun" : "rsd-trail-sun dim"} />
              <circle cx={e.x} cy={e.y} r="1.8"
                className={p.earth.alt > -EARTH_HALF ? "rsd-trail-earth" : "rsd-trail-earth dim"} />
            </g>
          );
        })}

        {/* Sun */}
        <circle cx={sunPos.x} cy={sunPos.y} r="19" className="rsd-sun-halo" />
        <circle cx={sunPos.x} cy={sunPos.y} r="10"
          className={sunSt.cls === "down" ? "rsd-sun hollow" : "rsd-sun"} />

        {/* Earth */}
        <circle cx={earthPos.x} cy={earthPos.y} r="18" className="rsd-earth-halo" />
        <circle cx={earthPos.x} cy={earthPos.y} r="9"
          className={earthSt.cls === "down" ? "rsd-earth hollow" : "rsd-earth"} />
      </svg>

      <div className="rsd-legend">
        <span><i className="dot sun" /> Sun</span>
        <span><i className="dot earth" /> Earth</span>
        <span><i className="dot trail" /> next 30 days (12 h steps)</span>
      </div>

      <div className="rsd-readouts">
        <div className={`rsd-card-box ${sunSt.cls}`}>
          <h5>☀️ Sun</h5>
          <p>Altitude <b>{signed(sun.alt)}</b></p>
          <p>Azimuth <b>{sun.az.toFixed(1)}° {compass(sun.az)}</b></p>
          <p className="rsd-status">{sunSt.label}</p>
        </div>
        <div className={`rsd-card-box ${earthSt.cls}`}>
          <h5>🌍 Earth</h5>
          <p>Altitude <b>{signed(earth.alt)}</b></p>
          <p>Azimuth <b>{earth.az.toFixed(1)}° {compass(earth.az)}</b></p>
          <p className="rsd-status">{earthSt.label}</p>
        </div>
      </div>

      <p className="rsd-meta">
        {siteLabel} · {fmtLat(site.lat)}, {fmtLon(site.lon)} · {utc} UTC
      </p>
      <p className="rsd-foot">
        Computed from ephemerides (astronomy-engine) and the IAU lunar rotation model. Flat horizon,
        terrain not modelled. Looking up: zenith at centre, horizon on the rim, east on the left.{" "}
        {check &&
          (check.ok ? (
            <span className="rsd-ok">Frame cross-check ✓ (Δ {check.maxDiff.toFixed(2)}°)</span>
          ) : (
            <span className="rsd-bad">⚠ Frame cross-check failed (Δ {check.maxDiff.toFixed(2)}°)</span>
          ))}
      </p>
    </div>
  );
}