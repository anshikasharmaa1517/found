import { describe, expect, it } from "vitest";

import { readConfig } from "./config";

const FULL = {
  VITE_REGION: "ap-south-1",
  VITE_USER_POOL_ID: "ap-south-1_abc",
  VITE_USER_POOL_CLIENT_ID: "client",
  VITE_API_URL: "https://api.example.org/",
  VITE_WS_URL: "wss://ws.example.org/prod",
};

describe("readConfig", () => {
  it("reads every setting and trims the trailing slash of the API URL", () => {
    expect(readConfig(FULL)).toEqual({
      ok: true,
      config: {
        region: "ap-south-1",
        userPoolId: "ap-south-1_abc",
        userPoolClientId: "client",
        apiUrl: "https://api.example.org",
        wsUrl: "wss://ws.example.org/prod",
        defaultIncidentId: undefined,
        mapApiKey: undefined,
      },
    });
  });

  it("reads the optional default incident", () => {
    const result = readConfig({ ...FULL, VITE_DEFAULT_INCIDENT_ID: " inc_demo " });
    expect(result.ok && result.config.defaultIncidentId).toBe("inc_demo");
  });

  it("reads the optional map key", () => {
    const result = readConfig({ ...FULL, VITE_MAP_API_KEY: "v1.public.abc" });
    expect(result.ok && result.config.mapApiKey).toBe("v1.public.abc");
  });

  it("lists every missing or blank setting", () => {
    expect(readConfig({ ...FULL, VITE_API_URL: " ", VITE_WS_URL: undefined })).toEqual({
      ok: false,
      missing: ["VITE_API_URL", "VITE_WS_URL"],
    });
  });
});
