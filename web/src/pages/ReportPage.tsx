import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { publishReport, type PublishResult } from "../api/reports";
import { PersonPicker, type Picked } from "../components/PersonPicker";
import { rememberIncident } from "../incident";
import { claimTypeLabel } from "../labels";
import {
  browserOffsetMinutes,
  buildBody,
  errorsFromApi,
  formatOffset,
  LIMITS,
  PERSON_CLAIM_TYPES,
  validate,
  type FieldErrors,
  type ReportValues,
} from "../reportForm";
import { asApiError } from "../useLoad";

const EMPTY: ReportValues = {
  subjectMode: "new",
  personId: "",
  name: "",
  age: "",
  notes: "",
  claimType: "",
  value: "",
  originalText: "",
  reference: "",
  reportedAt: "",
  timeUnknown: false,
  placeName: "",
  lat: "",
  lon: "",
};

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: ReactNode;
  children: (ids: { id: string; describedBy?: string; invalid?: "true" }) => ReactNode;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children({
        id,
        describedBy: error || hint ? noteId : undefined,
        invalid: error ? "true" : undefined,
      })}
      {(error || hint) && (
        <p id={noteId} className={error ? "field-error" : "hint"}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

function errorsFor(err: ApiError): FieldErrors {
  switch (err.code) {
    case "VALIDATION_FAILED": {
      const mapped = errorsFromApi(err.details);
      return Object.keys(mapped).length ? mapped : { form: err.message };
    }
    case "REFERENCE_CONFLICT":
      return {
        reference:
          "This reference was already used for a different report. Use a new reference, " +
          "or check the earlier report.",
      };
    case "FORBIDDEN":
      return { form: "Your organization is not registered for this incident." };
    case "NOT_FOUND":
      return { form: "The incident or the chosen person was not found." };
    case "NETWORK":
      return { form: `${err.message} Nothing was stored. Submitting again is safe.` };
    default:
      return { form: "The report could not be stored. Submitting again with the same reference is safe." };
  }
}

export function ReportPage() {
  const incidentId = useParams().incidentId ?? "";
  const api = useApi();
  const [params] = useSearchParams();
  const startPerson = params.get("person");
  const [values, setValues] = useState<ReportValues>(() => ({
    ...EMPTY,
    subjectMode: startPerson ? "existing" : "new",
    personId: startPerson ?? "",
  }));
  const [picked, setPicked] = useState<Picked | null>(() =>
    startPerson ? { id: startPerson, name: params.get("name") || startPerson } : null,
  );
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PublishResult | null>(null);

  useEffect(() => rememberIncident(incidentId), [incidentId]);

  function set<K extends keyof ReportValues>(key: K, value: ReportValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  function pick(person: Picked | null) {
    setPicked(person);
    set("personId", person?.id ?? "");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    try {
      setResult(await publishReport(api, incidentId, buildBody(values)));
    } catch (err) {
      setErrors(errorsFor(asApiError(err)));
    } finally {
      setBusy(false);
    }
  }

  function another() {
    setResult(null);
    setErrors({});
    setPicked(null);
    setValues(EMPTY);
  }

  if (result) {
    const { claim, replayed } = result;
    return (
      <section className="page">
        <div className="summary" role="status">
          <h1>{replayed ? "Already stored" : "Report stored"}</h1>
          <p>
            {replayed
              ? "This reference was already submitted with the same content. Nothing new was stored."
              : `Stored as ${claimTypeLabel(claim.claim_type)} from ${claim.source.name}, report ${claim.seq} for this person.`}
          </p>
          <p>
            <Link to={`/people/${encodeURIComponent(claim.subject_id)}`}>View the timeline</Link>
          </p>
        </div>
        <button type="button" onClick={another}>
          Publish another report
        </button>
      </section>
    );
  }

  const offset =
    !values.timeUnknown && values.reportedAt
      ? formatOffset(browserOffsetMinutes(values.reportedAt))
      : null;

  return (
    <section className="page">
      <h1>Publish a report</h1>
      <p className="muted">
        Incident {incidentId}. The report is published as your organization and cannot be edited
        later; a correction is a new report.
      </p>

      <form className="report" onSubmit={onSubmit} noValidate>
        {errors.form && (
          <p className="error" role="alert">
            {errors.form}
          </p>
        )}

        <fieldset>
          <legend>Who is it about</legend>
          <div className="choice-row">
            <label className="inline">
              <input
                type="radio"
                name="subjectMode"
                checked={values.subjectMode === "existing"}
                onChange={() => set("subjectMode", "existing")}
              />
              A person already listed
            </label>
            <label className="inline">
              <input
                type="radio"
                name="subjectMode"
                checked={values.subjectMode === "new"}
                onChange={() => set("subjectMode", "new")}
              />
              New person
            </label>
          </div>
          {values.subjectMode === "existing" ? (
            <PersonPicker incidentId={incidentId} picked={picked} onPick={pick} error={errors.personId} />
          ) : (
            <>
              <Field label="Name as reported" error={errors.name}>
                {(f) => (
                  <input
                    id={f.id}
                    value={values.name}
                    onChange={(e) => set("name", e.target.value)}
                    maxLength={LIMITS.name}
                    aria-describedby={f.describedBy}
                    aria-invalid={f.invalid}
                  />
                )}
              </Field>
              <Field label="Age (optional)" error={errors.age}>
                {(f) => (
                  <input
                    id={f.id}
                    type="number"
                    min={0}
                    max={120}
                    value={values.age}
                    onChange={(e) => set("age", e.target.value)}
                    aria-describedby={f.describedBy}
                    aria-invalid={f.invalid}
                  />
                )}
              </Field>
              <Field
                label="Description (optional)"
                error={errors.notes}
                hint="For example clothing. Do not add identity numbers."
              >
                {(f) => (
                  <input
                    id={f.id}
                    value={values.notes}
                    onChange={(e) => set("notes", e.target.value)}
                    maxLength={LIMITS.notes}
                    aria-describedby={f.describedBy}
                    aria-invalid={f.invalid}
                  />
                )}
              </Field>
            </>
          )}
        </fieldset>

        <fieldset>
          <legend>What the report says</legend>
          <Field
            label="Report type"
            error={errors.claimType}
            hint={
              values.claimType === "DECEASED"
                ? "Alerts for this report are held for a reviewer. Families are not sent SMS or email until a coordinator releases it."
                : undefined
            }
          >
            {(f) => (
              <select
                id={f.id}
                value={values.claimType}
                onChange={(e) => set("claimType", e.target.value)}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              >
                <option value="">Choose</option>
                {PERSON_CLAIM_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {claimTypeLabel(type)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Short detail (optional)" error={errors.value} hint="For example: Admitted, stable condition.">
            {(f) => (
              <input
                id={f.id}
                value={values.value}
                onChange={(e) => set("value", e.target.value)}
                maxLength={LIMITS.value}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              />
            )}
          </Field>
          <Field
            label="Report text as received"
            error={errors.originalText}
            hint={`${values.originalText.length} of ${LIMITS.text} characters. Stored exactly as given.`}
          >
            {(f) => (
              <textarea
                id={f.id}
                rows={6}
                value={values.originalText}
                onChange={(e) => set("originalText", e.target.value)}
                maxLength={LIMITS.text}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              />
            )}
          </Field>
        </fieldset>

        <fieldset>
          <legend>When and which record</legend>
          <Field
            label="When it happened"
            error={errors.reportedAt}
            hint={
              values.timeUnknown
                ? "Reports without a time are marked for review."
                : offset && `Your time zone, UTC${offset}.`
            }
          >
            {(f) => (
              <input
                id={f.id}
                type="datetime-local"
                value={values.reportedAt}
                onChange={(e) => set("reportedAt", e.target.value)}
                disabled={values.timeUnknown}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              />
            )}
          </Field>
          <label className="inline">
            <input
              type="checkbox"
              checked={values.timeUnknown}
              onChange={(e) => set("timeUnknown", e.target.checked)}
            />
            The time is not known
          </label>
          <Field
            label="Your reference"
            error={errors.reference}
            hint="Your own record number, for example CH-2026-0412. Sending the same reference again never stores a duplicate."
          >
            {(f) => (
              <input
                id={f.id}
                value={values.reference}
                onChange={(e) => set("reference", e.target.value)}
                maxLength={LIMITS.reference}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              />
            )}
          </Field>
        </fieldset>

        <fieldset>
          <legend>Where (optional)</legend>
          <p className="hint">
            The place as the report names it. It is shown on the map as reported, not verified.
          </p>
          <Field label="Place name" error={errors.placeName}>
            {(f) => (
              <input
                id={f.id}
                value={values.placeName}
                onChange={(e) => set("placeName", e.target.value)}
                maxLength={LIMITS.place}
                aria-describedby={f.describedBy}
                aria-invalid={f.invalid}
              />
            )}
          </Field>
          <div className="pair">
            <Field label="Latitude" error={errors.lat}>
              {(f) => (
                <input
                  id={f.id}
                  inputMode="decimal"
                  value={values.lat}
                  onChange={(e) => set("lat", e.target.value)}
                  aria-describedby={f.describedBy}
                  aria-invalid={f.invalid}
                />
              )}
            </Field>
            <Field label="Longitude" error={errors.lon}>
              {(f) => (
                <input
                  id={f.id}
                  inputMode="decimal"
                  value={values.lon}
                  onChange={(e) => set("lon", e.target.value)}
                  aria-describedby={f.describedBy}
                  aria-invalid={f.invalid}
                />
              )}
            </Field>
          </div>
        </fieldset>

        <button type="submit" disabled={busy}>
          {busy ? "Publishing" : "Publish report"}
        </button>
      </form>
    </section>
  );
}
