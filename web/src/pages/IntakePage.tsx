import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { useApi } from "../api/context";
import {
  getIntakeJob,
  MAX_UPLOAD_BYTES,
  requestUpload,
  submitText,
  UPLOAD_TYPES,
  uploadFile,
  type IntakeJob,
  type UploadType,
} from "../api/intake";
import { PageHeader } from "../components/ui";
import { intakeFailureLabel, INTAKE_STATUS_LABELS, labelFor } from "../labels";

export const POLL_MS = 3000;
const STATUS_TONE: Record<string, string> = {
  RECEIVED: "accent pulse",
  EXTRACTING: "accent pulse",
  READY_FOR_REVIEW: "ok",
  FAILED: "bad",
};
const MAX_TEXT = 20000;

type Mode = "file" | "text";

function JobStatus({ jobId, onAnother }: { jobId: string; onAnother: () => void }) {
  const api = useApi();
  const [job, setJob] = useState<IntakeJob | null>(null);
  const [lost, setLost] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      try {
        const { job: next } = await getIntakeJob(api, jobId);
        if (stopped) return;
        setJob(next);
        setLost(false);
        if (next.status === "READY_FOR_REVIEW" || next.status === "FAILED") return;
      } catch {
        if (stopped) return;
        setLost(true);
      }
      timer = setTimeout(poll, POLL_MS);
    }
    void poll();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [api, jobId]);

  return (
    <section className="intake-status" aria-live="polite">
      <h2 className={`status-heading ${job ? STATUS_TONE[job.status] : "accent pulse"}`}>
        {job ? labelFor(INTAKE_STATUS_LABELS, job.status) : "Checking the upload"}
      </h2>
      {job?.status === "READY_FOR_REVIEW" && (
        <p>
          {job.candidate_count === 1
            ? "1 possible report was found."
            : `${job.candidate_count} possible reports were found.`}{" "}
          A reviewer checks each one against the text before anything is published.
        </p>
      )}
      {job?.status === "FAILED" && (
        <p className="field-error" role="alert">
          {intakeFailureLabel(job.failure_reason)}
        </p>
      )}
      {job && job.status !== "READY_FOR_REVIEW" && job.status !== "FAILED" && (
        <p className="muted">This usually takes under a minute. You can leave this page.</p>
      )}
      {lost && <p className="muted">Lost contact; still trying.</p>}
      <button type="button" className="secondary" onClick={onAnother}>
        Send another
      </button>
    </section>
  );
}

export function IntakePage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [mode, setMode] = useState<Mode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  function check(): string | null {
    if (mode === "text") {
      if (!text.trim()) return "Paste the report text first.";
      if (text.length > MAX_TEXT) return `Text can be at most ${MAX_TEXT} characters.`;
      return null;
    }
    if (!file) return "Choose a file first.";
    if (!(UPLOAD_TYPES as readonly string[]).includes(file.type)) {
      return "Choose a JPEG or PNG image, or a single-page PDF.";
    }
    if (file.size > MAX_UPLOAD_BYTES) return "The file is larger than 5 MB.";
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = check();
    setError(problem);
    if (problem) return;
    setBusy(true);
    try {
      if (mode === "text") {
        setJobId((await submitText(api, incidentId, text)).job.id);
      } else if (file) {
        const form = await requestUpload(api, incidentId, file.name, file.type as UploadType);
        await uploadFile(form, file);
        setJobId(form.upload_id);
      }
    } catch {
      setError("This could not be sent. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function another() {
    setJobId(null);
    setFile(null);
    setText("");
    setError(null);
  }

  return (
    <section className="page">
      <PageHeader
        title="Upload a report"
        description="Send a scanned list, a photo of a notice or pasted text. The model suggests reports from it; nothing is published until a reviewer confirms each one. Reports are published as your organization."
      />
      {jobId ? (
        <JobStatus jobId={jobId} onAnother={another} />
      ) : (
        <form onSubmit={submit} noValidate>
          <div className="segmented intake-mode" role="group" aria-label="What to send">
            {(["file", "text"] as const).map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? "chip active" : "chip"}
                aria-pressed={mode === m}
                onClick={() => {
                  setMode(m);
                  setError(null);
                }}
              >
                {m === "file" ? "A file" : "Pasted text"}
              </button>
            ))}
          </div>
          {mode === "file" ? (
            <div className="field">
              <label htmlFor="intake-file">Image or single-page PDF, up to 5 MB</label>
              <input
                id="intake-file"
                type="file"
                accept={UPLOAD_TYPES.join(",")}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
          ) : (
            <div className="field">
              <label htmlFor="intake-text">Report text</label>
              <textarea
                id="intake-text"
                rows={10}
                maxLength={MAX_TEXT}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </div>
          )}
          {error && (
            <p className="field-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Sending" : "Send for review"}
          </button>
        </form>
      )}
    </section>
  );
}
