import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FakeGateway, REVIEWER, renderApp } from "./test/fakes";
import { initialTheme, savedTheme } from "./theme";

function systemPrefers(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        matches: dark && query.includes("dark"),
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete document.documentElement.dataset.theme;
});

describe("theme", () => {
  it("uses a saved choice, else the system setting", () => {
    systemPrefers(true);
    expect(initialTheme()).toBe("dark");
    localStorage.setItem("found-theme", "light");
    expect(initialTheme()).toBe("light");
    localStorage.setItem("found-theme", "sepia");
    expect(savedTheme()).toBeNull();
  });

  it("treats blocked storage as no choice", () => {
    systemPrefers(false);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(savedTheme()).toBeNull();
    expect(initialTheme()).toBe("light");
  });

  it("toggles from the header and remembers the choice", async () => {
    systemPrefers(false);
    const gateway = new FakeGateway();
    gateway.user = REVIEWER;
    renderApp(gateway, "/alerts");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("found-theme")).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("found-theme")).toBe("light");
  });
});
