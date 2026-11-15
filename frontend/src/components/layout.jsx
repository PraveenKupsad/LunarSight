import { Outlet } from "react-router-dom";
import Navbar from "./navbar";
import SpaceBackground from "./spacebackground";

export default function Layout() {
  return (
    <>
      <SpaceBackground />
      <Navbar />
      <main className="page">
        <Outlet />
      </main>
      <footer className="footer">
        Data: NASA LOLA, LROC, SPICE, Moon Trek · NASA Space Apps Challenge 2026
      </footer>
    </>
  );
}