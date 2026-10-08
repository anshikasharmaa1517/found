/** What the app needs from the sign-in provider. Tests use a fake; the app uses Cognito. */

import type { User } from "./user";

export type SignInStep =
  | { kind: "done" }
  | { kind: "newPassword" }
  | { kind: "totp" }
  | { kind: "unsupported"; step: string };

export interface AuthGateway {
  currentUser(): Promise<User | null>;
  idToken(): Promise<string | null>;
  signIn(email: string, password: string): Promise<SignInStep>;
  /** Answers the pending challenge: a new password or a one-time code. */
  respond(answer: string): Promise<SignInStep>;
  signOut(): Promise<void>;
}

/** Plain-language text for provider errors. Never says whether an account exists. */
export function signInErrorMessage(error: unknown): string {
  const name = error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAuthorizedException":
    case "UserNotFoundException":
      return "Email or password is incorrect.";
    case "InvalidPasswordException":
      return "The new password needs at least 12 characters, with upper and lower case letters and a number.";
    case "CodeMismatchException":
      return "That code is not right. Check your authenticator app and try again.";
    case "LimitExceededException":
    case "TooManyRequestsException":
    case "TooManyFailedAttemptsException":
      return "Too many attempts. Wait a few minutes and try again.";
    case "PasswordResetRequiredException":
      return "Your password must be reset. Ask an admin to reset it.";
    case "NetworkError":
      return "Cannot reach the sign-in service. Check your connection.";
    default:
      return "Sign-in failed. Try again.";
  }
}
