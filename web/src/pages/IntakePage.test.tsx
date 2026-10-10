import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IntakeJob } from "../api/intake";
import { userFromClaims } from "../auth/user";
import { FakeGateway, renderApp, routedApi } from "../test/fakes";
import { POLL_MS } from "./IntakePage";

const PUBLISHER = userFromClaims({
  sub: "p1",
  name: "Shelter desk",
  "cognito:groups": ["publisher"],
  "custom:org_id": "org_s",
});

function signedIn() {
  const gateway = new FakeGateway();
  gateway.user = PUBLISHER;
  return gateway;
}

function job(overrides: Partial<IntakeJob> = {}): IntakeJob {
  return {
    id: "ijb_1",
    incident_id: "inc_1",
    organization_id: "org_s",
    filename: "pasted.txt",
    content_type: "text/plain",
    status: "RECEIVED",
    sha256: null,
    size_bytes: null,
    candidate_count: 0,
    dropped_count: 0,
    failure_reason: null,
    created_at: "2026-10-05T10:15:00Z",
    updated_at: null,
    ...overrides,
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("intake page", () => {
  it("sends pasted text and follows the job until it is ready", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const states = [job({ status: "EXTRACTING" }), job({ status: "READY_FOR_REVIEW", candidate_count: 2 })];
    const { api, sent } = routedApi(
      { "/v1/intake-jobs/ijb_1": () => ({ job: states.length > 1 ? states.shift() : states[0], candidates: [] }) },
      { "/v1/incidents/inc_1/intake-text": () => ({ job: job() }) },
    );
    renderApp(signedIn(), "/incidents/inc_1/upload", api);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: "Pasted text" }));
    await user.type(screen.getByLabelText("Report text"), "Kavita Bisht, 29, is in hall B.");
    await user.click(screen.getByRole("button", { name: "Send for review" }));

    expect(await screen.findByRole("heading", { name: "Reading the report" })).toBeInTheDocument();
    expect(sent[0]).toEqual({
      path: "/v1/incidents/inc_1/intake-text",
      body: { text: "Kavita Bisht, 29, is in hall B." },
    });
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(await screen.findByRole("heading", { name: "Ready for a reviewer" })).toBeInTheDocument();
    expect(screen.getByText(/2 possible reports were found/)).toBeInTheDocument();
  });

  it("uploads a file straight to storage with the presigned form", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchImpl);
    const form = {
      upload_id: "ijb_1",
      post: { url: "https://bucket.example/", fields: { key: "intake/inc_1/ijb_1/list.png" } },
      max_bytes: 5242880,
      expires_in: 300,
    };
    const { api, sent } = routedApi(
      { "/v1/intake-jobs/ijb_1": () => ({ job: job({ status: "FAILED", failure_reason: "NO_TEXT" }), candidates: [] }) },
      { "/v1/incidents/inc_1/uploads": () => form },
    );
    renderApp(signedIn(), "/incidents/inc_1/upload", api);
    const user = userEvent.setup();
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "list.png", { type: "image/png" });
    await user.upload(await screen.findByLabelText(/Image or single-page PDF/), file);
    await user.click(screen.getByRole("button", { name: "Send for review" }));

    expect(await screen.findByText("No text could be found in it.")).toBeInTheDocument();
    expect(sent[0]).toEqual({
      path: "/v1/incidents/inc_1/uploads",
      body: { filename: "list.png", content_type: "image/png", purpose: "INTAKE" },
    });
    const [url, init] = fetchImpl.mock.calls[0]!;
    expect(url).toBe("https://bucket.example/");
    const body = init.body as FormData;
    expect(body.get("key")).toBe("intake/inc_1/ijb_1/list.png");
    expect(body.get("file")).toBeInstanceOf(File);
  });

  it("checks the file and text before sending anything", async () => {
    const { api, sent } = routedApi({});
    renderApp(signedIn(), "/incidents/inc_1/upload", api);
    const user = userEvent.setup({ applyAccept: false });
    await user.click(await screen.findByRole("button", { name: "Send for review" }));
    expect(screen.getByText("Choose a file first.")).toBeInTheDocument();
    await user.upload(screen.getByLabelText(/Image or single-page PDF/), new File(["x"], "a.zip", { type: "application/zip" }));
    await user.click(screen.getByRole("button", { name: "Send for review" }));
    expect(screen.getByText(/Choose a JPEG or PNG image/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pasted text" }));
    await user.click(screen.getByRole("button", { name: "Send for review" }));
    expect(screen.getByText("Paste the report text first.")).toBeInTheDocument();
    await waitFor(() => expect(sent).toEqual([]));
  });

  it("is only for publishers", async () => {
    const gateway = new FakeGateway();
    gateway.user = userFromClaims({ sub: "f", name: "Family", "cognito:groups": ["family"] });
    renderApp(gateway, "/incidents/inc_1/upload", routedApi({}).api);
    expect(await screen.findByText("Not available for your role")).toBeInTheDocument();
  });
});
