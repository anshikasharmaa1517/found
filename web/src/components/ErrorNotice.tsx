import type { ApiError } from "../api/client";

function messageFor(error: ApiError, notFound: string): string {
  switch (error.code) {
    case "NOT_FOUND":
      return notFound;
    case "FORBIDDEN":
      return "Your account does not have access to this.";
    case "UNAUTHENTICATED":
      return "Your session has ended. Sign in again.";
    case "NETWORK":
      return error.message;
    case "BAD_REQUEST":
    case "VALIDATION_FAILED":
      return error.message;
    default:
      return "Something went wrong. Try again.";
  }
}

export function ErrorNotice({
  error,
  notFound = "Not found.",
  onRetry,
}: {
  error: ApiError;
  notFound?: string;
  onRetry?: () => void;
}) {
  const canRetry = onRetry && !["NOT_FOUND", "FORBIDDEN", "BAD_REQUEST"].includes(error.code);
  return (
    <div className="error" role="alert">
      <p>{messageFor(error, notFound)}</p>
      {canRetry && (
        <button type="button" className="link" onClick={onRetry}>
          Try again
        </button>
      )}
      {error.requestId && <p className="hint">Reference: {error.requestId}</p>}
    </div>
  );
}
