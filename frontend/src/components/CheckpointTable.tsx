import { formatTime, riskColor } from "../lib/risk";
import type { Checkpoint, RouteOption } from "../lib/types";

const fmt = (v: number | null | undefined, digits = 0) => (v == null ? "–" : v.toFixed(digits));

function Drivers({ cp }: { cp: Checkpoint }) {
  if (!cp.risk) return <span className="muted">no forecast</span>;
  if (!cp.risk.drivers.length) return <span className="muted">—</span>;
  return <span>{cp.risk.drivers.join(", ")}{cp.risk.load_rule ? " + load" : ""}</span>;
}

interface Props {
  route: RouteOption;
  onFocus: (cp: Checkpoint) => void;
}

export function CheckpointTable({ route, onFocus }: Props) {
  return (
    <details className="checkpoints" open>
      <summary>
        Route {route.id} checkpoints <span className="muted">({route.checkpoints.length})</span>
      </summary>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Mile</th>
              <th>ETA</th>
              <th>Risk</th>
              <th title="Sustained wind (gust)">Wind mph</th>
              <th>Rain in/h</th>
              <th>Snow in/h</th>
              <th>Cause</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((cp) => (
              <tr key={cp.index} onClick={() => onFocus(cp)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onFocus(cp)}>
                <td className="num">{cp.mile.toFixed(0)}</td>
                <td>{formatTime(cp.eta)}</td>
                <td>
                  <span className="risk-pill" style={{ background: riskColor(cp.risk?.level) }}>
                    {cp.risk?.label ?? "Unknown"}
                  </span>
                </td>
                <td className="num">
                  {fmt(cp.weather?.wind_mph)}
                  {cp.weather?.gust_mph != null && <span className="muted"> ({fmt(cp.weather.gust_mph)})</span>}
                </td>
                <td className="num">{fmt(cp.weather?.rain_in_hr, 2)}</td>
                <td className="num">{fmt(cp.weather?.snow_in_hr, 2)}</td>
                <td><Drivers cp={cp} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
