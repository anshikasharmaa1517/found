import { useEffect, useId, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/context";
import { listPeople, type PersonRow } from "../api/people";
import { ErrorNotice } from "../components/ErrorNotice";
import { Empty, PageHeader, SkeletonRows } from "../components/ui";
import { rememberIncident } from "../incident";
import { useLoad } from "../useLoad";
import { usePager } from "../usePager";

function PersonRows({ people }: { people: PersonRow[] }) {
  return (
    <>
      {people.map((person) => (
        <tr key={person.id}>
          <th scope="row">
            <Link to={`/people/${encodeURIComponent(person.id)}`}>{person.name}</Link>
          </th>
          <td className="num">
            {person.age === null ? <span className="muted">Not reported</span> : person.age}
          </td>
        </tr>
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
      <PageHeader
        title="People"
        description="Everyone reported in this incident. Open a person to see each report and who made it."
      />

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
        {first.status === "loading" && <SkeletonRows label="Loading people" rows={8} />}
        {first.status === "error" && (
          <ErrorNotice error={first.error} notFound="This incident does not exist." onRetry={retry} />
        )}
        {first.status === "ready" && first.data.people.length === 0 && (
          <Empty
            title={searching ? "No people match this search." : "No people reported yet."}
            action={
              searching ? (
                <button type="button" onClick={() => setParams(new URLSearchParams())}>
                  Clear search
                </button>
              ) : undefined
            }
          >
            {searching
              ? "Try part of a name or leave the age empty. Ages match within 2 years."
              : "People appear here as soon as an organization publishes a report about them."}
          </Empty>
        )}
        {first.status === "ready" && first.data.people.length > 0 && (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col" className="num">
                      Age
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <PersonRows people={first.data.people} />
                  <PersonRows people={pager.items} />
                </tbody>
              </table>
            </div>
            <div className="table-foot">
              <span>
                Showing {first.data.people.length + pager.items.length}
                {pager.hasMore ? " so far" : ""}
              </span>
              {pager.hasMore && (
                <button type="button" onClick={pager.loadMore} disabled={pager.busy}>
                  {pager.busy ? "Loading" : "Load more"}
                </button>
              )}
            </div>
          </>
        )}
        {pager.error && <ErrorNotice error={pager.error} onRetry={pager.loadMore} />}
      </div>
    </section>
  );
}
