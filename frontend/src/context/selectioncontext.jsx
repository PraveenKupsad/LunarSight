import { createContext, useContext, useState, useCallback, useMemo } from "react";

const SelectionContext = createContext(null);

const sameSite = (a, b) =>
  Math.abs(a.lat - b.lat) < 0.01 && Math.abs(a.lon - b.lon) < 0.01;

export function SelectionProvider({ children }) {
  const [selectedSite, setSelectedSite] = useState(null); // { name?, lat, lon, fly? }
  const [candidates, setCandidates] = useState([]);       // max 2 sites
  const [dateTime, setDateTime] = useState(() => new Date().toISOString());

  const addCandidate = useCallback((site) => {
    setCandidates((list) =>
      list.length >= 2 || list.some((s) => sameSite(s, site))
        ? list
        : [...list, { name: site.name, lat: site.lat, lon: site.lon }]
    );
  }, []);

  const removeCandidate = useCallback((site) => {
    setCandidates((list) => list.filter((s) => !sameSite(s, site)));
  }, []);

  const clearCandidates = useCallback(() => setCandidates([]), []);

  const value = useMemo(
    () => ({
      selectedSite, setSelectedSite,
      candidates, addCandidate, removeCandidate, clearCandidates,
      dateTime, setDateTime,
    }),
    [selectedSite, candidates, dateTime, addCandidate, removeCandidate, clearCandidates]
  );

  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

export function useSelection() {
  const ctx = useContext(SelectionContext);
  if (!ctx) throw new Error("useSelection must be used inside <SelectionProvider>");
  return ctx;
}