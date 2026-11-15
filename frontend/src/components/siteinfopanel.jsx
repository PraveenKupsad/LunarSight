import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { analyzeSite } from "../services/api";
import { useSelection } from "../context/selectioncontext";
import { CANDIDATE_SITES } from "../mock/sites";
import {
  fmtLat, fmtLon, toDMS, haversineKm, distanceToPoleKm, moonSide, regionLabel,
} from "../utils/format";
import "./siteinfopanel.css";

const DASH = "—";
const num = (v, unit = "", digits = 1) =>
  v == null || Number.isNaN(Number(v)) ? DASH : `${Number(v).toFixed(digits)}${unit}`;
const yesNo = (v) => (v == null ? DASH : v ? "Yes" : "No");
const hours = (h) =>
  h == null ? DASH : h < 48 ? `${Number(h).toFixed(1)} h` : `${(h / 24).toFixed(1)} days`;

const scoreLabel = (s) =>
  s >= 8 ? "Excellent" : s >= 6.5 ? "Good" : s >= 5 ? "Fair" : "Challenging";

const BREAKDOWN_LABELS = {
  power: "Power (sunlight)",
  comms: "Communication",
  terrain: "Terrain safety",
  resources: "Resource access",
};

function Section({ title, children }) {
  return (
    <section className="sip-section">
      <h4>{title}</h4>
      <dl>{children}</dl>
    </section>
  );
}

function Row({ label, value }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function Meter({ value, max = 10 }) {
  const pct = Math.max(0, Math.min(100, ((value ?? 0) / max) * 100));
  return (
    <div className="sip-meter">
      <div className="sip-meter-fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function SiteInfoPanel() {
  const {
    selectedSite: site, dateTime, candidates, addCandidate, removeCandidate,
  } = useSelection();
  const [state, setState] = useState({ status: "idle" });
  const [retry, setRetry] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!site) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    analyzeSite({ lat: site.lat, lon: site.lon, datetime: dateTime })
      .then((data) => !cancelled && setState({ status: "ok", data }))
      .catch((e) => !cancelled && setState({ status: "error", message: e.message }));
    return () => {
      cancelled = true;
    };
  }, [site?.lat, site?.lon, dateTime, retry]);

  // Computed in the browser, so it is real data and shows instantly
  const geo = useMemo(() => {
    if (!site) return null;
    let nearest = null;
    for (const c of CANDIDATE_SITES) {
      const km = haversineKm(site, c);
      if (!nearest || km < nearest.km) nearest = { name: c.name, km };
    }
    return {
      poleKm: distanceToPoleKm(site.lat),
      side: moonSide(site.lon),
      region: regionLabel(site.lat),
      nearest,
    };
  }, [site?.lat, site?.lon]);

  if (!site) {
    return (
      <aside className="panel sip">
        <p className="sip-empty">
          Click anywhere on the Moon, or choose a candidate site, to see its details.
        </p>
      </aside>
    );
  }

  const d = state.data;
  const isMock = d?.meta?.source === "mock";
  const isAdded = candidates.some(
    (c) => Math.abs(c.lat - site.lat) < 0.01 && Math.abs(c.lon - site.lon) < 0.01
  );

  const strengths = [];
  const risks = [];
  if (d?.breakdown) {
    for (const [key, val] of Object.entries(d.breakdown)) {
      if (val >= 7) strengths.push(BREAKDOWN_LABELS[key] || key);
      else if (val <= 5) risks.push(BREAKDOWN_LABELS[key] || key);
    }
  }

  const copyCoords = async () => {
    try {
      await navigator.clipboard.writeText(`${site.lat.toFixed(4)}, ${site.lon.toFixed(4)}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked, ignore */
    }
  };

  return (
    <aside className="panel sip">
      <header className="sip-header">
        <h3>{site.name || "Selected location"}</h3>
        {isMock && <span className="sip-badge">Demo data</span>}
      </header>
      <p className="sip-sub">
        Analysis time (UTC): {new Date(dateTime).toISOString().replace("T", " ").slice(0, 16)}
      </p>

      <Section title="📍 Location">
        <Row label="Latitude" value={fmtLat(site.lat)} />
        <Row label="Longitude" value={fmtLon(site.lon)} />
        <Row label="Decimal" value={`${site.lat.toFixed(4)}, ${site.lon.toFixed(4)}`} />
        <Row label="DMS" value={`${toDMS(site.lat, "N", "S")}, ${toDMS(site.lon, "E", "W")}`} />
        <Row label="Region" value={geo.region} />
        <Row label="Side of Moon" value={geo.side} />
        <Row label="Distance to pole" value={`${geo.poleKm.toFixed(1)} km`} />
        {geo.nearest && (
          <Row
            label="Nearest candidate"
            value={
              geo.nearest.km < 1
                ? geo.nearest.name
                : `${geo.nearest.name} (${geo.nearest.km.toFixed(0)} km)`
            }
          />
        )}
      </Section>

      {state.status === "loading" && <p className="sip-note">Analysing site…</p>}

      {state.status === "error" && (
        <div className="sip-error" role="alert">
          Could not load site data: {state.message}
          <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
        </div>
      )}

      {state.status === "ok" && d && (
        <>
          <Section title="⛰️ Terrain">
            <Row label="Terrain type" value={d.site?.terrain ?? DASH} />
            <Row label="Elevation" value={num(d.site?.elevationM, " m", 0)} />
            <Row label="Slope" value={num(d.site?.slopeDeg, "°")} />
            <Row label="Nearest shadowed area" value={num(d.site?.psrDistanceKm, " km")} />
            <Row label="Ice likelihood" value={d.site?.iceLikelihood ?? DASH} />
          </Section>

          <Section title="☀️ Sun & illumination">
            <Row label="Sun altitude" value={num(d.sun?.altitudeDeg, "°")} />
            <Row label="Sun azimuth" value={num(d.sun?.azimuthDeg, "°", 0)} />
            <Row label="Sunlit now" value={yesNo(d.sun?.sunlit)} />
            <Row
              label={d.sun?.sunlit ? "Until sunset" : "Until sunrise"}
              value={hours(d.sun?.nextChangeHours)}
            />
            <Row label="Illumination" value={num(d.illumination?.percent, "%", 0)} />
            <Row label="Longest sunlight" value={num(d.sun?.longestSunlightDays, " days")} />
            <Row label="Longest darkness" value={num(d.sun?.longestDarknessDays, " days")} />
          </Section>

          <Section title="🌍 Earth & communication">
            <Row label="Earth altitude" value={num(d.earthVisibility?.altitudeDeg, "°")} />
            <Row label="Earth azimuth" value={num(d.earthVisibility?.azimuthDeg, "°", 0)} />
            <Row label="Earth visible now" value={yesNo(d.earthVisibility?.visibleNow)} />
            <Row label="Visibility" value={num(d.earthVisibility?.percent, "%", 0)} />
            <Row label="Next visibility window" value={hours(d.earthVisibility?.nextWindowHours)} />
            <Row label="Direct link to Earth" value={yesNo(d.communication?.directToEarth)} />
            <Row label="Relay satellite needed" value={yesNo(d.communication?.relayNeeded)} />
            <Row label="One-way signal delay" value={num(d.communication?.oneWayDelayS, " s")} />
          </Section>

          {d.environment && (
            <Section title="🌡️ Environment (estimate)">
              <Row label="Daytime surface" value={num(d.environment.dayTempC, " °C", 0)} />
              <Row label="Night surface" value={num(d.environment.nightTempC, " °C", 0)} />
            </Section>
          )}

          <section className="sip-section">
            <h4>🎯 Suitability</h4>
            <div className="sip-score">
              <span className="sip-score-num">{num(d.score, "", 1)}</span>
              <span className="sip-score-max">/ 10</span>
              {d.score != null && <span className="sip-score-label">{scoreLabel(d.score)}</span>}
            </div>
            <Meter value={d.score} />

            {d.breakdown && (
              <ul className="sip-breakdown">
                {Object.entries(d.breakdown).map(([key, val]) => (
                  <li key={key}>
                    <span>{BREAKDOWN_LABELS[key] || key}</span>
                    <span>{num(val, "", 1)}</span>
                    <Meter value={val} />
                  </li>
                ))}
              </ul>
            )}

            {strengths.length > 0 && (
              <p className="sip-tags good">✔ Strengths: {strengths.join(", ")}</p>
            )}
            {risks.length > 0 && <p className="sip-tags bad">⚠ Risks: {risks.join(", ")}</p>}
            {d.explanation && <p className="sip-explain">{d.explanation}</p>}
          </section>

          {isMock && (
            <p className="sip-note">
              Values marked as demo data are placeholders until the backend is connected. Only
              the Location section is calculated from the real coordinates.
            </p>
          )}
        </>
      )}

      <div className="sip-actions">
        {isAdded ? (
          <button className="secondary" onClick={() => removeCandidate(site)}>
            Remove from compare
          </button>
        ) : (
          <button disabled={candidates.length >= 2} onClick={() => addCandidate(site)}>
            Add to compare ({candidates.length}/2)
          </button>
        )}
        <button className="secondary" onClick={copyCoords}>
          {copied ? "Copied ✓" : "Copy coordinates"}
        </button>
        <Link className="sip-link" to="/visualization">
          View Sun & Earth →
        </Link>
      </div>
    </aside>
  );
}