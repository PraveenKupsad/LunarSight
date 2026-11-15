import { useEffect, useRef } from "react";
import * as Cesium from "cesium";

const MOON = Cesium.Ellipsoid.MOON;
const toDeg = Cesium.Math.toDegrees;

// Make Cesium treat everything as the Moon (ignored by older Cesium versions)
try {
  Cesium.Ellipsoid.default = MOON;
} catch {
  /* older Cesium: no default setter, safe to ignore */
}

const TILE_URL =
  "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{y}/{x}.jpg";

export default function MoonGlobe({ viewMode, selected, candidates = [], onSelect, onHover }) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const onSelectRef = useRef(onSelect);
  const onHoverRef = useRef(onHover);
  onSelectRef.current = onSelect; // keeps handlers fresh without recreating the viewer
  onHoverRef.current = onHover;

  // 1) create the viewer once
  useEffect(() => {
    const viewer = new Cesium.Viewer(containerRef.current, {
      baseLayer: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      globe: new Cesium.Globe(MOON),
    });

    const scene = viewer.scene;
    // These objects may not exist for a non-Earth ellipsoid, so check first
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = false;
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    if (scene.skyBox) scene.skyBox.show = true; // star background if available
    if (scene.globe) {
      scene.globe.showGroundAtmosphere = false;
      scene.globe.enableLighting = false;
    }
    scene.backgroundColor = Cesium.Color.BLACK;

    viewer.imageryLayers.addImageryProvider(
      new Cesium.UrlTemplateImageryProvider({
        url: TILE_URL,
        tilingScheme: new Cesium.GeographicTilingScheme({ ellipsoid: MOON }),
        maximumLevel: 7, // verify with the layer's WMTSCapabilities.xml
        credit: "NASA Moon Trek / LRO WAC",
      })
    );

    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(0, -60, 9_000_000, MOON),
    });

    const pick = (pos) => {
      const cart = viewer.camera.pickEllipsoid(pos, MOON);
      if (!cart) return null;
      const c = Cesium.Cartographic.fromCartesian(cart, MOON);
      return { lat: toDeg(c.latitude), lon: toDeg(c.longitude) };
    };

    const handler = new Cesium.ScreenSpaceEventHandler(scene.canvas);
    handler.setInputAction((e) => {
      const p = pick(e.position);
      if (p) onSelectRef.current?.(p);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction((e) => {
      onHoverRef.current?.(pick(e.endPosition));
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    viewerRef.current = viewer;
    return () => {
      handler.destroy();
      viewer.destroy();
      viewerRef.current = null;
    };
  }, []);

  // 2) view switching
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    if (viewMode === "south" || viewMode === "north") {
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(0, viewMode === "south" ? -90 : 90, 4_500_000, MOON),
        orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
        duration: 1.5,
      });
    } else {
      v.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(0, 0, 9_000_000, MOON),
        duration: 1.5,
      });
    }
  }, [viewMode]);

  // 3) markers (+ fly-to for preset sites)
  useEffect(() => {
    const v = viewerRef.current;
    if (!v) return;
    v.entities.removeAll();
    const add = (p, color) =>
      v.entities.add({
        position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat, 0, MOON),
        point: { pixelSize: 12, color, outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
        label: p.name
          ? {
              text: p.name,
              font: "14px sans-serif",
              showBackground: true,
              pixelOffset: new Cesium.Cartesian2(0, -22),
            }
          : undefined,
      });
    candidates.forEach((p) => add(p, Cesium.Color.CYAN));
    if (selected) {
      add(selected, Cesium.Color.ORANGE);
      if (selected.fly) {
        v.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(selected.lon, selected.lat, 600_000, MOON),
          orientation: { heading: 0, pitch: -Cesium.Math.PI_OVER_TWO, roll: 0 },
          duration: 2,
        });
      }
    }
  }, [selected, candidates]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}