import { formatTime, RISK_LABELS, RISK_RGB, THRESHOLDS } from "../lib/risk";
import type { HeatLayer, HeatmapResponse } from "../lib/types";

const LAYERS: { id: HeatLayer; label: string }[] = [
  { id: "risk", label: "Risk" },
  { id: "wind", label: "Wind" },
  { id: "rain", label: "Rain" },
  { id: "snow", label: "Snow" },
];
export const MAX_HOUR = 48;
export const STEP = 0.25;

function Legend({ layer }: { layer: HeatLayer }) {
  const gradient = `linear-gradient(90deg, ${RISK_RGB.map((c) => `rgb(${c.join(",")})`).join(", ")})`;
  const ticks = layer === "risk" ? RISK_LABELS.map((l) => l) : ["0", ...THRESHOLDS[layer].edges.map(String)];
  return (
    <div className="legend">
      <div className="legend-bar" style={{ background: gradient }} />
      <div className="legend-ticks">
        {ticks.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
      {layer !== "risk" && <div className="legend-unit">{THRESHOLDS[layer].unit} · bands match the risk rules</div>}
      {layer === "risk" && <div className="legend-unit">Includes your load-weight rules</div>}
    </div>
  );
}

interface Props {
  heat: HeatmapResponse | null;
  loading: boolean;
  error: string | null;
  hour: number;
  onHour: (h: number) => void;
  layer: HeatLayer;
  onLayer: (l: HeatLayer) => void;
  visible: boolean;
  onVisible: (v: boolean) => void;
  playing: boolean;
  onPlaying: (p: boolean) => void;
  truckNote: string | null;
}

export function TimeControl(props: Props) {
  const { heat, loading, error, hour, onHour, layer, onLayer, visible, onVisible, playing, onPlaying, truckNote } = props;

  const at = heat ? new Date(new Date(heat.departure).getTime() + hour * 3600_000) : null;
  const wholeH = Math.floor(hour);
  const mins = Math.round((hour - wholeH) * 60);

  return (
    <div className="time-control">
      <div className="tc-top">
        <label className="toggle">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          <span>Weather heatmap</span>
        </label>
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {LAYERS.map((l) => (
            <button key={l.id} type="button" role="radio" aria-checked={layer === l.id} className={layer === l.id ? "on" : ""} onClick={() => onLayer(l.id)}>
              {l.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="tc-status">Loading corridor forecast…</div>}
      {error && <div className="tc-status error">{error}</div>}

      {heat && (
        <>
          <div className="tc-slider">
            <button
              type="button"
              className="play"
              onClick={() => {
                if (!playing && hour >= MAX_HOUR) onHour(0);
                onPlaying(!playing);
              }}
              aria-label={playing ? "Pause" : "Play"}
            >
              {playing ? "❚❚" : "▶"}
            </button>
            <input
              type="range"
              min={0}
              max={MAX_HOUR}
              step={STEP}
              value={hour}
              onChange={(e) => {
                onPlaying(false);
                onHour(Number(e.target.value));
              }}
              aria-label="Forecast hour after departure"
            />
          </div>
          <div className="tc-time">
            <strong>
              T+{wholeH}h{mins ? ` ${String(mins).padStart(2, "0")}m` : ""}
            </strong>
            <span>{at && formatTime(at)}</span>
            {truckNote && <span className="truck-note">🚚 {truckNote}</span>}
          </div>
          <Legend layer={layer} />
        </>
      )}
    </div>
  );
}

