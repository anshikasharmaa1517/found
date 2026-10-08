import { useEffect, useId, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { listPeople, type PersonRow } from "../api/people";
import { ErrorNotice } from "../components/ErrorNotice";
import { rememberIncident } from "../incident";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

function PersonList({ people }: { people: PersonRow[] }) {
  return (
    <>
      {people.map((person) => (
        <li key={person.id}>
          <Link to={`/people/${encodeURIComponent(person.id)}`}>{person.name}</Link>
          <span className="muted">{person.age === null ? "Age not reported" : `Age ${person.age}`}</span>
        </li>
      ))}
    </>
  );
}

export function PeoplePage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const age = params.get("age") ?? "";
  const resultsId = useId();
  const key = `${incidentId}|${q}|${age}`;

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  const [first, retry] = useLoad(key, () => listPeople(api, incidentId, { q, age }));
  const pager = usePager(key, first.status === "ready" ? first.data.next_cursor : null, async (cursor) => {
    const page = await listPeople(api, incidentId, { q, age, cursor });
    return { items: page.people, next: page.next_cursor };
  });

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    const text = String(form.get("q") ?? "").trim();
    const years = String(form.get("age") ?? "").trim();
    if (text) next.set("q", text);
    if (years) next.set("age", years);
    setParams(next);
  }

  const searching = Boolean(q || age);

  return (
    <section className="page">
      <h1>People</h1>
      <p className="muted">Incident {incidentId}</p>

      <form className="search" role="search" onSubmit={onSearch} key={key}>
        <label>
          Name
          <input name="q" type="search" defaultValue={q} placeholder="For example: Rawat" />
        </label>
        <label className="narrow">
          Age
          <input name="age" type="number" min={0} max={120} defaultValue={age} />
        </label>
        <button type="submit" aria-controls={resultsId}>
          Search
        </button>
      </form>
      {age && <p className="hint">Ages match within 2 years. People with no reported age are included.</p>}

      <div id={resultsId} aria-live="polite">
        {first.status === "loading" && <p className="muted">Loading people</p>}
        {first.status === "error" && (
          <ErrorNotice error={first.error} notFound="This incident does not exist." onRetry={retry} />
        )}
        {first.status === "ready" && first.data.people.length === 0 && (
          <p className="muted">{searching ? "No people match this search." : "No people reported yet."}</p>
        )}
        {first.status === "ready" && first.data.people.length > 0 && (
          <ul className="people">
            <PersonList people={first.data.people} />
            <PersonList people={pager.items} />
          </ul>
        )}
        {pager.error && <ErrorNotice error={pager.error} onRetry={pager.loadMore} />}
        {pager.hasMore && (
          <button type="button" onClick={pager.loadMore} disabled={pager.busy}>
            {pager.busy ? "Loading" : "Load more"}
          </button>
        )}
      </div>
    </section>
  );
}
