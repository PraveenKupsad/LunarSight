import { useSelection } from "../context/selectioncontext";

export default function DateTimePicker() {
  const { date, setDate, time, setTime } = useSelection();

  const fixTime = (v) => (v.length === 5 ? `${v}:00` : v);

  const shift = (ms) => {
    const d = new Date(`${date}T${fixTime(time)}Z`);
    if (isNaN(d)) return;
    const n = new Date(d.getTime() + ms);
    setDate(n.toISOString().slice(0, 10));
    setTime(n.toISOString().slice(11, 19));
  };

  const setNow = () => {
    const n = new Date();
    setDate(n.toISOString().slice(0, 10));
    setTime(n.toISOString().slice(11, 19));
  };

  const H = 3600000, D = 24 * H;

  return (
    <div className="picker">
      <label>
        Date (UTC)
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>
        Time (UTC)
        <input type="time" step="1" value={time} onChange={(e) => setTime(fixTime(e.target.value))} />
      </label>
      <div className="picker-buttons">
        <button className="btn btn-ghost" onClick={() => shift(-D)}>−1 day</button>
        <button className="btn btn-ghost" onClick={() => shift(-H)}>−1 h</button>
        <button className="btn btn-ghost" onClick={() => shift(H)}>+1 h</button>
        <button className="btn btn-ghost" onClick={() => shift(D)}>+1 day</button>
        <button className="btn btn-ghost" onClick={setNow}>Now</button>
      </div>
    </div>
  );
}