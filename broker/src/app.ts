import {
  extractBearerToken,
  type FirebaseAppIdentity,
  type FirebaseEnvironment,
  type FirebaseIdentity,
} from "./auth";

const MAX_BODY_BYTES = 16_384;
const corsHeaders = {
  "Access-Control-Allow-Headers":
    "Authorization,Content-Type,X-Firebase-AppCheck",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Max-Age": "600",
};

interface RateLimiter {
  limit(options: { key: string }): Promise<{ success: boolean }>;
}

export interface Env extends FirebaseEnvironment {
  ALLOWED_ORIGINS: string;
  AUTH_RATE_LIMITER: RateLimiter;
  TOKEN_VERIFICATION_TIMEOUT_MS: string;
}

export interface AppDependencies {
  now: () => number;
  requestId: () => string;
  verifyAppCheck: (
    token: string,
    env: FirebaseEnvironment,
  ) => Promise<FirebaseAppIdentity>;
  verifyIdToken: (
    token: string,
    env: FirebaseEnvironment,
  ) => Promise<FirebaseIdentity>;
}

interface ErrorBody {
  error: {
    code: string;
    message: string;
    requestId: string;
  };
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly headers: Record<string, string> = {},
  ) {
    super(message);
  }
}

function json(body: object, status = 200): Response {
  return Response.json(body, {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function parseAllowedOrigins(value: string): Set<string> {
  const origins = value
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  if (origins.length === 0 || origins.includes("*")) {
    throw new HttpError(500, "CONFIGURATION_ERROR", "Configuração inválida.");
  }
  for (const origin of origins) {
    let parsed: URL;
    try {
      parsed = new URL(origin);
    } catch {
      throw new HttpError(500, "CONFIGURATION_ERROR", "Configuração inválida.");
    }
    const local = parsed.hostname === "localhost";
    if (parsed.origin !== origin || (parsed.protocol !== "https:" && !local)) {
      throw new HttpError(500, "CONFIGURATION_ERROR", "Configuração inválida.");
    }
  }
  return new Set(origins);
}

function parseTimeout(value: string): number {
  const timeout = Number(value);
  if (!Number.isInteger(timeout) || timeout < 100 || timeout > 10_000) {
    throw new HttpError(500, "CONFIGURATION_ERROR", "Configuração inválida.");
  }
  return timeout;
}

async function withTimeout<T>(
  promise: Promise<T>,
  milliseconds: number,
): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(
      () =>
        reject(new HttpError(503, "UPSTREAM_TIMEOUT", "Serviço indisponível.")),
      milliseconds,
    );
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

async function assertBodyWithinLimit(request: Request): Promise<void> {
  const contentLength = request.headers.get("Content-Length");
  if (contentLength !== null) {
    const declaredLength = Number(contentLength);
    if (!Number.isSafeInteger(declaredLength) || declaredLength < 0) {
      throw new HttpError(
        400,
        "INVALID_CONTENT_LENGTH",
        "Requisição inválida.",
      );
    }
    if (declaredLength > MAX_BODY_BYTES) {
      throw new HttpError(413, "PAYLOAD_TOO_LARGE", "Conteúdo muito grande.");
    }
  }
  if (request.body !== null) {
    const body = await request.clone().arrayBuffer();
    if (body.byteLength > MAX_BODY_BYTES) {
      throw new HttpError(413, "PAYLOAD_TOO_LARGE", "Conteúdo muito grande.");
    }
  }
}

async function verifyRequest(
  request: Request,
  env: Env,
  dependencies: AppDependencies,
): Promise<FirebaseIdentity> {
  const idToken = extractBearerToken(request.headers.get("Authorization"));
  if (idToken === null) {
    throw new HttpError(401, "AUTH_REQUIRED", "Autenticação necessária.");
  }
  const appCheckToken = request.headers.get("X-Firebase-AppCheck");
  if (!appCheckToken) {
    throw new HttpError(401, "APP_CHECK_REQUIRED", "App Check necessário.");
  }
  const timeout = parseTimeout(env.TOKEN_VERIFICATION_TIMEOUT_MS);
  let identity: FirebaseIdentity;
  try {
    identity = await withTimeout(
      dependencies.verifyIdToken(idToken, env),
      timeout,
    );
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(401, "AUTH_INVALID", "Autenticação inválida.");
  }
  try {
    await withTimeout(dependencies.verifyAppCheck(appCheckToken, env), timeout);
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(401, "APP_CHECK_INVALID", "App Check inválido.");
  }
  return identity;
}

function errorResponse(error: unknown, requestId: string): Response {
  const safeError =
    error instanceof HttpError
      ? error
      : new HttpError(500, "INTERNAL_ERROR", "Erro interno.");
  const body: ErrorBody = {
    error: {
      code: safeError.code,
      message: safeError.message,
      requestId,
    },
  };
  const response = json(body, safeError.status);
  for (const [name, value] of Object.entries(safeError.headers)) {
    response.headers.set(name, value);
  }
  return response;
}

function finishResponse(
  response: Response,
  origin: string | null,
  allowedOrigins: Set<string> | null,
  requestId: string,
): Response {
  response.headers.set("Cache-Control", "no-store");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Request-Id", requestId);
  response.headers.set("Vary", "Origin");
  if (origin !== null && allowedOrigins?.has(origin)) {
    response.headers.set("Access-Control-Allow-Origin", origin);
  }
  return response;
}

async function route(
  request: Request,
  env: Env,
  dependencies: AppDependencies,
): Promise<Response> {
  const url = new URL(request.url);
  if (request.method === "OPTIONS") {
    const response = new Response(null, { status: 204 });
    for (const [name, value] of Object.entries(corsHeaders)) {
      response.headers.set(name, value);
    }
    return response;
  }
  if (url.pathname === "/v1/health") {
    if (request.method !== "GET") {
      throw new HttpError(405, "METHOD_NOT_ALLOWED", "Método não permitido.", {
        Allow: "GET",
      });
    }
    return json({
      data: { service: "ufmg-broker", status: "ok", version: "1" },
    });
  }
  if (url.pathname === "/v1/auth/verify") {
    if (request.method !== "POST") {
      throw new HttpError(405, "METHOD_NOT_ALLOWED", "Método não permitido.", {
        Allow: "POST",
      });
    }
    await assertBodyWithinLimit(request);
    const identity = await verifyRequest(request, env, dependencies);
    const { success } = await env.AUTH_RATE_LIMITER.limit({
      key: `${identity.uid}:auth-verify`,
    });
    if (!success) {
      throw new HttpError(429, "RATE_LIMITED", "Muitas tentativas.", {
        "Retry-After": "60",
      });
    }
    return json({ data: { authenticated: true } });
  }
  throw new HttpError(404, "NOT_FOUND", "Rota não encontrada.");
}

export function createApp(dependencies: AppDependencies) {
  return {
    async fetch(request: Request, env: Env): Promise<Response> {
      const requestId = dependencies.requestId();
      const startedAt = dependencies.now();
      const origin = request.headers.get("Origin");
      let allowedOrigins: Set<string> | null = null;
      let response: Response;
      let errorCode: string | undefined;
      try {
        allowedOrigins = parseAllowedOrigins(env.ALLOWED_ORIGINS);
        if (origin !== null && !allowedOrigins.has(origin)) {
          throw new HttpError(
            403,
            "ORIGIN_NOT_ALLOWED",
            "Origem não permitida.",
          );
        }
        response = await route(request, env, dependencies);
      } catch (error) {
        response = errorResponse(error, requestId);
        errorCode = (await response.clone().json<ErrorBody>()).error.code;
      }
      const path = new URL(request.url).pathname;
      console.info({
        durationMs: Math.max(0, dependencies.now() - startedAt),
        ...(errorCode === undefined ? {} : { errorCode }),
        event: "broker_request",
        method: request.method,
        path,
        requestId,
        status: response.status,
      });
      return finishResponse(response, origin, allowedOrigins, requestId);
    },
  };
}
