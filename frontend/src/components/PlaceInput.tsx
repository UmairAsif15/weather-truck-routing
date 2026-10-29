import { useEffect, useId, useRef, useState } from "react";
import { searchPlaces } from "../lib/api";
import type { LocationInput, Place } from "../lib/types";

interface Props {
  label: string;
  value: LocationInput;
  onChange: (value: LocationInput) => void;
  placeholder?: string;
}

/** Text input with debounced place suggestions. Picking one pins exact coordinates. */
export function PlaceInput({ label, value, onChange, placeholder }: Props) {
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const pinned = value.lat != null && value.lon != null;
  const listId = useId();
  const skipNextSearch = useRef(false);

  useEffect(() => {
    if (skipNextSearch.current || pinned) {
      skipNextSearch.current = false;
      return;
    }
    const q = value.query.trim();
    if (q.length < 3) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      searchPlaces(q, controller.signal)
        .then((r) => {
          setResults(r);
          setActive(-1);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [value.query, pinned]);

  const choose = (place: Place) => {
    skipNextSearch.current = true;
    onChange({ query: place.label, lat: place.lat, lon: place.lon });
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || !results.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(results.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(0, a - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <label className="field place-field">
      <span className="field-label">
        {label}
        {pinned && <span className="pinned" title={`${value.lat?.toFixed(4)}, ${value.lon?.toFixed(4)}`}>● located</span>}
      </span>
      <input
        type="text"
        value={value.query}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        onChange={(e) => {
          onChange({ query: e.target.value, lat: null, lon: null });
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      {loading && <span className="input-spinner" aria-hidden />}
      {open && results.length > 0 && !pinned && (
        <ul className="suggestions" id={listId} role="listbox">
          {results.map((place, i) => (
            <li
              key={`${place.lat},${place.lon},${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(place);
              }}
            >
              {place.label}
            </li>
          ))}
        </ul>
      )}
    </label>
  );
}
