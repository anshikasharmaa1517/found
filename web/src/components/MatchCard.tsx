import { Link } from "react-router-dom";

import type { OpenMatch } from "../api/people";
import { labelFor, MATCH_REASON_LABELS } from "../labels";
import { nameInitials } from "../names";
import { PersonSearchIcon } from "./icons";

export interface MatchPerson {
  id: string;
  name: string;
  age: number | null;
}

/**
 * Two records that may be the same person, as in Trace: the pair, the rule-based reasons,
 * and a reviewer's way in. The records stay separate until a reviewer decides (rule 6).
 */
export function MatchCard({
  people,
  reasons,
  reviewHref,
}: {
  people: MatchPerson[];
  reasons: string[];
  /** Where a reviewer decides; omitted for roles that do not review. */
  reviewHref?: string;
}) {
  const ages = [...new Set(people.map((p) => p.age))];
  return (
    <li className="match-card">
      <div className="match-head">
        <span className="match-icon" aria-hidden="true">
          <PersonSearchIcon />
        </span>
        <h3>Could these be the same person?</h3>
      </div>
      <p className="match-pair">
        {people.map((p, i) => (
          <span key={p.id} className="match-person">
            {i > 0 && <span className="meta">and</span>}
            <span className="person-initials" aria-hidden="true">
              {nameInitials(p.name)}
            </span>
            <Link to={`/people/${encodeURIComponent(p.id)}`}>{p.name}</Link>
          </span>
        ))}
      </p>
      <p className="meta">
        Why we think so:{" "}
        {reasons.map((r) => labelFor(MATCH_REASON_LABELS, r).toLowerCase()).join(", ")}
        {ages.length === 1 && ages[0] !== null && ` (${ages[0]})`}.
      </p>
      <p className="meta match-note">We keep them separate until someone who knows them confirms.</p>
      {reviewHref && (
        <Link className="button-link" to={reviewHref}>
          Review match
        </Link>
      )}
    </li>
  );
}

/** Records that may be this same person, waiting for a reviewer. */
export function OpenMatches({
  person,
  matches,
  reviewHref,
}: {
  person: { id: string; name: string; age: number | null };
  matches: OpenMatch[];
  reviewHref?: string;
}) {
  if (matches.length === 0) return null;
  return (
    <section className="matches" aria-label="Possible matches">
      <ul className="match-cards">
        {matches.map((m) => (
          <MatchCard
            key={m.pair_key}
            people={[person, m.other]}
            reasons={m.reasons}
            reviewHref={reviewHref}
          />
        ))}
      </ul>
    </section>
  );
}
