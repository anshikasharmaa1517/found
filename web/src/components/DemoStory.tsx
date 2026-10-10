import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/context";
import { getTimeline, listPeople, type VisibleEntry } from "../api/people";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { useLoad } from "../useLoad";
import { TraceButton } from "./TraceButton";

interface StoryData {
  mayaId: string;
  otherId: string | null;
  hospitalClaimId: string | null;
  relayClaimId: string | null;
}

/** Finds Maya's records in the demo incident. Every step links to real data. */
async function loadStory(
  api: ReturnType<typeof useApi>,
  incidentId: string,
): Promise<StoryData | null> {
  const { people } = await listPeople(api, incidentId, { q: "Maya", limit: 20 });
  const maya = people.find((p) => p.name === "Maya Rawat");
  if (!maya) return null;
  const other = people.find((p) => p.id !== maya.id && p.name.startsWith("Maya R"));
  const timeline = await getTimeline(api, maya.id, { limit: 20 });
  const visible = timeline.entries.filter((e): e is VisibleEntry => !e.withheld);
  const hospital = visible.find(
    (e) => e.source === "Central Hospital Demo" && e.claim_type === "FOUND_SAFE",
  );
  const relay = visible.find((e) => e.excerpt.startsWith("According to"));
  return {
    mayaId: maya.id,
    otherId: other?.id ?? null,
    hospitalClaimId: hospital?.claim_id ?? null,
    relayClaimId: relay?.claim_id ?? null,
  };
}

const STEPS = [
  {
    short: "Reported missing",
    title: "Maya is reported missing",
    text: "After the flood, the police report Maya Rawat, 24, missing near the Old Bridge. Found keeps the report with who said it and when.",
  },
  {
    short: "Same person?",
    title: "Is this the same person?",
    text: "A volunteer desk reports a Maya R., 24, at the same bridge. The resolver proposes a match with its reasons; a reviewer decides, and the records are never merged.",
  },
  {
    short: "Hospital says safe",
    title: "The hospital says she is safe",
    text: "Central Hospital Demo reports Maya admitted and stable. Her page now cites that report, and still shows the police report that came first.",
  },
  {
    short: "Where did it come from?",
    title: "Where did the last report come from?",
    text: "Flood Relief Demo also says Maya is safe, citing the hospital. The agent traces it and finds a relay: helpful, but not independent confirmation.",
  },
] as const;

/** A guided walk through the demo incident, step by step, on real records. */
export function DemoStory({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const user = useUser();
  const reviewer = hasRole(user, "reviewer", "admin");
  const [step, setStep] = useState(0);
  const [story] = useLoad(`story|${incidentId}`, () => loadStory(api, incidentId));
  if (story.status !== "ready" || story.data === null) return null;
  const data = story.data;
  const person = `/people/${encodeURIComponent(data.mayaId)}`;
  const current = STEPS[step]!;

  function action() {
    switch (step) {
      case 0:
        return (
          <Link className="button-link primary" to={person}>
            See every report about Maya
          </Link>
        );
      case 1:
        if (reviewer) {
          return (
            <Link
              className="button-link primary"
              to={`/incidents/${encodeURIComponent(incidentId)}/review?type=identity`}
            >
              Review the possible match
            </Link>
          );
        }
        return data.otherId ? (
          <Link className="button-link primary" to={`/people/${encodeURIComponent(data.otherId)}`}>
            See the other record
          </Link>
        ) : null;
      case 2:
        return (
          <Link
            className="button-link primary"
            to={data.hospitalClaimId ? `${person}#entry-${data.hospitalClaimId}` : person}
          >
            See the hospital report
          </Link>
        );
      default:
        return reviewer && data.relayClaimId ? (
          <TraceButton claimId={data.relayClaimId} primary />
        ) : (
          <Link className="button-link primary" to={person}>
            See the relayed report
          </Link>
        );
    }
  }

  return (
    <section className="story" aria-labelledby="story-title">
      <ol className="story-steps" aria-label="Maya's story">
        {STEPS.map((s, i) => (
          <li key={s.short}>
            <button
              type="button"
              className={i === step ? "story-step active" : "story-step"}
              aria-current={i === step ? "step" : undefined}
              onClick={() => setStep(i)}
            >
              <span className="story-num" aria-hidden="true">
                {i + 1}
              </span>
              {s.short}
            </button>
          </li>
        ))}
      </ol>
      <div className="story-card">
        <div>
          <p className="eyebrow">
            Step {step + 1} of {STEPS.length}
          </p>
          <h2 id="story-title">{current.title}</h2>
          <p>{current.text}</p>
        </div>
        <div className="story-actions">
          {action()}
          {step < STEPS.length - 1 && (
            <button type="button" className="link" onClick={() => setStep(step + 1)}>
              Next step
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
