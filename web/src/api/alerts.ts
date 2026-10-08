/** Following people and the alert feed (design Section 7.4). Family accounts only. */

import type { ApiClient } from "./client";

export type DeliveryStatus = "NOT_REQUIRED" | "HELD" | "PENDING" | "SENDING" | "SENT" | "FAILED";

export interface Alert {
  id: string;
  incident_id: string;
  person_id: string;
  claim_id: string;
  relation: string;
  severity: "info" | "high";
  message: string;
  delivery_status: DeliveryStatus;
  created_at: string;
}

export interface AlertPage {
  alerts: Alert[];
  next_cursor: string | null;
}

export interface Subscription {
  id: string;
  person_id: string;
  channel_inapp: boolean;
  channel_sms: boolean;
  channel_email: boolean;
  phone_e164: string | null;
  email: string | null;
  active: boolean;
  created_at: string;
}

export interface FollowBody {
  channel_sms?: boolean;
  phone_e164?: string;
  channel_email?: boolean;
  email?: string;
}

export const DELIVERY_LABELS: Record<DeliveryStatus, string> = {
  NOT_REQUIRED: "In the app only",
  HELD: "A coordinator will contact you",
  PENDING: "Text or email on its way",
  SENDING: "Text or email on its way",
  SENT: "Also sent by text or email",
  FAILED: "Text or email could not be sent",
};

export function listAlerts(api: ApiClient, cursor?: string): Promise<AlertPage> {
  return api.get<AlertPage>("/v1/me/alerts", { cursor });
}

export async function listSubscriptions(api: ApiClient): Promise<Subscription[]> {
  return (await api.get<{ subscriptions: Subscription[] }>("/v1/me/subscriptions")).subscriptions;
}

export async function follow(api: ApiClient, personId: string, body: FollowBody): Promise<Subscription> {
  const result = await api.post<{ subscription: Subscription }>(
    `/v1/people/${encodeURIComponent(personId)}/subscriptions`,
    body,
  );
  return result.subscription;
}

export function unfollow(api: ApiClient, subscriptionId: string): Promise<void> {
  return api.del(`/v1/subscriptions/${encodeURIComponent(subscriptionId)}`);
}
