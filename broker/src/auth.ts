import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from "jose";

const firebaseAuthKeys = createRemoteJWKSet(
  new URL(
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
  ),
);
const appCheckKeys = createRemoteJWKSet(
  new URL("https://firebaseappcheck.googleapis.com/v1/jwks"),
);

export interface FirebaseEnvironment {
  FIREBASE_PROJECT_ID: string;
  FIREBASE_PROJECT_NUMBER: string;
}

export interface FirebaseIdentity {
  uid: string;
}

export interface FirebaseAppIdentity {
  appId: string;
}

export function extractBearerToken(value: string | null): string | null {
  const match = value?.match(/^Bearer ([^\s]+)$/);
  return match?.[1] ?? null;
}

export async function verifyFirebaseIdToken(
  token: string,
  env: FirebaseEnvironment,
  keyResolver: JWTVerifyGetKey = firebaseAuthKeys,
): Promise<FirebaseIdentity> {
  const { payload } = await jwtVerify(token, keyResolver, {
    algorithms: ["RS256"],
    audience: env.FIREBASE_PROJECT_ID,
    issuer: `https://securetoken.google.com/${env.FIREBASE_PROJECT_ID}`,
  });
  const now = Math.floor(Date.now() / 1000);
  if (
    typeof payload.sub !== "string" ||
    payload.sub.length === 0 ||
    typeof payload.iat !== "number" ||
    payload.iat > now ||
    typeof payload.auth_time !== "number" ||
    payload.auth_time > now
  ) {
    throw new Error("Invalid Firebase ID token claims");
  }
  return { uid: payload.sub };
}

export async function verifyFirebaseAppCheck(
  token: string,
  env: FirebaseEnvironment,
  keyResolver: JWTVerifyGetKey = appCheckKeys,
): Promise<FirebaseAppIdentity> {
  const { payload, protectedHeader } = await jwtVerify(token, keyResolver, {
    algorithms: ["RS256"],
    audience: `projects/${env.FIREBASE_PROJECT_NUMBER}`,
    issuer: `https://firebaseappcheck.googleapis.com/${env.FIREBASE_PROJECT_NUMBER}`,
  });
  if (
    protectedHeader.typ !== "JWT" ||
    typeof payload.sub !== "string" ||
    payload.sub.length === 0
  ) {
    throw new Error("Invalid App Check token claims");
  }
  return { appId: payload.sub };
}
