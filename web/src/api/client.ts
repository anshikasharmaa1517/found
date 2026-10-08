/** Typed HTTP client for the Found API (design Section 7.1). */

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}

export interface ApiClient {
  get<T>(path: string, query?: Record<string, string | number | undefined>): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  del(path: string): Promise<void>;
}

export interface ApiClientOptions {
  baseUrl: string;
  idToken: () => Promise<string | null>;
  fetchImpl?: typeof fetch;
}

function withQuery(path: string, query?: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

async function errorFrom(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("x-request-id");
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; details?: Record<string, unknown> };
      request_id?: string;
    };
    if (body.error?.code) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message || "Request failed.",
        body.error.details ?? {},
        body.request_id ?? requestId,
      );
    }
  } catch {
    // Not our error body, for example a gateway timeout page.
  }
  const code = response.status === 401 ? "UNAUTHENTICATED" : "INTERNAL";
  return new ApiError(response.status, code, "Something went wrong.", {}, requestId);
}

export function createApiClient({ baseUrl, idToken, fetchImpl }: ApiClientOptions): ApiClient {
  const send = fetchImpl ?? ((input, init) => fetch(input, init));

  async function request(method: string, path: string, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = { accept: "application/json" };
    const token = await idToken();
    if (token) headers.authorization = `Bearer ${token}`;
    if (body !== undefined) headers["content-type"] = "application/json";
    let response: Response;
    try {
      response = await send(`${baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "NETWORK", "Cannot reach the server. Check your connection.");
    }
    if (!response.ok) throw await errorFrom(response);
    return response;
  }

  return {
    async get<T>(path: string, query?: Record<string, string | number | undefined>) {
      return (await (await request("GET", withQuery(path, query))).json()) as T;
    },
    async post<T>(path: string, body: unknown = {}) {
      return (await (await request("POST", path, body)).json()) as T;
    },
    async del(path: string) {
      await request("DELETE", path);
    },
  };
}
