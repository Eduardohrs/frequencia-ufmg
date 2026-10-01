import {
  exportJWK,
  generateKeyPair,
  importJWK,
  SignJWT,
  type JWTHeaderParameters,
  type JWTVerifyGetKey,
} from "jose";
import { beforeAll, describe, expect, it } from "vitest";

import {
  extractBearerToken,
  verifyFirebaseAppCheck,
  verifyFirebaseIdToken,
} from "../src/auth";

const projectId = "project-id";
const projectNumber = "123456789";
let privateKey: CryptoKey;
let keyResolver: JWTVerifyGetKey;

beforeAll(async () => {
  const pair = await generateKeyPair("RS256", { extractable: true });
  privateKey = pair.privateKey;
  const jwk = await exportJWK(pair.publicKey);
  const publicKey = await importJWK({ ...jwk, alg: "RS256", kid: "test-key" });
  keyResolver = async (protectedHeader) => {
    if (protectedHeader.kid !== "test-key") throw new Error("unknown key");
    return publicKey;
  };
});

async function token(
  claims: Record<string, unknown>,
  header: JWTHeaderParameters = {
    alg: "RS256",
    kid: "test-key",
    typ: "JWT",
  },
): Promise<string> {
  return new SignJWT(claims).setProtectedHeader(header).sign(privateKey);
}

const env = {
  FIREBASE_PROJECT_ID: projectId,
  FIREBASE_PROJECT_NUMBER: projectNumber,
};

describe("Firebase token verification", () => {
  it("extracts only a strict bearer credential", () => {
    expect(extractBearerToken("Bearer abc.def")).toBe("abc.def");
    expect(extractBearerToken(null)).toBeNull();
    expect(extractBearerToken("Basic abc")).toBeNull();
    expect(extractBearerToken("Bearer ")).toBeNull();
    expect(extractBearerToken("bearer abc")).toBeNull();
  });

  it("verifies a Firebase ID token and returns only the uid", async () => {
    const now = Math.floor(Date.now() / 1000);
    const signed = await token({
      aud: projectId,
      auth_time: now - 10,
      exp: now + 300,
      iat: now - 10,
      iss: `https://securetoken.google.com/${projectId}`,
      sub: "user-1",
    });

    await expect(
      verifyFirebaseIdToken(signed, env, keyResolver),
    ).resolves.toEqual({ uid: "user-1" });
  });

  it.each([
    ["empty subject", { sub: "" }],
    ["future issued-at", { iat: Math.floor(Date.now() / 1000) + 120 }],
    [
      "future authentication",
      { auth_time: Math.floor(Date.now() / 1000) + 120 },
    ],
  ])("rejects ID token with %s", async (_name, override) => {
    const now = Math.floor(Date.now() / 1000);
    const signed = await token({
      aud: projectId,
      auth_time: now - 10,
      exp: now + 300,
      iat: now - 10,
      iss: `https://securetoken.google.com/${projectId}`,
      sub: "user-1",
      ...override,
    });

    await expect(
      verifyFirebaseIdToken(signed, env, keyResolver),
    ).rejects.toThrow("Invalid Firebase ID token claims");
  });

  it("cryptographically rejects an ID token for another Firebase project", async () => {
    const now = Math.floor(Date.now() / 1000);
    const signed = await token({
      aud: "other-project",
      auth_time: now - 10,
      exp: now + 300,
      iat: now - 10,
      iss: `https://securetoken.google.com/${projectId}`,
      sub: "user-1",
    });

    await expect(
      verifyFirebaseIdToken(signed, env, keyResolver),
    ).rejects.toThrow();
  });

  it("verifies App Check issuer, audience, JWT type and app id", async () => {
    const now = Math.floor(Date.now() / 1000);
    const signed = await token({
      aud: [`projects/${projectNumber}`],
      exp: now + 300,
      iat: now - 10,
      iss: `https://firebaseappcheck.googleapis.com/${projectNumber}`,
      sub: "1:123:web:abc",
    });

    await expect(
      verifyFirebaseAppCheck(signed, env, keyResolver),
    ).resolves.toEqual({ appId: "1:123:web:abc" });
  });

  it("rejects App Check tokens without a subject or JWT type", async () => {
    const now = Math.floor(Date.now() / 1000);
    const claims = {
      aud: [`projects/${projectNumber}`],
      exp: now + 300,
      iat: now - 10,
      iss: `https://firebaseappcheck.googleapis.com/${projectNumber}`,
      sub: "",
    };
    const emptySubject = await token(claims);
    const wrongType = await token(
      { ...claims, sub: "app-id" },
      { alg: "RS256", kid: "test-key", typ: "NOT-JWT" },
    );

    await expect(
      verifyFirebaseAppCheck(emptySubject, env, keyResolver),
    ).rejects.toThrow("Invalid App Check token claims");
    await expect(
      verifyFirebaseAppCheck(wrongType, env, keyResolver),
    ).rejects.toThrow();
  });

  it("cryptographically rejects App Check from another project", async () => {
    const now = Math.floor(Date.now() / 1000);
    const signed = await token({
      aud: ["projects/999999999"],
      exp: now + 300,
      iat: now - 10,
      iss: `https://firebaseappcheck.googleapis.com/${projectNumber}`,
      sub: "app-id",
    });

    await expect(
      verifyFirebaseAppCheck(signed, env, keyResolver),
    ).rejects.toThrow();
  });
});
