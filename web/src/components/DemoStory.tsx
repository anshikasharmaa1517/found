import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { resetDemo } from "../api/admin";
import { useApi } from "../api/context";
import { publishDemoHospitalUpdate } from "../api/incidents";
import { getTimeline, listPeople, type VisibleEntry } from "../api/people";
import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { asApiError, useLoad } from "../useLoad";
import {
  ArrowRightIcon,
  CheckIcon,
  ChevronIcon,
  HospitalIcon,
  PersonSearchIcon,
  PinIcon,
  RestartIcon,
  SearchIcon,
} from "./icons";
import { InfoTip } from "./InfoTip";
import { TraceButton } from "./TraceButton";

interface StoryData {
  sitaId: string;
  otherId: string | null;
  hospitalClaimId: string | null;
  relayClaimId: string | null;
}

/** Finds Sita's records in the demo incident. Every step links to real data. */
async function loadStory(
  api: ReturnType<typeof useApi>,
  incidentId: string,
): Promise<StoryData | null> {
  const { people } = await listPeople(api, incidentId, { q: "Sita", limit: 20 });
  const sita = people.find((p) => p.name === "Sita Tamang");
  if (!sita) return null;
  const other = people.find((p) => p.id !== sita.id && p.name.startsWith("Sita T"));
  const timeline = await getTimeline(api, sita.id, { limit: 20 });
  const visible = timeline.entries.filter((e): e is VisibleEntry => !e.withheld);
  const hospital = visible.find(
    (e) => e.source === "Central Hospital" && e.claim_type === "FOUND_SAFE",
  );
  const relay = visible.find((e) => e.excerpt.startsWith("According to"));
  return {
    sitaId: sita.id,
    otherId: other?.id ?? null,
    hospitalClaimId: hospital?.claim_id ?? null,
    relayClaimId: relay?.claim_id ?? null,
  };
}

const STEPS = [
  {
    short: "Reported missing",
    title: "Sita is reported missing",
    text: "After the flood, the police report Sita Tamang, 24, missing near the Old Bridge. Found keeps the report with who said it and when.",
    icon: <PinIcon size={24} />,
    note: "The pin marks the bridge named in the police report. It is not live tracking.",
  },
  {
    short: "Same person?",
    title: "Is this the same person?",
    text: "A volunteer desk reports a Sita T., 24, at the same bridge. The resolver proposes a match with its reasons; a reviewer decides, and the records are never merged.",
    icon: <PersonSearchIcon size={24} />,
    note: "Names alone are never enough. The resolver compares given name, surname or initial, age and place, and lists what it could not check. The decision records who made it and when.",
  },
  {
    short: "Hospital says safe",
    title: "The hospital says she is safe",
    text: "Central Hospital reports Sita admitted and stable. The police report still says missing, so Found shows both side by side and alerts everyone following her.",
    icon: <HospitalIcon size={24} />,
    note: "This button publishes a prepared, fictional hospital report through the normal path: Found stores it, then the watcher finds everyone following Sita and creates one alert each. Pressing it again publishes nothing new.",
  },
  {
    short: "Where did it come from?",
    title: "Where did this report come from?",
    text: "Flood Relief says Sita is missing, \"according to District Police\". The agent checks who it quotes and compares it with that source: a relay, never independent confirmation.",
    icon: <SearchIcon size={24} />,
    note: "The model only labels who a report quotes. Code decides what happens next, and a person makes the final call. Recorded runs are labelled REPLAYED.",
  },
] as const;

const HIDDEN_KEY = "found.storyHidden";

function storyHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberHidden(hidden: boolean) {
  try {
    if (hidden) localStorage.setItem(HIDDEN_KEY, "1");
    else localStorage.removeItem(HIDDEN_KEY);
  } catch {
    // Only this visit remembers it.
  }
}

/** Admins can reload the demo from its dataset; it runs in the background. */
function StartOver({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");
  const [error, setError] = useState("");

  async function onClick() {
    if (!window.confirm("Reload this incident from its dataset? Reports added since the last load are removed.")) {
      return;
    }
    setState("busy");
    try {
      await resetDemo(api, incidentId);
      setState("done");
    } catch (err) {
      setError(asApiError(err).message);
      setState("failed");
    }
  }

  return (
    <>
      <button type="button" className="ghost small" onClick={onClick} disabled={state === "busy"}>
        <RestartIcon />
        {state === "busy" ? "Starting over" : "Start over"}
      </button>
      {state === "done" && (
        <span className="story-note" role="status">
          The incident is reloading. Refresh in about a minute.
        </span>
      )}
      {state === "failed" && (
        <span className="field-error" role="alert">
          {error}
        </span>
      )}
    </>
  );
}

/** A guided walk through the demo incident, step by step, on real records. */
export function DemoStory({ incidentId }: { incidentId: string }) {
  const api = useApi();
  const user = useUser();
  const reviewer = hasRole(user, "reviewer", "admin");
  const [step, setStep] = useState(0);
  const [hidden, setHidden] = useState(storyHidden);
  const [story, , reloadStory] = useLoad(`story|${incidentId}`, () => loadStory(api, incidentId));
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState("");
  if (story.status !== "ready" || story.data === null) return null;
  const data = story.data;
  const person = `/people/${encodeURIComponent(data.sitaId)}`;
  const current = STEPS[step]!;

  async function publishHospital() {
    setPublishing(true);
    setPublishError("");
    try {
      await publishDemoHospitalUpdate(api, incidentId);
      // Read the story again, so the step shows the report it just published.
      reloadStory();
    } catch (err) {
      setPublishError(asApiError(err).message);
    } finally {
      setPublishing(false);
    }
  }

  function toggleHidden() {
    rememberHidden(!hidden);
    setHidden(!hidden);
  }

  function action(): ReactNode {
    switch (step) {
      case 0:
        return (
          <Link className="button-link primary large" to={person}>
            See every report about Sita
          </Link>
        );
      case 1:
        if (reviewer) {
          return (
            <Link
              className="button-link primary large"
              to={`/incidents/${encodeURIComponent(incidentId)}/review?type=identity`}
            >
              Review the possible match
            </Link>
          );
        }
        return data.otherId ? (
          <Link
            className="button-link primary large"
            to={`/people/${encodeURIComponent(data.otherId)}`}
          >
            See the other record
          </Link>
        ) : null;
      case 2:
        return data.hospitalClaimId ? (
          <>
            <span className="pill ok story-done">
              <CheckIcon size={14} />
              Hospital report published
            </span>
            <Link
              className="button-link large"
              to={`${person}#entry-${data.hospitalClaimId}`}
            >
              See the hospital report
            </Link>
          </>
        ) : (
          <button
            type="button"
            className="primary large"
            onClick={publishHospital}
            disabled={publishing}
          >
            {publishing ? "Publishing" : "Publish the hospital report"}
          </button>
        );
      default:
        return reviewer && data.relayClaimId ? (
          <TraceButton claimId={data.relayClaimId} primary />
        ) : (
          <Link className="button-link primary large" to={person}>
            See the relayed report
          </Link>
        );
    }
  }

  return (
    <section className="story" aria-label="Sita's story, step by step">
      <div className="story-bar">
        <span className="eyebrow">Sita&apos;s story</span>
        <ol className="story-steps" aria-label="Sita's story">
          {STEPS.map((s, i) => (
            <li key={s.short}>
              <button
                type="button"
                className={
                  i === step ? "story-step active" : i < step ? "story-step done" : "story-step"
                }
                aria-current={i === step ? "step" : undefined}
                onClick={() => setStep(i)}
              >
                <span className="story-num" aria-hidden="true">
                  {i < step ? <CheckIcon size={14} /> : i + 1}
                </span>
                {s.short}
              </button>
            </li>
          ))}
        </ol>
        <div className="story-tools">
          {hasRole(user, "admin") && <StartOver incidentId={incidentId} />}
          <button
            type="button"
            className="icon-button ghost"
            aria-label={hidden ? "Show story guide" : "Hide story guide"}
            aria-expanded={!hidden}
            onClick={toggleHidden}
          >
            <ChevronIcon up={!hidden} />
          </button>
        </div>
      </div>
      {!hidden && (
        <div className="story-card" key={step}>
          <span className="story-icon" aria-hidden="true">
            {current.icon}
          </span>
          <div className="story-text">
            <p className="eyebrow accent">
              Step {step + 1} of {STEPS.length}
            </p>
            <div className="story-title">
              <h2>{current.title}</h2>
              <InfoTip label="More about this step">{current.note}</InfoTip>
            </div>
            <p>{current.text}</p>
          </div>
          <div className="story-actions">
            {action()}
            {step === 2 && publishError && (
              <span className="field-error" role="alert">
                {publishError}
              </span>
            )}
            {step < STEPS.length - 1 && (
              <button type="button" className="ghost large" onClick={() => setStep(step + 1)}>
                Next step
                <ArrowRightIcon />
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
