import { NavLink } from "react-router-dom";

export default function Navbar() {
  return (
    <nav className="navbar">
      <span className="logo">🌙 LunarSight</span>
      <div className="nav-links">
        <NavLink to="/" end>Home</NavLink>
        <NavLink to="/explorer">Explorer</NavLink>
        <NavLink to="/visualization">Sun &amp; Earth</NavLink>
        <NavLink to="/compare">Compare</NavLink>
        <NavLink to="/report">Report</NavLink>
      </div>
    </nav>
  );
}