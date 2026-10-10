import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { FakeGateway, REVIEWER, renderApp, routedApi, type Query } from "../test/fakes";

const PATH = "/v1/incidents/inc_1/people";

function signedIn() {
  const gateway = new FakeGateway();
  gateway.user = REVIEWER;
  return gateway;
}

const MAYA = { id: "per_1", name: "Maya Rawat", age: 24 };
const MOHAN = { id: "per_2", name: "Mohan Rawat", age: null };
const RAVI = { id: "per_3", name: "Ravi Kumar", age: 30 };

afterEach(() => localStorage.clear());

describe("people page", () => {
  it("lists people with links and remembers the incident", async () => {
    const { api } = routedApi({ [PATH]: () => ({ people: [MAYA, MOHAN], next_cursor: null }) });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    const link = await screen.findByRole("link", { name: "Maya Rawat" });
    expect(link).toHaveAttribute("href", "/people/per_1");
    expect(screen.getByText("Not reported")).toBeInTheDocument();
    expect(localStorage.getItem("found.incidentId")).toBe("inc_1");
    expect(screen.getByRole("link", { name: "People" })).toBeInTheDocument();
  });

  it("searches by name and age through the URL", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) =>
        q.q ? { people: [MAYA], next_cursor: null } : { people: [MAYA, RAVI], next_cursor: null },
    });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    await screen.findByRole("link", { name: "Ravi Kumar" });
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "rawat");
    await user.type(screen.getByLabelText("Age"), "25");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText(/Ages match within 2 years/);
    expect(screen.queryByRole("link", { name: "Ravi Kumar" })).not.toBeInTheDocument();
    expect(calls.at(-1)?.query).toMatchObject({ q: "rawat", age: "25" });
  });

  it("loads more pages with the cursor", async () => {
    const { api, calls } = routedApi({
      [PATH]: (q: Query) =>
        q.cursor === "c2"
          ? { people: [RAVI], next_cursor: null }
          : { people: [MAYA, MOHAN], next_cursor: "c2" },
    });
    renderApp(signedIn(), "/incidents/inc_1/people", api);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
    const list = await screen.findByRole("table");
    await within(list).findByRole("link", { name: "Ravi Kumar" });
    expect(within(list).getAllByRole("row")).toHaveLength(4); // header and three people
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(calls.at(-1)?.query.cursor).toBe("c2");
  });

  it("says when nothing matches", async () => {
    const { api } = routedApi({ [PATH]: () => ({ people: [], next_cursor: null }) });
    renderApp(signedIn(), "/incidents/inc_1/people?q=zed", api);
    expect(await screen.findByText("No people match this search.")).toBeInTheDocument();
  });

  it("explains an unknown incident", async () => {
    const { api } = routedApi({});
    renderApp(signedIn(), "/incidents/inc_x/people", api);
    expect(await screen.findByRole("alert")).toHaveTextContent("This incident does not exist.");
  });

  it("opens an incident from the home page", async () => {
    const { api } = routedApi({
      "/v1/health": () => ({ status: "ok" }),
      [PATH]: () => ({ people: [MAYA], next_cursor: null }),
    });
    renderApp(signedIn(), "/", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Incident"), "inc_1");
    await user.click(screen.getByRole("button", { name: "Open people" }));
    expect(await screen.findByRole("link", { name: "Maya Rawat" })).toBeInTheDocument();
  });

  it("rejects an incident id that is not id-shaped", async () => {
    const { api } = routedApi({ "/v1/health": () => ({ status: "ok" }) });
    renderApp(signedIn(), "/", api);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Incident"), "../admin");
    await user.click(screen.getByRole("button", { name: "Open people" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an incident id");
  });
});
