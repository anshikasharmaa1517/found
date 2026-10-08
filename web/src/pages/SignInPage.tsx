import { useId, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/context";
import { signInErrorMessage, type SignInStep } from "../auth/gateway";

const UNSUPPORTED = "This account needs a sign-in step the app does not support yet. Ask an admin.";

function afterSignIn(location: ReturnType<typeof useLocation>): string {
  const from = (location.state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith("/") && from !== "/sign-in" ? from : "/";
}

export function SignInPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const errorId = useId();

  if (auth.state.status === "signedIn") return <Navigate to={afterSignIn(location)} replace />;

  async function run(action: () => Promise<SignInStep>) {
    setBusy(true);
    setError(null);
    try {
      const step = await action();
      if (step.kind === "done") navigate(afterSignIn(location), { replace: true });
      if (step.kind === "unsupported") setError(UNSUPPORTED);
    } catch (err) {
      setError(signInErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function onSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(() => auth.signIn(String(form.get("email")), String(form.get("password"))));
  }

  function onNewPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password !== String(form.get("confirm"))) {
      setError("The two passwords do not match.");
      return;
    }
    void run(() => auth.respond(password));
  }

  function onCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void run(() => auth.respond(String(form.get("code")).trim()));
  }

  const challenge = auth.state.status === "challenge" ? auth.state.challenge : null;
  const describedBy = error ? errorId : undefined;

  return (
    <main className="sign-in">
      <section className="card" aria-labelledby="sign-in-title">
        <p className="brand">Found</p>
        {challenge === null && (
          <form onSubmit={onSignIn} noValidate={false}>
            <h1 id="sign-in-title">Sign in</h1>
            <label>
              Email
              <input name="email" type="email" autoComplete="username" required aria-describedby={describedBy} />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
                aria-describedby={describedBy}
              />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? "Signing in" : "Sign in"}
            </button>
            <p className="hint">Accounts are created by an admin. There is no self sign-up.</p>
          </form>
        )}
        {challenge === "newPassword" && (
          <form onSubmit={onNewPassword}>
            <h1 id="sign-in-title">Choose a new password</h1>
            <p className="hint">
              Your account was created with a temporary password. Choose your own: at least 12
              characters, with upper and lower case letters and a number.
            </p>
            <label>
              New password
              <input name="password" type="password" autoComplete="new-password" minLength={12} required />
            </label>
            <label>
              Repeat new password
              <input name="confirm" type="password" autoComplete="new-password" minLength={12} required />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? "Saving" : "Save and sign in"}
            </button>
          </form>
        )}
        {challenge === "totp" && (
          <form onSubmit={onCode}>
            <h1 id="sign-in-title">Enter your code</h1>
            <label>
              Six-digit code from your authenticator app
              <input
                name="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                required
              />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? "Checking" : "Continue"}
            </button>
          </form>
        )}
        {error && (
          <p id={errorId} className="error" role="alert">
            {error}
          </p>
        )}
      </section>
    </main>
  );
}
