import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "cesium/Build/CesiumUnminified/Widgets/widgets.css";
import "./index.css";
import "./App.css";
import App from "./App.jsx";
import { SelectionProvider } from "./context/selectioncontext";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <SelectionProvider>
        <App />
      </SelectionProvider>
    </BrowserRouter>
  </StrictMode>
);