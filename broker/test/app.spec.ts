import { describe, expect, it, vi } from "vitest";

import { createApp, type AppDependencies, type Env } from "../src/app";

const allowedOrigin = "https://frequencia-ufmg-eduardo.web.app";

function dependencies(
  overrides: Partial<AppDependencies> = {},
): AppDependencies {
  return {
    now: () => 100,
    requestId: () => "request-1",
    verifyAppCheck: vi.fn().mockResolvedValue({ appId: "web-app" }),
    verifyIdToken: vi.fn().mockResolvedValue({ uid: "user-1" }),
    ...overrides,
  };
}

function environment(overrides: Partial<Env> = {}): Env {
  return {
    ALLOWED_ORIGINS: allowedOrigin,
    AUTH_RATE_LIMITER: {
      limit: vi.fn().mockResolvedValue({ success: true }),
    },
    FIREBASE_PROJECT_ID: "project-id",
    FIREBASE_PROJECT_NUMBER: "123456789",
    TOKEN_VERIFICATION_TIMEOUT_MS: "5000",
    ...overrides,
  };
}

function request(
  path: string,
  init: RequestInit = {},
  origin: string | null = allowedOrigin,
): Request {
  const headers = new Headers(init.headers);
  if (origin !== null) headers.set("Origin", origin);
  return new Request(`https://broker.example${path}`, { ...init, headers });
}

async function json(response: Response): Promise<Record<string, unknown>> {
  return response.json() as Promise<Record<string, unknown>>;
}

describe("broker contract", () => {
  it("serves a public health response with exact CORS and security headers", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health"),
      environment(),
    );

    expect(response.status).toBe(200);
    expect(await json(response)).toEqual({
      data: { service: "ufmg-broker", status: "ok", version: "1" },
    });
    expect(response.headers.get("Access-Control-Allow-Origin")).toBe(
      allowedOrigin,
    );
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(response.headers.get("X-Request-Id")).toBe("request-1");
    expect(response.headers.get("Vary")).toBe("Origin");
  });

  it("allows native clients without an Origin header", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health", {}, null),
      environment(),
    );

    expect(response.status).toBe(200);
    expect(response.headers.has("Access-Control-Allow-Origin")).toBe(false);
  });

  it("answers an allowed preflight without authenticating", async () => {
    const deps = dependencies();
    const response = await createApp(deps).fetch(
      request("/v1/auth/verify", {
        method: "OPTIONS",
        headers: {
          "Access-Control-Request-Headers":
            "authorization,content-type,x-firebase-appcheck",
          "Access-Control-Request-Method": "POST",
        },
      }),
      environment(),
    );

    expect(response.status).toBe(204);
    expect(response.headers.get("Access-Control-Allow-Methods")).toBe(
      "GET,POST,OPTIONS",
    );
    expect(response.headers.get("Access-Control-Allow-Headers")).toBe(
      "Authorization,Content-Type,X-Firebase-AppCheck",
    );
    expect(response.headers.get("Access-Control-Max-Age")).toBe("600");
    expect(deps.verifyIdToken).not.toHaveBeenCalled();
  });

  it("blocks unapproved browser origins without reflecting them", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health", {}, "https://evil.example"),
      environment(),
    );

    expect(response.status).toBe(403);
    expect(response.headers.has("Access-Control-Allow-Origin")).toBe(false);
    expect(await json(response)).toEqual({
      error: {
        code: "ORIGIN_NOT_ALLOWED",
        message: "Origem não permitida.",
        requestId: "request-1",
      },
    });
  });

  it("rejects unsafe origin configuration", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health"),
      environment({ ALLOWED_ORIGINS: "*" }),
    );

    expect(response.status).toBe(500);
    expect((await json(response)).error).toMatchObject({
      code: "CONFIGURATION_ERROR",
    });
  });

  it.each([
    ["empty", ""],
    ["insecure", "http://example.com"],
    ["with path", "https://example.com/path"],
    ["malformed", "not-a-url"],
  ])("rejects %s allowed-origin configuration", async (_name, configured) => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health"),
      environment({ ALLOWED_ORIGINS: configured }),
    );

    expect(response.status).toBe(500);
    expect((await json(response)).error).toMatchObject({
      code: "CONFIGURATION_ERROR",
    });
  });

  it("returns a stable not-found contract", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/missing"),
      environment(),
    );

    expect(response.status).toBe(404);
    expect((await json(response)).error).toMatchObject({ code: "NOT_FOUND" });
  });

  it("rejects unsupported methods", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/health", { method: "POST" }),
      environment(),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("GET");
    expect((await json(response)).error).toMatchObject({
      code: "METHOD_NOT_ALLOWED",
    });
  });

  it("rejects unsupported methods on the protected route", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify"),
      environment(),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get("Allow")).toBe("POST");
  });

  it("requires a Firebase bearer token", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", { method: "POST" }),
      environment(),
    );

    expect(response.status).toBe(401);
    expect((await json(response)).error).toMatchObject({
      code: "AUTH_REQUIRED",
    });
  });

  it("requires an App Check token", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: { Authorization: "Bearer id-token" },
      }),
      environment(),
    );

    expect(response.status).toBe(401);
    expect((await json(response)).error).toMatchObject({
      code: "APP_CHECK_REQUIRED",
    });
  });

  it("verifies both tokens and rate limits by verified uid", async () => {
    const deps = dependencies();
    const env = environment();
    const response = await createApp(deps).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      env,
    );

    expect(response.status).toBe(200);
    expect(await json(response)).toEqual({ data: { authenticated: true } });
    expect(deps.verifyIdToken).toHaveBeenCalledWith("id-token", env);
    expect(deps.verifyAppCheck).toHaveBeenCalledWith("app-check-token", env);
    expect(env.AUTH_RATE_LIMITER.limit).toHaveBeenCalledWith({
      key: "user-1:auth-verify",
    });
  });

  it("maps invalid ID and App Check tokens to generic errors", async () => {
    const idResponse = await createApp(
      dependencies({
        verifyIdToken: vi.fn().mockRejectedValue(new Error("secret id-token")),
      }),
    ).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer bad-id",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment(),
    );
    const appResponse = await createApp(
      dependencies({
        verifyAppCheck: vi
          .fn()
          .mockRejectedValue(new Error("secret app-token")),
      }),
    ).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "bad-app",
        },
      }),
      environment(),
    );

    expect(idResponse.status).toBe(401);
    expect((await json(idResponse)).error).toMatchObject({
      code: "AUTH_INVALID",
    });
    expect(appResponse.status).toBe(401);
    expect((await json(appResponse)).error).toMatchObject({
      code: "APP_CHECK_INVALID",
    });
  });

  it("returns 429 when the shared limiter rejects the verified user", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment({
        AUTH_RATE_LIMITER: {
          limit: vi.fn().mockResolvedValue({ success: false }),
        },
      }),
    );

    expect(response.status).toBe(429);
    expect(response.headers.get("Retry-After")).toBe("60");
    expect((await json(response)).error).toMatchObject({
      code: "RATE_LIMITED",
    });
  });

  it("rejects oversized request bodies before token verification", async () => {
    const deps = dependencies();
    const response = await createApp(deps).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "Content-Length": "16385",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment(),
    );

    expect(response.status).toBe(413);
    expect((await json(response)).error).toMatchObject({
      code: "PAYLOAD_TOO_LARGE",
    });
    expect(deps.verifyIdToken).not.toHaveBeenCalled();
  });

  it("measures a body when content length is unavailable", async () => {
    const headers = {
      Authorization: "Bearer id-token",
      "X-Firebase-AppCheck": "app-check-token",
    };
    const smallResponse = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        body: "small",
        headers,
        method: "POST",
      }),
      environment(),
    );
    const largeResponse = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        body: "x".repeat(16_385),
        headers,
        method: "POST",
      }),
      environment(),
    );

    expect(smallResponse.status).toBe(200);
    expect(largeResponse.status).toBe(413);
  });

  it.each(["invalid", "-1"])(
    "rejects invalid declared content length %s",
    async (declaredLength) => {
      const response = await createApp(dependencies()).fetch(
        request("/v1/auth/verify", {
          method: "POST",
          headers: {
            Authorization: "Bearer id-token",
            "Content-Length": declaredLength,
            "X-Firebase-AppCheck": "app-check-token",
          },
        }),
        environment(),
      );

      expect(response.status).toBe(400);
      expect((await json(response)).error).toMatchObject({
        code: "INVALID_CONTENT_LENGTH",
      });
    },
  );

  it("accepts a valid declared content length within the limit", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        body: "small",
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "Content-Length": "5",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment(),
    );

    expect(response.status).toBe(200);
  });

  it.each(["invalid", "99", "10001"])(
    "fails closed for invalid timeout %s",
    async (configured) => {
      const response = await createApp(dependencies()).fetch(
        request("/v1/auth/verify", {
          method: "POST",
          headers: {
            Authorization: "Bearer id-token",
            "X-Firebase-AppCheck": "app-check-token",
          },
        }),
        environment({ TOKEN_VERIFICATION_TIMEOUT_MS: configured }),
      );

      expect(response.status).toBe(500);
      expect((await json(response)).error).toMatchObject({
        code: "CONFIGURATION_ERROR",
      });
    },
  );

  it("times out token verification and fails closed", async () => {
    vi.useFakeTimers();
    const never = new Promise<never>(() => undefined);
    const responsePromise = createApp(
      dependencies({ verifyIdToken: vi.fn(() => never) }),
    ).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment({ TOKEN_VERIFICATION_TIMEOUT_MS: "100" }),
    );
    await vi.advanceTimersByTimeAsync(100);
    const response = await responsePromise;
    vi.useRealTimers();

    expect(response.status).toBe(503);
    expect((await json(response)).error).toMatchObject({
      code: "UPSTREAM_TIMEOUT",
    });
  });

  it("also times out App Check verification", async () => {
    vi.useFakeTimers();
    const responsePromise = createApp(
      dependencies({
        verifyAppCheck: vi.fn(() => new Promise<never>(() => undefined)),
      }),
    ).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment({ TOKEN_VERIFICATION_TIMEOUT_MS: "100" }),
    );
    await vi.advanceTimersByTimeAsync(100);
    const response = await responsePromise;
    vi.useRealTimers();

    expect(response.status).toBe(503);
    expect((await json(response)).error).toMatchObject({
      code: "UPSTREAM_TIMEOUT",
    });
  });

  it("hides unexpected infrastructure errors", async () => {
    const response = await createApp(dependencies()).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer id-token",
          "X-Firebase-AppCheck": "app-check-token",
        },
      }),
      environment({
        AUTH_RATE_LIMITER: {
          limit: vi.fn().mockRejectedValue(new Error("private failure")),
        },
      }),
    );

    expect(response.status).toBe(500);
    expect(await response.text()).not.toContain("private failure");
  });

  it("logs only the sanitized operational envelope", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    await createApp(
      dependencies({
        verifyIdToken: vi.fn().mockRejectedValue(new Error("secret-token")),
      }),
    ).fetch(
      request("/v1/auth/verify", {
        method: "POST",
        headers: {
          Authorization: "Bearer secret-token",
          "X-Firebase-AppCheck": "secret-app-check",
        },
      }),
      environment(),
    );

    expect(info).toHaveBeenCalledOnce();
    const serialized = JSON.stringify(info.mock.calls[0]?.[0]);
    expect(serialized).not.toContain("secret-token");
    expect(serialized).not.toContain("secret-app-check");
    expect(info.mock.calls[0]?.[0]).toEqual({
      durationMs: 0,
      errorCode: "AUTH_INVALID",
      event: "broker_request",
      method: "POST",
      path: "/v1/auth/verify",
      requestId: "request-1",
      status: 401,
    });
    info.mockRestore();
  });
});
