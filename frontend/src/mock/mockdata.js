export const mockSites = [
  {
    id: "shackleton_rim",
    name: "Shackleton Rim",
    latitude: -89.9,
    longitude: 0.0,
    description: "Rim of Shackleton crater near the south pole",
  },
  {
    id: "malapert_massif",
    name: "Malapert Massif",
    latitude: -85.9,
    longitude: 0.0,
    description: "Mountain near the south pole with Earth visibility",
  },
];

// Fictional values for building the UI only
export const mockSunEarth = {
  sun: { altitude_deg: 4.2, azimuth_deg: 135.0, above_horizon: true },
  earth: { altitude_deg: 2.1, azimuth_deg: 210.0, above_horizon: true },
  calculation_status: "illustrative_example",
};