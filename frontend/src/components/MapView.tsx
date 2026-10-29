import L from "leaflet";
import { Fragment, memo, useEffect, useMemo } from "react";
import { CircleMarker, ImageOverlay, MapContainer, Marker, Pane, Polyline, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import { formatDuration, formatTime, riskColor } from "../lib/risk";
import type { Checkpoint, HeatmapResponse, PlanResponse, RouteOption } from "../lib/types";

const US_CENTER: [number, number] = [39.5, -98.35];
// Override with VITE_TILE_URL (e.g. a MapTiler/Stadia URL with key) for heavier production use.
const TILE_URL = import.meta.env.VITE_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const endpointIcon = (text: string, kind: "start" | "end") =>
  L.divIcon({ className: "", html: `<div class="endpoint ${kind}">${text}</div>`, iconSize: [26, 26], iconAnchor: [13, 13] });
const truckIcon = L.divIcon({ className: "", html: '<div class="truck-marker">🚚</div>', iconSize: [30, 30], iconAnchor: [15, 15] });
const START_ICON = endpointIcon("S", "start");
const END_ICON = endpointIcon("D", "end");

function FitToPlan({ plan }: { plan: PlanResponse | null }) {
  const map = useMap();
  useEffect(() => {
    if (!plan) return;
    const bounds = L.latLngBounds(plan.routes.flatMap((r) => r.geometry.map((g) => [g[0], g[1]] as [number, number])));
    // Leave room for the time slider docked at the bottom of the map.
    map.fitBounds(bounds, { paddingTopLeft: [48, 64], paddingBottomRight: [48, 200] });
  }, [plan, map]);
  return null;
}

function FlyTo({ target }: { target: Checkpoint | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo([target.lat, target.lon], Math.max(map.getZoom(), 9), { duration: 0.6 });
  }, [target, map]);
  return null;
}

function CheckpointPopup({ route, cp }: { route: RouteOption; cp: Checkpoint }) {
  const w = cp.weather;
  return (
    <div className="cp-popup">
      <div className="cp-popup-head">
        <strong>Route {route.id} · mile {cp.mile.toFixed(0)}</strong>
        <span className="risk-pill" style={{ background: riskColor(cp.risk?.level) }}>{cp.risk?.label ?? "Unknown"}</span>
      </div>
      <div className="cp-eta">ETA {formatTime(cp.eta)}</div>
      {w ? (
        <dl>
          <dt>Wind</dt><dd>{w.wind_mph.toFixed(0)} mph{w.gust_mph != null && ` (gusts ${w.gust_mph.toFixed(0)})`}</dd>
          <dt>Rain</dt><dd>{w.rain_in_hr.toFixed(2)} in/hr</dd>
          <dt>Snow</dt><dd>{w.snow_in_hr.toFixed(2)} in/hr</dd>
          {w.temp_f != null && (<><dt>Temp</dt><dd>{w.temp_f.toFixed(0)} °F</dd></>)}
        </dl>
      ) : (
        <p className="muted">Beyond the forecast horizon.</p>
      )}
      {cp.risk?.drivers.length ? <p className="cp-driver">Driven by {cp.risk.drivers.join(" & ")}</p> : null}
      {cp.risk?.load_rule && <p className="cp-load">Load rule: {cp.risk.load_rule}</p>}
    </div>
  );
}

const RouteLayer = memo(function RouteLayer({
  route,
  selected,
  onSelect,
}: {
  route: RouteOption;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const positions = useMemo(() => route.geometry.map((g) => [g[0], g[1]] as [number, number]), [route]);
  const mid = positions[Math.floor(positions.length / 2)];
  const s = route.summary;
  const label = `${route.id}${route.recommended ? " ★" : ""} · ${formatDuration(s.duration_s)}`;
  const handlers = useMemo(() => ({ click: () => onSelect(route.id) }), [onSelect, route.id]);

  if (!selected) {
    return (
      <>
        <Polyline positions={positions} pathOptions={{ color: "#1f2d3a", weight: 5, opacity: 0.35 }} eventHandlers={handlers}>
          <Tooltip sticky>{label} — click to inspect</Tooltip>
        </Polyline>
        {route.checkpoints.map((cp) => (
          <CircleMarker
            key={cp.index}
            center={[cp.lat, cp.lon]}
            radius={3}
            pathOptions={{ color: riskColor(cp.risk?.level), fillColor: riskColor(cp.risk?.level), fillOpacity: 0.7, weight: 0 }}
            eventHandlers={handlers}
          />
        ))}
        <CircleMarker center={mid} radius={0} opacity={0}>
          <Tooltip permanent direction="center" className="route-label">{label}</Tooltip>
        </CircleMarker>
      </>
    );
  }

  return (
    <>
      <Polyline positions={positions} pathOptions={{ color: "#ffffff", weight: 11, opacity: 0.95 }} />
      {route.risk_segments.map((seg, i) => (
        <Polyline key={i} positions={seg.path} pathOptions={{ color: riskColor(seg.level), weight: 6, opacity: 1 }} />
      ))}
      {route.checkpoints.map((cp) => (
        <CircleMarker
          key={cp.index}
          center={[cp.lat, cp.lon]}
          radius={6}
          pathOptions={{ color: "#ffffff", weight: 2, fillColor: riskColor(cp.risk?.level), fillOpacity: 1 }}
        >
          <Tooltip direction="top" offset={[0, -6]}>
            Mile {cp.mile.toFixed(0)} · {cp.risk?.label ?? "Unknown"} · {formatTime(cp.eta)}
          </Tooltip>
          <Popup>
            <CheckpointPopup route={route} cp={cp} />
          </Popup>
        </CircleMarker>
      ))}
      <CircleMarker center={mid} radius={0} opacity={0}>
        <Tooltip permanent direction="center" className="route-label selected">{label}</Tooltip>
      </CircleMarker>
    </>
  );
});

interface Props {
  plan: PlanResponse | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
  heat: HeatmapResponse | null;
  heatFrameUrl: string | null;
  truckPosition: [number, number] | null;
  focus: Checkpoint | null;
}

export function MapView({ plan, selectedId, onSelect, heat, heatFrameUrl, truckPosition, focus }: Props) {
  const heatBounds = useMemo(
    () => (heat ? L.latLngBounds([heat.bounds.south, heat.bounds.west], [heat.bounds.north, heat.bounds.east]) : null),
    [heat],
  );
  // Draw unselected routes first so the selected one sits on top.
  const ordered = plan ? [...plan.routes].sort((a, b) => Number(a.id === selectedId) - Number(b.id === selectedId)) : [];

  return (
    <MapContainer center={US_CENTER} zoom={4} preferCanvas className="map" zoomControl={false}>
      <TileLayer
        url={TILE_URL}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
        className="basemap"
      />
      <Pane name="heat" style={{ zIndex: 350, pointerEvents: "none" }}>
        {heatBounds && heatFrameUrl && (
          <ImageOverlay url={heatFrameUrl} bounds={heatBounds} opacity={0.85} className="heat-overlay" />
        )}
      </Pane>
      <FitToPlan plan={plan} />
      <FlyTo target={focus} />
      {ordered.map((route) => (
        <Fragment key={route.id}>
          <RouteLayer route={route} selected={route.id === selectedId} onSelect={onSelect} />
        </Fragment>
      ))}
      {plan && (
        <>
          <Marker position={[plan.origin.lat, plan.origin.lon]} icon={START_ICON}>
            <Tooltip>Start: {plan.origin.label}</Tooltip>
          </Marker>
          <Marker position={[plan.destination.lat, plan.destination.lon]} icon={END_ICON}>
            <Tooltip>Destination: {plan.destination.label}</Tooltip>
          </Marker>
        </>
      )}
      {focus && <CircleMarker center={[focus.lat, focus.lon]} radius={16} pathOptions={{ color: "#0b3d4f", weight: 2, fill: false, dashArray: "4 4" }} />}
      {truckPosition && <Marker position={truckPosition} icon={truckIcon} interactive={false} zIndexOffset={1000} />}
    </MapContainer>
  );
}
