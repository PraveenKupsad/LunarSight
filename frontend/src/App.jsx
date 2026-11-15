import { Routes, Route } from "react-router-dom";
import Layout from "./components/layout";
import Home from "./pages/home";
import Explorer from "./pages/explorer";
import Compare from "./pages/compare";
import Visualization from "./pages/visualization";
import Report from "./pages/report";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/explorer" element={<Explorer />} />
        <Route path="/visualization" element={<Visualization />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/report" element={<Report />} />
      </Route>
    </Routes>
  );
}