import { describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient } from "./client";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function setup(response: Response | Error, token: string | null = "tok") {
  const fetchImpl = vi.fn(async () => {
    if (response instanceof Error) throw response;
    return response;
  });
  const client = createApiClient({
    baseUrl: "https://api.example.org",
    idToken: async () => token,
    fetchImpl: fetchImpl as unknown as typeof fetch,
  });
  return { client, fetchImpl };
}

function sent(fetchImpl: ReturnType<typeof setup>["fetchImpl"]) {
  const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
  return { url, init, headers: init.headers as Record<string, string> };
}

describe("api client", () => {
  it("sends the bearer token and query, and parses JSON", async () => {
    const { client, fetchImpl } = setup(json(200, { people: [] }));
    const body = await client.get("/v1/people", { q: "maya", age: 24, cursor: undefined });
    expect(body).toEqual({ people: [] });
    const { url, headers } = sent(fetchImpl);
    expect(url).toBe("https://api.example.org/v1/people?q=maya&age=24");
    expect(headers.authorization).toBe("Bearer tok");
  });

  it("posts JSON bodies", async () => {
    const { client, fetchImpl } = setup(json(201, { ok: true }));
    await client.post("/v1/x", { a: 1 });
    const { init, headers } = sent(fetchImpl);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
    expect(headers["content-type"]).toBe("application/json");
  });

  it("omits the header when signed out", async () => {
    const { client, fetchImpl } = setup(json(200, {}), null);
    await client.get("/v1/health");
    expect(sent(fetchImpl).headers.authorization).toBeUndefined();
  });

  it("turns the error body into an ApiError", async () => {
    const { client } = setup(
      json(409, {
        error: {
          code: "REFERENCE_CONFLICT",
          message: "Exists.",
          details: { existing_claim_id: "clm_1" },
        },
        request_id: "req-1",
      }),
    );
    const err = await client.post("/v1/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 409,
      code: "REFERENCE_CONFLICT",
      message: "Exists.",
      details: { existing_claim_id: "clm_1" },
      requestId: "req-1",
    });
  });

  it("handles errors without our body", async () => {
    const { client } = setup(
      new Response("<html>", { status: 504, headers: { "x-request-id": "r9" } }),
    );
    await expect(client.get("/v1/x")).rejects.toMatchObject({
      status: 504,
      code: "INTERNAL",
      requestId: "r9",
    });
  });

  it("reports network failures plainly", async () => {
    const { client } = setup(new TypeError("Failed to fetch"));
    await expect(client.get("/v1/x")).rejects.toMatchObject({ status: 0, code: "NETWORK" });
  });

  it("accepts 204 on delete", async () => {
    const { client } = setup(new Response(null, { status: 204 }));
    await expect(client.del("/v1/subscriptions/sub_1")).resolves.toBeUndefined();
  });
});
