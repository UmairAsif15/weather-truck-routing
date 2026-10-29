import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckpointTable } from "./components/CheckpointTable";
import { MapView } from "./components/MapView";
import { RouteCards } from "./components/RouteCards";
import { MAX_HOUR, STEP, TimeControl } from "./components/TimeControl";
import { TripForm } from "./components/TripForm";
import { ApiError, fetchHeatmap, planTrip } from "./lib/api";
import { positionAt, renderFrame } from "./lib/heatmap";
import type { Checkpoint, HeatLayer, HeatmapResponse, PlanRequest, PlanResponse } from "./lib/types";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focus, setFocus] = useState<Checkpoint | null>(null);

  const [heat, setHeat] = useState<HeatmapResponse | null>(null);
  const [heatLoading, setHeatLoading] = useState(false);
  const [heatError, setHeatError] = useState<string | null>(null);
  const [heatVisible, setHeatVisible] = useState(true);
  const [layer, setLayer] = useState<HeatLayer>("risk");
  const [hour, setHour] = useState(0);
  const [playing, setPlaying] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const submit = useCallback(async (request: PlanRequest) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPlanning(true);
    setError(null);
    setHeat(null);
    setHeatError(null);
    setPlaying(false);
    setHour(0);
    setFocus(null);
    try {
      const result = await planTrip(request, controller.signal);
      setPlan(result);
      setSelectedId(result.recommendation.route_id);
      setPlanning(false);
      // Routes are on screen; the corridor heatmap loads behind them.
      setHeatLoading(true);
      try {
        setHeat(await fetchHeatmap(result, controller.signal));
      } catch (e) {
        if (!controller.signal.aborted) setHeatError(message(e));
      } finally {
        if (!controller.signal.aborted) setHeatLoading(false);
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(message(e));
        setPlanning(false);
      }
    }
  }, []);

  // Playback: 15-minute steps, ~11 forecast hours per second.
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setHour((h) => Math.min(MAX_HOUR, h + STEP));
    }, 90);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    if (playing && hour >= MAX_HOUR) setPlaying(false);
  }, [playing, hour]);

  // Frames are rendered on demand and cached; a new heatmap starts a fresh cache.
  const frameCache = useMemo(() => new Map<string, string>(), [heat]);
  const frameUrl = useMemo(() => {
    if (!heat || !heatVisible) return null;
    const key = `${layer}:${hour}`;
    let url = frameCache.get(key);
    if (!url) {
      url = renderFrame(heat, layer, hour);
      frameCache.set(key, url);
    }
    return url;
  }, [heat, heatVisible, layer, hour, frameCache]);

  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null;
  const elapsed = hour * 3600;
  const truckPosition = selected && heat ? positionAt(selected.geometry, elapsed) : null;
  const truckNote = useMemo(() => {
    if (!selected || !heat) return null;
    const end = selected.geometry[selected.geometry.length - 1];
    if (elapsed > end[3]) return `Route ${selected.id} has arrived`;
    const row = selected.geometry.find((g) => g[3] >= elapsed);
    return `Route ${selected.id}: mile ${Math.round(row ? row[2] : 0)} of ${Math.round(end[2])}`;
  }, [selected, heat, elapsed]);

  const selectRoute = useCallback((id: string) => {
    setSelectedId(id);
    setFocus(null);
  }, []);

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <div className="logo" aria-hidden>
            <svg viewBox="0 0 32 32"><path d="M6 21h3l2-7h10l2 7h3" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /><circle cx="11" cy="22" r="2.4" fill="currentColor" /><circle cx="21" cy="22" r="2.4" fill="currentColor" /></svg>
          </div>
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>Three routes, forecast at the truck's ETA every few miles, ranked by risk then time.</p>
          </div>
        </header>

        <TripForm loading={planning} onSubmit={submit} />

        {error && <div className="error-banner" role="alert">{error}</div>}

        {planning && (
          <div className="skeletons" aria-busy>
            {[0, 1, 2].map((i) => <div key={i} className="skeleton" />)}
          </div>
        )}

        {plan && !planning && (
          <>
            {plan.weather_source === "simulated" && (
              <p className="sim-note">
                Demo storm: a simulated system peaks on Route A's midpoint as the truck arrives, so you can see
                the risk rules and ranking respond. Switch to <em>Live</em> for real forecasts.
              </p>
            )}
            <RouteCards plan={plan} selectedId={selectedId ?? ""} onSelect={selectRoute} />
            {selected && <CheckpointTable route={selected} onFocus={setFocus} />}
          </>
        )}

        {!plan && !planning && (
          <section className="intro">
            <h2>How routes are scored</h2>
            <ol>
              <li>Up to three distinct truck routes are generated (OSRM, slowed to truck speeds).</li>
              <li>Weather is sampled every 10/25/50 miles at the moment the truck will be there.</li>
              <li>Each checkpoint gets the worst of wind, rain and snow risk — with load-weight wind rules.</li>
              <li>Routes are ranked: fewest Severe miles, fewest High miles, lowest average risk, then fastest.</li>
            </ol>
          </section>
        )}
        <footer className="credits">
          Routing © OSRM / OpenStreetMap · Weather © Open-Meteo · Geocoding © Photon
        </footer>
      </aside>

      <main className="map-wrap">
        <MapView
          plan={plan}
          selectedId={selectedId}
          onSelect={selectRoute}
          heat={heat}
          heatFrameUrl={frameUrl}
          truckPosition={truckPosition}
          focus={focus}
        />
        {plan && (
          <TimeControl
            heat={heat}
            loading={heatLoading}
            error={heatError}
            hour={hour}
            onHour={setHour}
            layer={layer}
            onLayer={setLayer}
            visible={heatVisible}
            onVisible={setHeatVisible}
            playing={playing}
            onPlaying={setPlaying}
            truckNote={truckNote}
          />
        )}
        <div className="map-legend">
          {["Low", "Moderate", "High", "Severe", "No Travel"].map((l, i) => (
            <span key={l}><i className={`dot l${i}`} />{l}</span>
          ))}
        </div>
      </main>
    </div>
  );
}
