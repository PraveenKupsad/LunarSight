import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import cesium from "vite-plugin-cesium";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), cesium()],

  server: {
    proxy: {
      // Flask backend (Member 3). Harmless while the backend is off.
      "/api": {
        target: "http://localhost:5000",
        changeOrigin: true,
      },

      // Only needed if the browser blocks NASA tile requests with a CORS error.
      // If you enable it, change TILE_URL in moonglobe.jsx to start with
      // "/trek/tiles/Moon/EQ/..." instead of "https://trek.nasa.gov/tiles/Moon/EQ/...".
      // "/trek": {
      //   target: "https://trek.nasa.gov",
      //   changeOrigin: true,
      //   rewrite: (path) => path.replace(/^\/trek/, ""),
      // },
    },
  },
});