import { useState } from "react";
import { localTimeZone } from "../lib/risk";
import type { LocationInput, PlanRequest, WeatherSource } from "../lib/types";
import { PlaceInput } from "./PlaceInput";

const EXAMPLES: { label: string; origin: LocationInput; destination: LocationInput }[] = [
  {
    label: "Dallas → Oklahoma City",
    origin: { query: "Dallas, Texas, United States", lat: 32.7767, lon: -96.797 },
    destination: { query: "Oklahoma City, Oklahoma, United States", lat: 35.4676, lon: -97.5164 },
  },
  {
    label: "Chicago → Minneapolis",
    origin: { query: "Chicago, Illinois, United States", lat: 41.8781, lon: -87.6298 },
    destination: { query: "Minneapolis, Minnesota, United States", lat: 44.9778, lon: -93.265 },
  },
  {
    label: "Denver → Salt Lake City",
    origin: { query: "Denver, Colorado, United States", lat: 39.7392, lon: -104.9903 },
    destination: { query: "Salt Lake City, Utah, United States", lat: 40.7608, lon: -111.891 },
  },
];

/** `datetime-local` value for the next whole hour, in the browser's time zone. */
function nextHourLocal(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

interface Props {
  loading: boolean;
  onSubmit: (request: PlanRequest) => void;
}

export function TripForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<LocationInput>({ query: "" });
  const [destination, setDestination] = useState<LocationInput>({ query: "" });
  const [departure, setDeparture] = useState(nextHourLocal);
  const [load, setLoad] = useState("40000");
  const [interval, setSampleInterval] = useState<10 | 25 | 50>(25);
  const [source, setSource] = useState<WeatherSource>("live");

  const loadNumber = Number(load);
  const canSubmit =
    !loading && origin.query.trim() && destination.query.trim() && departure && load !== "" && loadNumber >= 0;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      origin,
      destination,
      departure: new Date(departure).toISOString(), // local wall time → UTC instant
      load_weight_lb: loadNumber,
      sample_interval_mi: interval,
      weather_source: source,
    });
  };

  return (
    <form className="trip-form" onSubmit={submit}>
      <PlaceInput label="Origin" value={origin} onChange={setOrigin} placeholder="City or address" />
      <PlaceInput label="Destination" value={destination} onChange={setDestination} placeholder="City or address" />

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            className="chip"
            onClick={() => {
              setOrigin(ex.origin);
              setDestination(ex.destination);
            }}
          >
            {ex.label}
          </button>
        ))}
      </div>

      <div className="row">
        <label className="field">
          <span className="field-label">Departure <small>({localTimeZone()})</small></span>
          <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} required />
        </label>
        <label className="field load-field">
          <span className="field-label">Load weight</span>
          <div className="suffix-input">
            <input
              type="number"
              min={0}
              max={200000}
              step={500}
              value={load}
              onChange={(e) => setLoad(e.target.value)}
              required
            />
            <span>lb</span>
          </div>
        </label>
      </div>

      <div className="row">
        <div className="field">
          <span className="field-label">Weather checkpoint every</span>
          <div className="segmented" role="radiogroup" aria-label="Checkpoint interval">
            {([10, 25, 50] as const).map((mi) => (
              <button
                key={mi}
                type="button"
                role="radio"
                aria-checked={interval === mi}
                className={interval === mi ? "on" : ""}
                onClick={() => setSampleInterval(mi)}
              >
                {mi} mi
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span className="field-label">Weather data</span>
          <div className="segmented" role="radiogroup" aria-label="Weather source">
            <button type="button" role="radio" aria-checked={source === "live"} className={source === "live" ? "on" : ""} onClick={() => setSource("live")}>
              Live
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={source === "simulated"}
              className={source === "simulated" ? "on" : ""}
              onClick={() => setSource("simulated")}
              title="A deterministic storm placed on the fastest route — useful to see the risk logic at work on a calm day."
            >
              Demo storm
            </button>
          </div>
        </div>
      </div>

      <button className="primary" type="submit" disabled={!canSubmit}>
        {loading ? "Planning routes…" : "Find safest route"}
      </button>
    </form>
  );
}
