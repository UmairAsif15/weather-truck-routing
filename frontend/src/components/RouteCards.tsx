import { formatDuration, formatMiles, formatTime, riskColor, RISK_LABELS } from "../lib/risk";
import type { PlanResponse, RouteOption } from "../lib/types";

/** Where along the route each risk level occurs (each checkpoint owns the stretch it represents). */
export function RiskStrip({ route }: { route: RouteOption }) {
  const total = route.summary.distance_mi || 1;
  return (
    <div className="risk-strip" aria-label="Risk along the route">
      {route.checkpoints.map((cp) => (
        <span
          key={cp.index}
          style={{
            width: `${((cp.represents[1] - cp.represents[0]) / total) * 100}%`,
            background: riskColor(cp.risk?.level),
          }}
          title={`Mile ${cp.mile}: ${cp.risk?.label ?? "No forecast"}`}
        />
      ))}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "bad" | "warn" }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function RouteCard({ route, selected, onSelect }: { route: RouteOption; selected: boolean; onSelect: () => void }) {
  const s = route.summary;
  const severePlus = s.severe_miles + s.no_travel_miles;
  return (
    <button
      type="button"
      className={`route-card ${selected ? "selected" : ""} ${route.recommended ? "recommended" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className="route-head">
        <span className="route-badge">{route.id}</span>
        <div className="route-title">
          <strong>{route.recommended ? "Recommended" : `Option ${route.rank}`}</strong>
          <span className="via" title={route.via}>{route.via ? `via ${route.via}` : route.label}</span>
        </div>
        <span className="max-risk" style={{ background: riskColor(s.max_level) }}>
          {s.max_level == null ? "Unknown" : RISK_LABELS[s.max_level]}
        </span>
      </div>
      <RiskStrip route={route} />
      <div className="stats">
        <Stat label="Drive time" value={formatDuration(s.duration_s)} />
        <Stat label="Distance" value={formatMiles(s.distance_mi)} />
        <Stat label="Arrive" value={formatTime(route.arrival)} />
        <Stat label="Severe+ mi" value={severePlus.toFixed(0)} tone={severePlus > 0 ? "bad" : undefined} />
        <Stat label="High mi" value={s.high_miles.toFixed(0)} tone={s.high_miles > 0 ? "warn" : undefined} />
        <Stat label="Avg risk" value={s.avg_risk == null ? "–" : `${s.avg_risk.toFixed(2)} / 4`} />
      </div>
      {s.no_travel_miles > 0 && (
        <p className="no-travel-note">⚠ {formatMiles(s.no_travel_miles)} in No Travel conditions</p>
      )}
    </button>
  );
}

interface Props {
  plan: PlanResponse;
  selectedId: string;
  onSelect: (id: string) => void;
}

export function RouteCards({ plan, selectedId, onSelect }: Props) {
  const ranked = [...plan.routes].sort((a, b) => a.rank - b.rank);
  return (
    <section className="results">
      <div className="recommendation">
        <h2>
          Take <span className="route-badge inline">{plan.recommendation.route_id}</span>
        </h2>
        <ul>
          {plan.recommendation.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        <p className="ranking-rule">
          Ranked by fewest Severe miles → fewest High miles → lowest average risk → shortest time
          (No Travel miles count before Severe).
        </p>
      </div>
      {plan.warnings.map((w) => (
        <p key={w} className="warning">{w}</p>
      ))}
      {ranked.map((route) => (
        <RouteCard key={route.id} route={route} selected={route.id === selectedId} onSelect={() => onSelect(route.id)} />
      ))}
    </section>
  );
}
