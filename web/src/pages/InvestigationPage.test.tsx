import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Investigation } from "../api/investigations";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, fakeSockets, renderApp, routedApi, type Call } from "../test/fakes";

const PATH = "/v1/investigations/inv_1";
const WS = "wss://ws.example.org/prod";

function as(user = REVIEWER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

function investigation(overrides: Partial<Investigation> = {}): Investigation {
  return {
    id: "inv_1",
    incident_id: "inc_1",
    claim_id: "clm_relay",
    mode: "LIVE",
    status: "NEEDS_REVIEW",
    model_id: "model-a",
    prompt_version: "lineage-v1",
    agent_version: "0.1.0",
    finding: {
      attribution: "RELAY",
      referenced_source: { id: "src_h", name: "Central Hospital Demo" },
      comparison: "SUPPORTS",
      summary: "The NGO report repeats the hospital's admission report.",
      citations: [
        { claim_id: "clm_relay", excerpt: "According to Central Hospital Demo" },
        { claim_id: "clm_src", excerpt: "admitted to ward 3 at 07:40, stable" },
      ],
    },
    outcome_reasons: ["RELAY_NOT_FIRST_HAND"],
    failure_reason: null,
    usage: {
      tool_calls: 4,
      model_calls: 5,
      input_tokens: 6120,
      output_tokens: 410,
      usage_source: "provider",
    },
    timing: {
      queued_at: "2026-10-05T10:15:00Z",
      started_at: "2026-10-05T10:15:01Z",
      finished_at: "2026-10-05T10:15:19Z",
      duration_ms: 18450,
    },
    steps: [
      {
        seq: 1,
        kind: "TOOL",
        tool: "get_report",
        summary: "Read report clm_relay from Flood Relief Demo",
        duration_ms: 120,
        input_tokens: null,
        output_tokens: null,
        error_code: null,
      },
      {
        seq: 2,
        kind: "MODEL",
        tool: null,
        summary: "Requested record_finding",
        duration_ms: 900,
        input_tokens: 1200,
        output_tokens: 80,
        error_code: null,
      },
    ],
    review: null,
    ...overrides,
  };
}

function count(calls: Call[]) {
  return calls.filter((c) => c.path === PATH).length;
}

describe("InvestigationPage", () => {
  it("shows the labeled finding, why it needs a reviewer, the steps and the run", async () => {
    const { api } = routedApi({ [PATH]: () => investigation() });
    renderApp(as(), "/investigations/inv_1", api);

    expect(await screen.findByRole("heading", { name: "Finding" })).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText(/Status: Needs a reviewer/)).toBeInTheDocument();
    const finding = screen.getByRole("region", { name: "Finding" });
    expect(within(finding).getByText(/Relayed: it passes on another source's report/)).toBeInTheDocument();
    expect(within(finding).getByText("Central Hospital Demo")).toBeInTheDocument();
    expect(within(finding).getByText("Matches the named source's own reports")).toBeInTheDocument();
    expect(within(finding).getByText("admitted to ward 3 at 07:40, stable")).toBeInTheDocument();
    expect(
      within(finding).getByText("A relay is not independent confirmation, even when it agrees."),
    ).toBeInTheDocument();

    expect(screen.getByText("get_report")).toBeInTheDocument();
    expect(screen.getByText("Read report clm_relay from Flood Relief Demo")).toBeInTheDocument();
    expect(screen.getByText("1200 tokens in, 80 out")).toBeInTheDocument();
    expect(screen.getByText(/5 model calls, 4 tool calls/)).toBeInTheDocument();
    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();
  });

  it("labels a stored result served again as cached", async () => {
    const { api } = routedApi({ [PATH]: () => investigation() });
    renderApp(as(), "/investigations/inv_1?served=cached", api);
    expect(await screen.findByText("CACHED")).toBeInTheDocument();
    expect(screen.getByText(/no new model call/)).toBeInTheDocument();
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("says why a run failed", async () => {
    const failed = investigation({ status: "FAILED", finding: null, outcome_reasons: [], failure_reason: "TURN_LIMIT" });
    const { api } = routedApi({ [PATH]: () => failed });
    renderApp(as(), "/investigations/inv_1", api);
    expect(await screen.findByText("The run reached its limit of model turns.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Finding" })).not.toBeInTheDocument();
  });

  it("refetches when a step of this run arrives, and only then", async () => {
    let current = investigation({ status: "RUNNING", finding: null, outcome_reasons: [], steps: [] });
    const { api, calls } = routedApi({ [PATH]: () => current });
    const { sockets, createSocket } = fakeSockets();
    localStorage.setItem("found.incidentId", "inc_1");
    renderApp(as(), "/investigations/inv_1", api, { wsUrl: WS, createSocket });
    expect(await screen.findByText(/this page updates as steps arrive/)).toBeInTheDocument();
    expect(screen.getByText("No steps yet.")).toBeInTheDocument();
    await waitFor(() => expect(sockets).toHaveLength(1));
    act(() => sockets[0]!.open());

    const before = count(calls);
    act(() =>
      sockets[0]!.push({
        type: "investigation.step",
        incident_id: "inc_1",
        investigation_id: "inv_other",
        seq: 1,
        kind: "TOOL",
        tool: "get_report",
        summary: "x",
      }),
    );
    current = investigation();
    act(() =>
      sockets[0]!.push({
        type: "investigation.updated",
        incident_id: "inc_1",
        investigation_id: "inv_1",
        claim_id: "clm_relay",
        status: "NEEDS_REVIEW",
      }),
    );
    expect(await screen.findByRole("heading", { name: "Finding" })).toBeInTheDocument();
    expect(count(calls)).toBe(before + 1);
    localStorage.clear();
  });

  it("is for reviewers and admins only", async () => {
    const { api } = routedApi({ [PATH]: () => investigation() });
    const family = userFromClaims({ sub: "f", name: "Asha", "cognito:groups": ["family"] });
    renderApp(as(family), "/investigations/inv_1", api);
    expect(await screen.findByText("Not available for your role")).toBeInTheDocument();
  });

  it("says when the investigation does not exist", async () => {
    renderApp(as(), "/investigations/inv_x", routedApi({}).api);
    expect(await screen.findByText("This investigation was not found.")).toBeInTheDocument();
  });
});
