/**
 * Form rules for publishing a report. They mirror the API so mistakes show before
 * sending; the API still validates everything.
 */

import type { ReportBody } from "./api/reports";

export const PERSON_CLAIM_TYPES = [
  "MISSING",
  "FOUND_SAFE",
  "INJURED",
  "DECEASED",
  "SEEN_AT_LOCATION",
  "SHELTERED",
  "OTHER",
] as const;

export const LIMITS = {
  name: 120,
  notes: 500,
  value: 500,
  text: 4000,
  reference: 64,
  place: 120,
} as const;
const REFERENCE = /^[A-Za-z0-9._-]{1,64}$/;
const LOCAL_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

export interface ReportValues {
  subjectMode: "existing" | "new";
  personId: string;
  name: string;
  age: string;
  notes: string;
  claimType: string;
  value: string;
  originalText: string;
  reference: string;
  /** `YYYY-MM-DDTHH:MM` from a datetime-local input, in the browser's time zone. */
  reportedAt: string;
  timeUnknown: boolean;
  /** Optional place as reported; coordinates are optional but come as a pair. */
  placeName: string;
  lat: string;
  lon: string;
}

export type FieldErrors = Partial<Record<keyof ReportValues | "form", string>>;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** UTC offset in minutes that the browser uses for a local date and time. */
export function browserOffsetMinutes(local: string): number {
  return -new Date(local).getTimezoneOffset();
}

export function formatOffset(minutes: number): string {
  const sign = minutes < 0 ? "-" : "+";
  const abs = Math.abs(minutes);
  return `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

/** `2026-10-03T07:40` and +330 become `2026-10-03T07:40:00+05:30`; the offset is kept. */
export function toOffsetIso(local: string, offsetMinutes: number): string {
  return `${local}:00${formatOffset(offsetMinutes)}`;
}

function coordinate(raw: string, limit: number): number | null {
  if (!raw.trim()) return null;
  const value = Number(raw);
  return Number.isFinite(value) && Math.abs(value) <= limit ? value : Number.NaN;
}

function placeErrors(values: ReportValues): FieldErrors {
  const errors: FieldErrors = {};
  const name = values.placeName.trim();
  const lat = coordinate(values.lat, 90);
  const lon = coordinate(values.lon, 180);
  if (name.length > LIMITS.place) errors.placeName = `Use at most ${LIMITS.place} characters.`;
  if (Number.isNaN(lat)) errors.lat = "Latitude must be a number from -90 to 90.";
  if (Number.isNaN(lon)) errors.lon = "Longitude must be a number from -180 to 180.";
  if (!errors.lat && !errors.lon && (lat === null) !== (lon === null)) {
    errors[lat === null ? "lat" : "lon"] = "Give both latitude and longitude, or neither.";
  }
  if (!name && (lat !== null || lon !== null)) {
    errors.placeName = "Name the place the coordinates belong to.";
  }
  return errors;
}

export function validate(values: ReportValues): FieldErrors {
  const errors: FieldErrors = {};
  if (values.subjectMode === "existing" && !values.personId) {
    errors.personId = "Choose the person this report is about.";
  }
  if (values.subjectMode === "new") {
    const name = values.name.trim();
    if (!name) errors.name = "Enter the person's name as reported.";
    else if (name.length > LIMITS.name) errors.name = `Use at most ${LIMITS.name} characters.`;
    if (values.age.trim()) {
      const age = Number(values.age);
      if (!Number.isInteger(age) || age < 0 || age > 120) errors.age = "Age must be 0 to 120.";
    }
    if (values.notes.length > LIMITS.notes) errors.notes = `Use at most ${LIMITS.notes} characters.`;
  }
  if (!(PERSON_CLAIM_TYPES as readonly string[]).includes(values.claimType)) {
    errors.claimType = "Choose what the report says.";
  }
  if (values.value.length > LIMITS.value) errors.value = `Use at most ${LIMITS.value} characters.`;
  const text = values.originalText.trim();
  if (!text) errors.originalText = "Paste or type the report as received.";
  else if (text.length > LIMITS.text) errors.originalText = `Use at most ${LIMITS.text} characters.`;
  if (!REFERENCE.test(values.reference.trim())) {
    errors.reference = "Use 1 to 64 letters, digits, dots, dashes or underscores.";
  }
  Object.assign(errors, placeErrors(values));
  if (!values.timeUnknown && !LOCAL_TIME.test(values.reportedAt)) {
    errors.reportedAt = "Enter when this happened, or tick that the time is unknown.";
  }
  return errors;
}

export function buildBody(
  values: ReportValues,
  offsetFor: (local: string) => number = browserOffsetMinutes,
): ReportBody {
  const value = values.value.trim();
  const body: ReportBody = {
    subject:
      values.subjectMode === "existing"
        ? { type: "PERSON", id: values.personId }
        : {
            type: "PERSON",
            new: {
              name: values.name.trim(),
              ...(values.age.trim() ? { age: Number(values.age) } : {}),
              ...(values.notes.trim() ? { notes: values.notes.trim() } : {}),
            },
          },
    claim_type: values.claimType,
    original_text: values.originalText.trim(),
    external_reference: values.reference.trim(),
  };
  if (value) body.value = value;
  const place = values.placeName.trim();
  if (place) {
    body.location = { name: place };
    if (values.lat.trim() && values.lon.trim()) {
      body.location.lat = Number(values.lat);
      body.location.lon = Number(values.lon);
    }
  }
  // An unknown time is sent as missing, never guessed; the watcher flags it for review.
  if (!values.timeUnknown) body.reported_at = toOffsetIso(values.reportedAt, offsetFor(values.reportedAt));
  return body;
}

const API_FIELDS: Record<string, keyof ReportValues> = {
  "subject.id": "personId",
  "subject.new.name": "name",
  "subject.new.age": "age",
  "subject.new.notes": "notes",
  claim_type: "claimType",
  value: "value",
  original_text: "originalText",
  external_reference: "reference",
  reported_at: "reportedAt",
  location: "placeName",
  "location.name": "placeName",
  "location.lat": "lat",
  "location.lon": "lon",
};

/** Places the API's field errors next to the matching inputs; the rest go on top. */
export function errorsFromApi(details: Record<string, unknown>): FieldErrors {
  const errors: FieldErrors = {};
  const list = Array.isArray(details.errors) ? details.errors : [];
  for (const item of list) {
    const { field, message } = (item ?? {}) as { field?: unknown; message?: unknown };
    const text = typeof message === "string" ? message : "Not valid.";
    const key = (typeof field === "string" && API_FIELDS[field]) || "form";
    errors[key] = errors[key] ? `${errors[key]} ${text}` : text;
  }
  return errors;
}
