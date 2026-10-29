export type WeatherSource = "live" | "simulated";
export type RiskLevel = 0 | 1 | 2 | 3 | 4;
export type HeatLayer = "risk" | "wind" | "rain" | "snow";

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

export interface LocationInput {
  query: string;
  lat?: number | null;
  lon?: number | null;
}

export interface PlanRequest {
  origin: LocationInput;
  destination: LocationInput;
  departure: string; // ISO 8601 with offset
  load_weight_lb: number;
  sample_interval_mi: 10 | 25 | 50;
  weather_source: WeatherSource;
}

export interface CheckpointWeather {
  wind_mph: number;
  gust_mph: number | null;
  rain_in_hr: number;
  snow_in_hr: number;
  temp_f: number | null;
}

export interface CheckpointRisk {
  level: RiskLevel;
  label: string;
  factors: { wind: RiskLevel; rain: RiskLevel; snow: RiskLevel };
  drivers: ("wind" | "rain" | "snow")[];
  load_rule: string | null;
}

export interface Checkpoint {
  index: number;
  mile: number;
  lat: number;
  lon: number;
  eta: string;
  elapsed_s: number;
  represents: [number, number];
  weather: CheckpointWeather | null;
  risk: CheckpointRisk | null;
}

export interface RouteSummary {
  distance_mi: number;
  duration_s: number;
  miles_by_level: Record<"low" | "moderate" | "high" | "severe" | "no_travel", number>;
  unknown_miles: number;
  no_travel_miles: number;
  severe_miles: number;
  high_miles: number;
  avg_risk: number | null;
  max_level: RiskLevel | null;
}

/** Geometry rows are [lat, lon, mile, elapsedSeconds]. */
export type GeometryRow = [number, number, number, number];

export interface RouteOption {
  id: string;
  label: string;
  via: string;
  source: string;
  departure: string;
  arrival: string;
  geometry: GeometryRow[];
  risk_segments: { level: RiskLevel | null; path: [number, number][] }[];
  checkpoints: Checkpoint[];
  summary: RouteSummary;
  rank: number;
  recommended: boolean;
}

export interface StormScenario {
  lat: number;
  lon: number;
  peak_time: number;
  radius_km: number;
  trip_heading_deg: number;
  speed_kmh: number;
}

export interface PlanResponse {
  origin: Place;
  destination: Place;
  departure: string;
  load_weight_lb: number;
  sample_interval_mi: number;
  weather_source: WeatherSource;
  simulation: StormScenario | null;
  truck_max_speed_mph: number;
  routes: RouteOption[];
  recommendation: { route_id: string; ranking: string[]; reasons: string[] };
  warnings: string[];
}

export interface HeatmapResponse {
  bounds: { north: number; south: number; east: number; west: number };
  rows: number;
  cols: number;
  cells: [number, number][];
  cell_km: number;
  corridor_km: number;
  departure: string;
  times: string[];
  layers: Record<HeatLayer, (number | null)[][]>;
}
