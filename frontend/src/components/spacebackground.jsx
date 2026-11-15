import { useEffect, useRef } from "react";

// ---- Tuning knobs -------------------------------------------------------
const CONFIG = {
  starDensity: 1800,        // lower = more stars (pixels of screen per star)
  maxStars: 1200,
  parallax: 0.06,           // how much stars shift with the cursor
  idleAfterMs: 4000,        // start auto-drift after this much inactivity
  shootingStarsPerSec: 0.4,
  satellitesPerSec: 0.05,
  motes: 18,                // large soft floating particles
  constellationRadius: 280, // cursor reach for star links (px)
  constellationLink: 180,   // max distance between linked stars (px)
};
// -------------------------------------------------------------------------

const TAU = Math.PI * 2;
const rand = (a, b) => a + Math.random() * (b - a);
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

export default function SpaceBackground() {
  const canvasRef = useRef(null);
  const coordsRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let w = 0, h = 0, dpr = 1;
    let raf = 0, last = 0, t = 0;
    let lastMove = 0, link = 0, resizeTimer = 0;
    let mouse = { x: 0, y: 0 };
    let smooth = { x: 0, y: 0 };
    let stars = [], bright = [], motes = [], shooters = [], satellites = [];
    let backdrop = null;

    // ---- Static layer: Milky Way band + dust clouds (drawn once) ----------
    const buildBackdrop = () => {
      const c = document.createElement("canvas");
      c.width = Math.floor(w * dpr);
      c.height = Math.floor(h * dpr);
      const g = c.getContext("2d");
      g.scale(dpr, dpr);

      g.save();
      g.translate(w * 0.5, h * 0.5);
      g.rotate(-0.45);
      const bandH = Math.max(h * 0.5, 280);

      const band = g.createLinearGradient(0, -bandH / 2, 0, bandH / 2);
      band.addColorStop(0, "rgba(120,140,255,0)");
      band.addColorStop(0.5, "rgba(170,160,255,0.28)");
      band.addColorStop(1, "rgba(120,140,255,0)");
      g.fillStyle = band;
      g.fillRect(-w, -bandH / 2, w * 2, bandH);

      for (let i = 0; i < 46; i++) {
        const x = rand(-w * 0.8, w * 0.8);
        const y = rand(-bandH * 0.35, bandH * 0.35);
        const r = rand(60, 220);
        const hue = pick([250, 220, 300, 30]);
        const rg = g.createRadialGradient(x, y, 0, x, y, r);
        rg.addColorStop(0, `hsla(${hue},70%,65%,0.14)`);
        rg.addColorStop(1, `hsla(${hue},70%,65%,0)`);
        g.fillStyle = rg;
        g.beginPath();
        g.arc(x, y, r, 0, TAU);
        g.fill();
      }

      // fine star dust, denser toward the middle of the band
      const dust = Math.floor((w * h) / 260);
      for (let i = 0; i < dust; i++) {
        const y = ((Math.random() + Math.random() + Math.random()) / 3 - 0.5) * bandH * 0.9;
        const x = rand(-w, w);
        g.fillStyle = `rgba(220,225,255,${rand(0.15, 0.6)})`;
        const s = rand(0.3, 0.8);
        g.fillRect(x, y, s, s);
      }
      g.restore();
      return c;
    };

    // ---- (Re)build everything that depends on screen size -----------------
    const init = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (!mouse.x && !mouse.y) {
        mouse = { x: w / 2, y: h / 2 };
        smooth = { x: w / 2, y: h / 2 };
      }

      const count = Math.min(Math.floor((w * h) / CONFIG.starDensity), CONFIG.maxStars);
      stars = Array.from({ length: count }, () => {
        const depth = Math.random(); // 0 = far, 1 = near
        const roll = Math.random();
        const hue = roll < 0.12 ? 38 : roll < 0.3 ? 215 : roll < 0.36 ? 15 : 0;
        const x = rand(0, w);
        const y = rand(0, h);
        return {
          x, y, px: x, py: y,
          r: 0.3 + depth * 1.3,
          depth,
          speed: 0.008 + depth * 0.07,
          phase: rand(0, TAU),
          tw: rand(0.6, 2.6),
          hue,
          sat: hue ? 90 : 0,
        };
      });
      bright = stars.filter((s) => s.r > 1.1).slice(0, 80);

      motes = Array.from({ length: CONFIG.motes }, () => ({
        x: rand(0, w), y: rand(0, h),
        r: rand(20, 70),
        depth: rand(0.5, 1),
        vx: rand(-6, 6), vy: rand(-3, 3),
        a: rand(0.04, 0.09),
        hue: pick([215, 260, 30]),
      }));

      backdrop = buildBackdrop();
    };

    // ---- One frame --------------------------------------------------------
    const render = (dt) => {
      const now = performance.now();
      t += dt;
      const k = dt * 60; // 1 at 60 fps, keeps speeds frame-rate independent

      // smooth camera: follows the cursor, drifts on its own when idle
      const idle = now - lastMove > CONFIG.idleAfterMs;
      const tx = idle ? w / 2 + Math.sin(t * 0.15) * w * 0.15 : mouse.x;
      const ty = idle ? h / 2 + Math.cos(t * 0.11) * h * 0.1 : mouse.y;
      smooth.x += (tx - smooth.x) * Math.min(1, 0.05 * k);
      smooth.y += (ty - smooth.y) * Math.min(1, 0.05 * k);
      link += ((idle ? 0 : 1) - link) * Math.min(1, 0.06 * k);

      ctx.clearRect(0, 0, w, h);

      // backdrop (Milky Way) with a tiny parallax shift
      ctx.drawImage(
        backdrop,
        (smooth.x - w / 2) * 0.006,
        (smooth.y - h / 2) * 0.006,
        w,
        h
      );

      // stars
      for (const s of stars) {
        s.y += s.speed * k;
        if (s.y > h + 2) { s.y = -2; s.x = rand(0, w); }
        const px = s.x + (smooth.x - w / 2) * s.depth * CONFIG.parallax;
        const py = s.y + (smooth.y - h / 2) * s.depth * CONFIG.parallax;
        s.px = px;
        s.py = py;
        const alpha = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * s.tw + s.phase));
        const col = `${s.hue},${s.sat}%,92%`;

        ctx.fillStyle = `hsla(${col},${alpha})`;
        ctx.beginPath();
        ctx.arc(px, py, s.r, 0, TAU);
        ctx.fill();

        if (s.r > 1.3) {
          ctx.fillStyle = `hsla(${col},${alpha * 0.12})`;
          ctx.beginPath();
          ctx.arc(px, py, s.r * 4, 0, TAU);
          ctx.fill();
        }
        if (s.r > 1.45) {
          ctx.strokeStyle = `hsla(${col},${alpha * 0.35})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(px - s.r * 5, py);
          ctx.lineTo(px + s.r * 5, py);
          ctx.moveTo(px, py - s.r * 5);
          ctx.lineTo(px, py + s.r * 5);
          ctx.stroke();
        }
      }

      // interactive constellations around the cursor
      if (link > 0.02) {
        const near = bright.filter(
          (s) => Math.hypot(s.px - smooth.x, s.py - smooth.y) < CONFIG.constellationRadius
        );
        ctx.lineWidth = 0.7;
        for (let i = 0; i < near.length; i++) {
          for (let j = i + 1; j < near.length; j++) {
            const d = Math.hypot(near[i].px - near[j].px, near[i].py - near[j].py);
            if (d < CONFIG.constellationLink) {
              ctx.strokeStyle = `rgba(150,190,255,${(1 - d / CONFIG.constellationLink) * 0.35 * link})`;
              ctx.beginPath();
              ctx.moveTo(near[i].px, near[i].py);
              ctx.lineTo(near[j].px, near[j].py);
              ctx.stroke();
            }
          }
        }
      }

      // floating dust motes (foreground depth)
      for (const m of motes) {
        m.x += m.vx * dt;
        m.y += m.vy * dt;
        if (m.x < -m.r) m.x = w + m.r;
        if (m.x > w + m.r) m.x = -m.r;
        if (m.y < -m.r) m.y = h + m.r;
        if (m.y > h + m.r) m.y = -m.r;
        const mx = m.x + (smooth.x - w / 2) * m.depth * 0.05;
        const my = m.y + (smooth.y - h / 2) * m.depth * 0.05;
        const g = ctx.createRadialGradient(mx, my, 0, mx, my, m.r);
        g.addColorStop(0, `hsla(${m.hue},80%,75%,${m.a})`);
        g.addColorStop(1, `hsla(${m.hue},80%,75%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(mx, my, m.r, 0, TAU);
        ctx.fill();
      }

      // shooting stars
      if (Math.random() < dt * CONFIG.shootingStarsPerSec) {
        const ang = rand(0.35, 0.75);
        const sp = rand(650, 1000);
        shooters.push({
          x: rand(-w * 0.1, w * 0.7),
          y: rand(0, h * 0.4),
          vx: Math.cos(ang) * sp,
          vy: Math.sin(ang) * sp,
          life: 1,
          len: rand(0.1, 0.16),
        });
      }
      for (const c of shooters) {
        const tx2 = c.x - c.vx * c.len;
        const ty2 = c.y - c.vy * c.len;
        const grad = ctx.createLinearGradient(c.x, c.y, tx2, ty2);
        grad.addColorStop(0, `rgba(255,255,255,${c.life})`);
        grad.addColorStop(0.3, `rgba(180,210,255,${c.life * 0.4})`);
        grad.addColorStop(1, "rgba(180,210,255,0)");
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(c.x, c.y);
        ctx.lineTo(tx2, ty2);
        ctx.stroke();

        const glow = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, 7);
        glow.addColorStop(0, `rgba(255,255,255,${c.life * 0.9})`);
        glow.addColorStop(1, "rgba(255,255,255,0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(c.x, c.y, 7, 0, TAU);
        ctx.fill();

        c.x += c.vx * dt;
        c.y += c.vy * dt;
        c.life -= dt * 0.85;
      }
      shooters = shooters.filter((c) => c.life > 0 && c.x < w + 100 && c.y < h + 100);

      // satellite
      if (satellites.length < 1 && Math.random() < dt * CONFIG.satellitesPerSec) {
        const dir = Math.random() < 0.5 ? 1 : -1;
        satellites.push({
          x: dir > 0 ? -20 : w + 20,
          y: rand(h * 0.08, h * 0.45),
          vx: dir * rand(35, 60),
          vy: rand(-6, 6),
          ph: rand(0, TAU),
        });
      }
      for (const s of satellites) {
        const blink = 0.5 + 0.5 * Math.sin(t * 3 + s.ph);
        ctx.strokeStyle = "rgba(255,255,255,0.08)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(s.x - s.vx * 0.8, s.y - s.vy * 0.8);
        ctx.lineTo(s.x, s.y);
        ctx.stroke();
        ctx.fillStyle = `rgba(255,255,255,${0.35 + 0.5 * blink})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, 1.3, 0, TAU);
        ctx.fill();
        s.x += s.vx * dt;
        s.y += s.vy * dt;
      }
      satellites = satellites.filter((s) => s.x > -40 && s.x < w + 40);
    };

    // ---- Loop control -----------------------------------------------------
    const loop = (now) => {
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      render(dt);
      raf = requestAnimationFrame(loop);
    };
    const start = () => {
      if (reduceMotion || raf) return;
      last = performance.now();
      raf = requestAnimationFrame(loop);
    };
    const stop = () => {
      cancelAnimationFrame(raf);
      raf = 0;
    };

    // ---- Events -----------------------------------------------------------
    const onMove = (e) => {
      mouse = { x: e.clientX, y: e.clientY };
      lastMove = performance.now();
      // Simulated readout: derived from the mouse position on screen, NOT real lunar data
      if (coordsRef.current) {
        const lat = 85 + (e.clientY / h) * 5;
        const lon = (e.clientX / w) * 360 - 180;
        coordsRef.current.textContent =
          `${lat.toFixed(3)}° S   ${Math.abs(lon).toFixed(3)}° ${lon < 0 ? "W" : "E"}`;
      }
    };
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        init();
        if (reduceMotion) render(0);
      }, 150);
    };
    const onVisibility = () => (document.hidden ? stop() : start());

    init();
    if (reduceMotion) render(0); // one static frame, no animation
    else start();

    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      clearTimeout(resizeTimer);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div className="space-bg" aria-hidden="true">
      <div className="nebula" />
      <canvas ref={canvasRef} className="space-canvas" />
      <div className="earth" />

      {/* Lunar surface (generated in code, optional photo on top) */}
      <div className="lunar-surface">
        <svg className="moon-texture" width="100%" height="100%" preserveAspectRatio="none">
          <filter id="rough" x="0" y="0" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.010 0.016" numOctaves="5" seed="11" />
            <feColorMatrix
              type="matrix"
              values="0 0 0 0 0.66
                      0 0 0 0 0.68
                      0 0 0 0 0.76
                      0 0 0 1.5 -0.55"
            />
          </filter>
          <rect width="100%" height="100%" filter="url(#rough)" />
        </svg>
        <div className="craters" />
        <div className="lunar-photo" />
      </div>

      <div className="vignette" />

      {/* HUD: simulated readout, clearly labelled as not real data */}
      <div
        className="hud-corner"
        title="Simulated readout. These numbers follow your mouse position and are not real lunar coordinates. Use the Explorer page for real site coordinates."
      >
        <span className="hud-label">ILLUSTRATIVE · SOUTH POLAR REGION</span>
        <span className="hud-coords" ref={coordsRef}>90.000° S   0.000° E</span>
        <span className="hud-note">simulated · not real lunar coordinates</span>
      </div>
    </div>
  );
}