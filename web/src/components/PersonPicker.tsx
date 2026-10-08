import { useState } from "react";

import type { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { listPeople, type PersonRow } from "../api/people";
import { asApiError } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";

export interface Picked {
  id: string;
  name: string;
}

/** Finds a person in the incident by name. Names alone never decide a match: the user picks. */
export function PersonPicker({
  incidentId,
  picked,
  onPick,
  error,
}: {
  incidentId: string;
  picked: Picked | null;
  onPick: (person: Picked | null) => void;
  error?: string;
}) {
  const api = useApi();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PersonRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiError | null>(null);

  async function search() {
    if (query.trim().length < 2) return;
    setBusy(true);
    setFailure(null);
    try {
      setResults((await listPeople(api, incidentId, { q: query.trim(), limit: 20 })).people);
    } catch (err) {
      setFailure(asApiError(err));
    } finally {
      setBusy(false);
    }
  }

  if (picked) {
    return (
      <div className="picked">
        <span>
          Report about <strong>{picked.name}</strong>
        </span>
        <button type="button" className="link" onClick={() => onPick(null)}>
          Change
        </button>
      </div>
    );
  }

  return (
    <fieldset className="picker">
      <legend>Find the person</legend>
      <div className="search">
        <label>
          Name
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              // Enter searches here instead of submitting the whole report.
              if (e.key === "Enter") {
                e.preventDefault();
                void search();
              }
            }}
            aria-invalid={error ? "true" : undefined}
          />
        </label>
        <button type="button" onClick={() => void search()} disabled={busy || query.trim().length < 2}>
          {busy ? "Finding" : "Find"}
        </button>
      </div>
      {error && <p className="field-error">{error}</p>}
      {failure && <ErrorNotice error={failure} notFound="This incident does not exist." />}
      {results && results.length === 0 && (
        <p className="muted">Nobody by that name yet. Choose "New person" above to add them.</p>
      )}
      {results && results.length > 0 && (
        <ul className="choices">
          {results.map((person) => (
            <li key={person.id}>
              <button
                type="button"
                className="link"
                onClick={() => onPick({ id: person.id, name: person.name })}
              >
                {person.name}
              </button>
              <span className="muted">
                {person.age === null ? "Age not reported" : `Age ${person.age}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}
