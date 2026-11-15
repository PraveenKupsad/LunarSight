const styles = {
  visible: { label: "Above horizon", cls: "ok" },
  hidden: { label: "Below horizon", cls: "bad" },
  unavailable: { label: "Unavailable", cls: "muted" },
  illustrative: { label: "Illustrative", cls: "warn" },
};

export default function StatusBadge({ status }) {
  const s = styles[status] ?? styles.unavailable;
  return <span className={`badge-status ${s.cls}`}>{s.label}</span>;
}