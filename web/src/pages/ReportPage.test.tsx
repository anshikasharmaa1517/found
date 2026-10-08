import { screen } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { ReportBody } from "../api/reports";
import { userFromClaims } from "../auth/user";
import { FakeGateway, REVIEWER, renderApp, routedApi } from "../test/fakes";

const REPORTS = "/v1/incidents/inc_1/reports";
const PEOPLE = "/v1/incidents/inc_1/people";

const PUBLISHER = userFromClaims({
  sub: "pub_1",
  email: "desk@hospital.example.org",
  "cognito:groups": ["publisher"],
  "custom:org_id": "org_h",
});

function as(user = PUBLISHER) {
  const gateway = new FakeGateway();
  gateway.user = user;
  return gateway;
}

function stored(replayed = false) {
  return () => ({
    claim: {
      id: "clm_9",
      incident_id: "inc_1",
      subject_id: "per_9",
      source: { id: "src_h", name: "Central Hospital Demo", type: "HOSPITAL" },
      seq: 2,
      claim_type: "FOUND_SAFE",
      reported_at: "2026-10-03T02:10:00Z",
      ingested_at: "2026-10-05T10:15:22Z",
    },
    replayed,
  });
}

async function fillNewPerson(user: UserEvent) {
  await user.type(await screen.findByLabelText("Name as reported"), "Maya Rawat");
  await user.type(screen.getByLabelText("Age (optional)"), "24");
  await user.selectOptions(screen.getByLabelText("Report type"), "FOUND_SAFE");
  await user.type(screen.getByLabelText("Report text as received"), "Maya Rawat admitted, stable.");
  await user.click(screen.getByLabelText("The time is not known"));
  await user.type(screen.getByLabelText("Your reference"), "CH-2026-0412");
}

afterEach(() => localStorage.clear());

describe("report page", () => {
  it("publishes a new-person report and links to the timeline", async () => {
    const { api, sent } = routedApi({}, { [REPORTS]: stored() });
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await fillNewPerson(user);
    await user.click(screen.getByRole("button", { name: "Publish report" }));

    expect(await screen.findByRole("heading", { name: "Report stored" })).toBeInTheDocument();
    expect(screen.getByText(/Found safe from Central Hospital Demo, report 2/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View the timeline" })).toHaveAttribute(
      "href",
      "/people/per_9",
    );
    const body = sent[0]!.body as ReportBody;
    expect(body).toEqual({
      subject: { type: "PERSON", new: { name: "Maya Rawat", age: 24 } },
      claim_type: "FOUND_SAFE",
      original_text: "Maya Rawat admitted, stable.",
      external_reference: "CH-2026-0412",
    });
  });

  it("says plainly when a retry was already stored", async () => {
    const { api } = routedApi({}, { [REPORTS]: stored(true) });
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await fillNewPerson(user);
    await user.click(screen.getByRole("button", { name: "Publish report" }));
    expect(await screen.findByRole("heading", { name: "Already stored" })).toBeInTheDocument();
    expect(screen.getByText(/Nothing new was stored/)).toBeInTheDocument();
  });

  it("shows problems next to fields before sending anything", async () => {
    const { api, sent } = routedApi({}, { [REPORTS]: stored() });
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Publish report" }));
    expect(await screen.findByText("Enter the person's name as reported.")).toBeInTheDocument();
    expect(screen.getByLabelText("Your reference")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/or tick that the time is unknown/)).toBeInTheDocument();
    expect(sent).toEqual([]);
  });

  it("explains a reference already used for different content", async () => {
    const { api } = routedApi(
      {},
      {
        [REPORTS]: () => {
          throw new ApiError(409, "REFERENCE_CONFLICT", "Exists.", { existing_claim_id: "clm_1" });
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await fillNewPerson(user);
    await user.click(screen.getByRole("button", { name: "Publish report" }));
    expect(await screen.findByText(/already used for a different report/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your reference")).toHaveAttribute("aria-invalid", "true");
  });

  it("puts the API's field errors next to the right input", async () => {
    const { api } = routedApi(
      {},
      {
        [REPORTS]: () => {
          throw new ApiError(422, "VALIDATION_FAILED", "Report is invalid.", {
            errors: [{ field: "original_text", message: "Text is too long for the server." }],
          });
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await fillNewPerson(user);
    await user.click(screen.getByRole("button", { name: "Publish report" }));
    expect(await screen.findByText("Text is too long for the server.")).toBeInTheDocument();
  });

  it("says a network failure stored nothing and retrying is safe", async () => {
    const { api } = routedApi(
      {},
      {
        [REPORTS]: () => {
          throw new ApiError(0, "NETWORK", "Cannot reach the server. Check your connection.");
        },
      },
    );
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await fillNewPerson(user);
    await user.click(screen.getByRole("button", { name: "Publish report" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Submitting again is safe.");
  });

  it("finds an existing person and sends the reported time with its offset", async () => {
    const { api, sent } = routedApi(
      { [PEOPLE]: () => ({ people: [{ id: "per_1", name: "Maya Rawat", age: 24 }], next_cursor: null }) },
      { [REPORTS]: stored() },
    );
    renderApp(as(), "/incidents/inc_1/report", api);
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText("A person already listed"));
    await user.type(screen.getByLabelText("Name"), "rawat");
    await user.click(screen.getByRole("button", { name: "Find" }));
    await user.click(await screen.findByRole("button", { name: "Maya Rawat" }));
    expect(screen.getByText(/Report about/)).toHaveTextContent("Report about Maya Rawat");

    await user.selectOptions(screen.getByLabelText("Report type"), "FOUND_SAFE");
    await user.type(screen.getByLabelText("Report text as received"), "Admitted.");
    await user.type(screen.getByLabelText("When it happened"), "2026-10-03T07:40");
    await user.type(screen.getByLabelText("Your reference"), "CH-1");
    await user.click(screen.getByRole("button", { name: "Publish report" }));
    await screen.findByRole("heading", { name: "Report stored" });

    const body = sent[0]!.body as ReportBody;
    expect(body.subject).toEqual({ type: "PERSON", id: "per_1" });
    expect(body.reported_at).toMatch(/^2026-10-03T07:40:00[+-]\d{2}:\d{2}$/);
  });

  it("starts from a person when linked from their timeline", async () => {
    const { api } = routedApi({}, { [REPORTS]: stored() });
    renderApp(as(), "/incidents/inc_1/report?person=per_1&name=Maya%20Rawat", api);
    expect(await screen.findByText(/Report about/)).toHaveTextContent("Report about Maya Rawat");
  });

  it("warns that deceased reports are held for a reviewer", async () => {
    renderApp(as(), "/incidents/inc_1/report", routedApi({}).api);
    await userEvent.setup().selectOptions(await screen.findByLabelText("Report type"), "DECEASED");
    expect(screen.getByText(/held for a reviewer/)).toBeInTheDocument();
  });

  it("is only for publishers", async () => {
    renderApp(as(REVIEWER), "/incidents/inc_1/report", routedApi({}).api);
    expect(
      await screen.findByRole("heading", { name: "Not available for your role" }),
    ).toBeInTheDocument();
  });

  it("offers publishers a Report link once an incident is open", async () => {
    renderApp(as(), "/incidents/inc_1/report", routedApi({}).api);
    expect(await screen.findByRole("link", { name: "Report" })).toHaveAttribute(
      "href",
      "/incidents/inc_1/report",
    );
  });
});
