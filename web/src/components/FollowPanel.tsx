import { useState, type FormEvent } from "react";

import { follow, listSubscriptions, unfollow, type FollowBody } from "../api/alerts";
import { ApiError } from "../api/client";
import { useApi } from "../api/context";
import { asApiError, useLoad } from "../useLoad";
import { ErrorNotice } from "./ErrorNotice";

const E164 = /^\+[1-9][0-9]{7,14}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function check(body: FollowBody): string | null {
  if (body.channel_sms && !E164.test(body.phone_e164 ?? "")) {
    return "Enter the phone number in international format, for example +919876543210.";
  }
  if (body.channel_email && !EMAIL.test(body.email ?? "")) {
    return "Enter a valid email address.";
  }
  return null;
}

function failure(err: ApiError): string {
  if (err.code === "VALIDATION_FAILED") {
    const list = Array.isArray(err.details.errors) ? err.details.errors : [];
    const messages = list
      .map((e) => (e as { message?: unknown }).message)
      .filter((m): m is string => typeof m === "string");
    return messages.join(" ") || err.message;
  }
  return err.code === "NETWORK" ? err.message : "That did not work. Try again.";
}

/** Follow or unfollow one person. For family accounts. */
export function FollowPanel({ personId, personName }: { personId: string; personName: string }) {
  const api = useApi();
  const [version, setVersion] = useState(0);
  const [subs, retry] = useLoad(`subs|${personId}|${version}`, () => listSubscriptions(api));
  const [sms, setSms] = useState(false);
  const [mail, setMail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setVersion((v) => v + 1);
    } catch (err) {
      setError(failure(asApiError(err)));
    } finally {
      setBusy(false);
    }
  }

  function onFollow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: FollowBody = {};
    if (sms) Object.assign(body, { channel_sms: true, phone_e164: String(form.get("phone")).trim() });
    if (mail) Object.assign(body, { channel_email: true, email: String(form.get("email")).trim() });
    const problem = check(body);
    if (problem) {
      setError(problem);
      return;
    }
    void run(() => follow(api, personId, body));
  }

  if (subs.status === "loading") return <p className="muted">Checking whether you follow {personName}</p>;
  if (subs.status === "error") return <ErrorNotice error={subs.error} onRetry={retry} />;

  const mine = subs.data.find((s) => s.person_id === personId && s.active);
  return (
    <section className="follow" aria-labelledby="follow-title">
      <h2 id="follow-title">Alerts for {personName}</h2>
      {mine ? (
        <>
          <p>
            You follow {personName}. Alerts appear in the app
            {mine.channel_sms && mine.phone_e164 ? `, by text to ${mine.phone_e164}` : ""}
            {mine.channel_email && mine.email ? `, by email to ${mine.email}` : ""}.
          </p>
          <button type="button" onClick={() => void run(() => unfollow(api, mine.id))} disabled={busy}>
            {busy ? "Saving" : "Stop following"}
          </button>
        </>
      ) : (
        <form onSubmit={onFollow}>
          <p className="hint">
            You get an alert when a new report changes what is known about {personName}. Sensitive
            reports are shared by a coordinator, not by text or email.
          </p>
          <label className="inline">
            <input type="checkbox" checked={sms} onChange={(e) => setSms(e.target.checked)} />
            Also send a text message
          </label>
          {sms && (
            <label>
              Phone number
              <input name="phone" type="tel" autoComplete="tel" placeholder="+919876543210" />
            </label>
          )}
          <label className="inline">
            <input type="checkbox" checked={mail} onChange={(e) => setMail(e.target.checked)} />
            Also send an email
          </label>
          {mail && (
            <label>
              Email address
              <input name="email" type="email" autoComplete="email" />
            </label>
          )}
          <button type="submit" disabled={busy}>
            {busy ? "Saving" : "Follow"}
          </button>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
