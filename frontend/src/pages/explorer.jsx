import "./explorer.css";
import { lazy, Suspense, useState } from "react";
import { useSelection } from "../context/selectioncontext";
import SiteInfoPanel from "../components/siteinfopanel";
import { CANDIDATE_SITES } from "../mock/sites";
import { fmtLat, fmtLon } from "../utils/format";

// Cesium is large, so load the globe only when this page opens
const MoonGlobe = lazy(() => import("../components/moonglobe"));

const VIEWS = [
  ["3d", "3D Globe"],
  ["south", "South Pole"],
  ["north", "North Pole"],
];

export default function Explorer() {
  const { selectedSite, setSelectedSite, candidates } = useSelection();
  const [viewMode, setViewMode] = useState("3d");
  const [hover, setHover] = useState(null);

  return (
    <div className="explorer">
      <div className="explorer-map">
        <div className="map-toolbar">
          {VIEWS.map(([key, label]) => (
            <button
              key={key}
              className={viewMode === key ? "active" : ""}
              onClick={() => setViewMode(key)}
            >
              {label}
            </button>
          ))}

          <select
            defaultValue=""
            onChange={(e) => {
              const site = CANDIDATE_SITES[e.target.value];
              if (site) setSelectedSite({ ...site, fly: true });
            }}
          >
            <option value="" disabled>Candidate sites…</option>
            {CANDIDATE_SITES.map((s, i) => (
              <option key={s.name} value={i}>{s.name}</option>
            ))}
          </select>
        </div>

        <Suspense fallback={<p style={{ padding: 16 }}>Loading Moon…</p>}>
          <MoonGlobe
            viewMode={viewMode}
            selected={selectedSite}
            candidates={candidates}
            onSelect={setSelectedSite}
            onHover={setHover}
          />
        </Suspense>

        <div className="coord-readout">
          {hover ? `${fmtLat(hover.lat)} · ${fmtLon(hover.lon)}` : "Hover over the Moon"}
        </div>
      </div>

      <SiteInfoPanel />
    </div>
  );
}