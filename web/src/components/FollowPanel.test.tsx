import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Subscription } from "../api/alerts";
import { ApiError } from "../api/client";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

const FAMILY = userFromClaims({ sub: "fam_1", name: "Asha", "cognito:groups": ["family"] });
const TIMELINE = "/v1/people/per_1/timeline";
const SUBS = "/v1/me/subscriptions";
const FOLLOW = "/v1/people/per_1/subscriptions";

const timeline = () => ({
  person: { id: "per_1", name: "Maya Rawat", age: 24 },
  summary: { label: "Reported missing", basis: "b", cited_claim_id: null, conflicts: [], needs_review: false },
  identity: [],
  entries: [],
  next_cursor: null,
});

function sub(overrides: Partial<Subscription> = {}): Subscription {
  return {
    id: "sub_1",
    person_id: "per_1",
    channel_inapp: true,
    channel_sms: false,
    channel_email: false,
    phone_e164: null,
    email: null,
    active: true,
    created_at: "2026-10-05T10:15:00Z",
    ...overrides,
  };
}

function as(user = FAMILY) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

describe("follow panel", () => {
  it("follows with a text message and then shows how alerts arrive", async () => {
    let subs: Subscription[] = [];
    const { api, sent } = routedApi(
      { [TIMELINE]: timeline, [SUBS]: () => ({ subscriptions: subs }) },
      {
        [FOLLOW]: (body) => {
          subs = [sub({ channel_sms: true, phone_e164: "+919876543210" })];
          return { subscription: subs[0], body };
        },
      },
    );
    renderApp(as(), "/people/per_1", api);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("Also send a text message"));
    await user.type(screen.getByLabelText("Phone number"), "98765");
    await user.click(screen.getByRole("button", { name: "Follow" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("international format");
    expect(sent).toEqual([]);

    await user.clear(screen.getByLabelText("Phone number"));
    await user.type(screen.getByLabelText("Phone number"), "+919876543210");
    await user.click(screen.getByRole("button", { name: "Follow" }));
    expect(await screen.findByText(/You follow Maya Rawat/)).toHaveTextContent("by text to +919876543210");
    expect(sent[0]).toEqual({
      path: FOLLOW,
      body: { channel_sms: true, phone_e164: "+919876543210" },
    });
  });

  it("stops following", async () => {
    let subs = [sub()];
    const { api, sent } = routedApi(
      { [TIMELINE]: timeline, [SUBS]: () => ({ subscriptions: subs }) },
      {},
      { "/v1/subscriptions/sub_1": () => (subs = []) },
    );
    renderApp(as(), "/people/per_1", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Stop following" }));
    expect(await screen.findByRole("button", { name: "Follow" })).toBeInTheDocument();
    expect(sent.at(-1)?.path).toBe("/v1/subscriptions/sub_1");
  });

  it("shows the API's reason when following fails", async () => {
    const { api } = routedApi(
      { [TIMELINE]: timeline, [SUBS]: () => ({ subscriptions: [] }) },
      {
        [FOLLOW]: () => {
          throw new ApiError(422, "VALIDATION_FAILED", "Subscription is invalid.", {
            errors: [{ field: "", message: "Value error, SMS alerts need phone_e164" }],
          });
        },
      },
    );
    renderApp(as(), "/people/per_1", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Follow" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("SMS alerts need phone_e164");
  });

  it("is shown only to family accounts", async () => {
    const { api } = routedApi({ [TIMELINE]: timeline });
    renderApp(as(REVIEWER), "/people/per_1", api);
    await screen.findByRole("heading", { name: "Maya Rawat" });
    expect(screen.queryByRole("heading", { name: /Alerts for/ })).not.toBeInTheDocument();
  });
});
