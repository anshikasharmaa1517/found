/** AuthGateway over Amazon Cognito with SRP sign-in (no hosted UI). */

import { Amplify } from "aws-amplify";
import {
  confirmSignIn,
  fetchAuthSession,
  signIn,
  signOut,
  type SignInOutput,
} from "aws-amplify/auth";

import type { AppConfig } from "../config";
import type { AuthGateway, SignInStep } from "./gateway";
import { userFromClaims } from "./user";

function stepOf(output: SignInOutput): SignInStep {
  if (output.isSignedIn) return { kind: "done" };
  const step = output.nextStep.signInStep;
  switch (step) {
    case "DONE":
      return { kind: "done" };
    // Accounts are created by an admin with a temporary password.
    case "CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED":
      return { kind: "newPassword" };
    case "CONFIRM_SIGN_IN_WITH_TOTP_CODE":
      return { kind: "totp" };
    default:
      return { kind: "unsupported", step };
  }
}

export function cognitoGateway(config: AppConfig): AuthGateway {
  Amplify.configure({
    Auth: {
      Cognito: { userPoolId: config.userPoolId, userPoolClientId: config.userPoolClientId },
    },
  });

  // Refreshes expired tokens with the refresh token when it can.
  async function idTokenClaims() {
    try {
      const session = await fetchAuthSession();
      return session.tokens?.idToken ?? null;
    } catch {
      return null;
    }
  }

  return {
    async currentUser() {
      const token = await idTokenClaims();
      return token ? userFromClaims(token.payload as Record<string, unknown>) : null;
    },
    async idToken() {
      const token = await idTokenClaims();
      return token ? token.toString() : null;
    },
    async signIn(email, password) {
      return stepOf(await signIn({ username: email.trim(), password }));
    },
    async respond(answer) {
      return stepOf(await confirmSignIn({ challengeResponse: answer }));
    },
    async signOut() {
      await signOut();
    },
  };
}
