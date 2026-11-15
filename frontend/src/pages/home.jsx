import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import RealSkyDial from "../components/realskydial";
import { useSelection } from "../context/selectioncontext";

const steps = [
  { icon: "📍", title: "Select a site", text: "Pick a candidate lunar landing location.", to: "/explorer" },
  { icon: "🕒", title: "Choose a time", text: "Set the date and time in UTC." },
  { icon: "🌞", title: "See Sun & Earth", text: "Check altitude, azimuth and visibility." },
  { icon: "⚖️", title: "Compare", text: "Evaluate two sites side by side." },
];

const features = [
  { icon: "🗺️", title: "Site Explorer", text: "Browse candidate sites on an interactive Moon map." },
  { icon: "🧭", title: "Sun & Earth Viewer", text: "A sky dial showing where the Sun and Earth sit above the horizon." },
  { icon: "📈", title: "Timelines", text: "See sunlight and Earth contact windows over time." },
  { icon: "📊", title: "Comparison", text: "Rank sites by illumination and communication access." },
];

function UtcClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="hud">
      <i className="dot" /> UTC {now.toISOString().slice(0, 19).replace("T", " ")}
    </span>
  );
}

// Makes the card glow follow the mouse
function glow(e) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
  e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
}

export default function Home() {
  const { selectedSite } = useSelection();

  // Use the site picked on the Explorer page; otherwise the dial uses its default (near the south pole)
  const dialSite = selectedSite
    ? { name: selectedSite.name, lat: selectedSite.lat, lon: selectedSite.lon }
    : undefined;

  return (
    <>
      <section className="hero-grid">
        <div className="hero-text">
          <UtcClock />
          <p className="eyebrow">NASA SPACE APPS 2026 · THE NEXT FRONTIER</p>
          <h1>LunarSight</h1>
          <p>
            Will the Sun and Earth be visible from your lunar landing site?
            Find out before you land.
          </p>
          <div className="hero-actions">
            <Link to="/explorer" className="btn">🚀 Start Exploring</Link>
            <Link to="/compare" className="btn btn-ghost">Compare Sites</Link>
          </div>
        </div>
        <RealSkyDial site={dialSite} />
      </section>

      <section className="stats">
        <div className="stat"><b>Sun</b><span>Power for rovers and habitats</span></div>
        <div className="stat"><b>Earth</b><span>Direct communication link</span></div>
        <div className="stat"><b>2</b><span>Sites compared side by side</span></div>
        <div className="stat"><b>NASA</b><span>Real lunar data</span></div>
      </section>

      <h2 className="section-title">How it works</h2>
      <p className="section-sub">Four simple steps from site to insight</p>
      <section className="grid">
        {steps.map((s, i) => (
          <div className="card" key={s.title} onMouseMove={glow} style={{ animationDelay: `${i * 0.1}s` }}>
            <span className="step-num">0{i + 1}</span>
            <div className="icon">{s.icon}</div>
            <h3>{s.title}</h3>
            <p>{s.text}</p>
          </div>
        ))}
      </section>

      <h2 className="section-title">Key features</h2>
      <p className="section-sub">Everything a mission planner needs</p>
      <section className="grid">
        {features.map((f, i) => (
          <div className="card" key={f.title} onMouseMove={glow} style={{ animationDelay: `${i * 0.1}s` }}>
            <div className="icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.text}</p>
          </div>
        ))}
      </section>

      <h2 className="section-title">Powered by NASA data</h2>
      <p className="section-sub">Built on trusted lunar science resources</p>
      <section className="chips">
        <span className="chip">LOLA Elevation</span>
        <span className="chip">LROC Illumination</span>
        <span className="chip">SPICE Ephemeris</span>
        <span className="chip">Moon Trek</span>
      </section>
    </>
  );
}