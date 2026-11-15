export default function LoadingSpinner({ text = "Loading..." }) {
  return (
    <div className="loading">
      <span className="spinner" />
      <span>{text}</span>
    </div>
  );
}