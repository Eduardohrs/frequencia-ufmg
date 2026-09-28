import { readFile } from "node:fs/promises";
import { after, afterEach, before, describe, test } from "node:test";

import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from "@firebase/rules-unit-testing";
import {
  Timestamp,
  deleteDoc,
  doc,
  getDoc,
  getDocs,
  collection,
  setDoc,
  serverTimestamp,
  updateDoc,
} from "firebase/firestore";

const projectId = "demo-frequencia-ufmg";
let testEnv;

before(async () => {
  testEnv = await initializeTestEnvironment({
    projectId,
    firestore: {
      host: "127.0.0.1",
      port: 8080,
      rules: await readFile(new URL("../firestore.rules", import.meta.url), "utf8"),
    },
  });
});

afterEach(async () => testEnv.clearFirestore());
after(async () => testEnv.cleanup());

const dbFor = (userId) => testEnv.authenticatedContext(userId).firestore();
const anonymousDb = () => testEnv.unauthenticatedContext().firestore();
const coursePath = (userId, courseId = "dcc203") =>
  `users/${userId}/courses/${courseId}`;
const meetingPath = (userId, meetingId = "monday-0800") =>
  `${coursePath(userId)}/meetings/${meetingId}`;
const sessionPath = (userId, sessionId = "2026-08-03") =>
  `${coursePath(userId)}/sessions/${sessionId}`;
const logPath = (userId, logId = "log-1") =>
  `users/${userId}/logs/${logId}`;

const createdAt = Timestamp.fromDate(new Date("2026-07-01T12:00:00Z"));
const updatedAt = Timestamp.fromDate(new Date("2026-07-02T12:00:00Z"));

const course = (overrides = {}) => ({
  schemaVersion: 1,
  code: "DCC203",
  name: "Programação Orientada a Objetos",
  workload: 60,
  term: "2026-2",
  startsOn: null,
  endsOn: null,
  createdAt,
  updatedAt,
  ...overrides,
});

const meeting = (overrides = {}) => ({
  schemaVersion: 1,
  weekday: 1,
  startMinutes: 480,
  endMinutes: 580,
  lessonCount: 2,
  callCount: 1,
  createdAt,
  updatedAt,
  ...overrides,
});

const session = (overrides = {}) => ({
  schemaVersion: 1,
  startsAt: Timestamp.fromDate(new Date("2026-08-03T11:00:00Z")),
  endsAt: Timestamp.fromDate(new Date("2026-08-03T13:00:00Z")),
  lessonCount: 2,
  callCount: 1,
  firstPing: null,
  secondPing: null,
  attendanceStatus: null,
  absences: null,
  calendarStatus: "scheduled",
  createdAt,
  updatedAt,
  ...overrides,
});

const operationalLog = (overrides = {}) => ({
  schemaVersion: 1,
  occurredAt: serverTimestamp(),
  expiresAt: Timestamp.fromDate(new Date(Date.now() + 30 * 24 * 60 * 60 * 1000)),
  level: "error",
  event: "app_exception",
  entryPoint: "client",
  platform: "web",
  correlationId: "operation-42",
  operation: "firestore_course_save",
  outcome: "failed",
  durationMs: 125,
  errorType: "FirebaseException",
  errorCode: "permission-denied",
  errorMessage: "The caller does not have permission.",
  errorDetails: null,
  fatal: false,
  ...overrides,
});

function withoutField(data, field) {
  const copy = { ...data };
  delete copy[field];
  return copy;
}

async function seed(path, data) {
  await testEnv.withSecurityRulesDisabled(async (context) => {
    await setDoc(doc(context.firestore(), path), data);
  });
}

describe("tenant isolation", () => {
  test("owner can create, read, list, update, and delete a course", async () => {
    const db = dbFor("alice");
    const reference = doc(db, coursePath("alice"));

    await assertSucceeds(setDoc(reference, course()));
    await assertSucceeds(getDoc(reference));
    await assertSucceeds(getDocs(collection(db, "users/alice/courses")));
    await assertSucceeds(updateDoc(reference, { name: "POO" }));
    await assertSucceeds(deleteDoc(reference));
  });

  test("anonymous and other users cannot access a tenant", async () => {
    await seed(coursePath("alice"), course());

    await assertFails(getDoc(doc(anonymousDb(), coursePath("alice"))));
    await assertFails(setDoc(doc(anonymousDb(), coursePath("alice")), course()));
    await assertFails(getDoc(doc(dbFor("bob"), coursePath("alice"))));
    await assertFails(setDoc(doc(dbFor("bob"), coursePath("alice")), course()));
  });

  test("applies tenant isolation to meetings and sessions", async () => {
    await seed(coursePath("alice"), course());
    await seed(meetingPath("alice"), meeting());
    await seed(sessionPath("alice"), session());
    const alice = dbFor("alice");
    const bob = dbFor("bob");

    await assertSucceeds(getDoc(doc(alice, meetingPath("alice"))));
    await assertSucceeds(updateDoc(doc(alice, meetingPath("alice")), { endMinutes: 600 }));
    await assertSucceeds(getDoc(doc(alice, sessionPath("alice"))));
    await assertFails(getDoc(doc(bob, meetingPath("alice"))));
    await assertFails(updateDoc(doc(bob, sessionPath("alice")), { absences: 1 }));
    await assertSucceeds(deleteDoc(doc(alice, sessionPath("alice"))));
  });

  test("unknown documents stay denied even for their tenant", async () => {
    const db = dbFor("alice");

    await assertFails(setDoc(doc(db, "users/alice"), { schemaVersion: 1 }));
    await assertFails(
      setDoc(doc(db, "users/alice/private/anything"), { schemaVersion: 1 }),
    );
  });
});

describe("course documents", () => {
  test("reject malformed shapes, values, and audit timestamps", async () => {
    const db = dbFor("alice");
    const invalidDocuments = [
      course({ schemaVersion: 2 }),
      course({ code: "" }),
      course({ code: " DCC203" }),
      course({ code: "x".repeat(33) }),
      course({ name: "POO " }),
      course({ name: "x".repeat(161) }),
      course({ workload: 0 }),
      course({ term: "2026/2" }),
      course({ startsOn: createdAt, endsOn: null }),
      course({ startsOn: updatedAt, endsOn: createdAt }),
      course({ createdAt: updatedAt, updatedAt: createdAt }),
      withoutField(course(), "name"),
      { ...course(), ownerId: "alice" },
      { ...course(), workload: "60" },
    ];

    for (const [index, data] of invalidDocuments.entries()) {
      await assertFails(setDoc(doc(db, coursePath("alice", `invalid-${index}`)), data));
    }
  });

  test("accepts a complete date range and the legacy shape", async () => {
    const db = dbFor("alice");
    await assertSucceeds(
      setDoc(
        doc(db, coursePath("alice", "dated")),
        course({ startsOn: createdAt, endsOn: updatedAt }),
      ),
    );
    const legacy = withoutField(withoutField(course(), "startsOn"), "endsOn");
    await assertSucceeds(setDoc(doc(db, coursePath("alice", "legacy")), legacy));
  });

  test("preserves creation time and prevents audit time rollback", async () => {
    await seed(coursePath("alice"), course());
    const reference = doc(dbFor("alice"), coursePath("alice"));

    await assertFails(updateDoc(reference, { createdAt: updatedAt }));
    await assertFails(updateDoc(reference, { updatedAt: createdAt }));
    await assertFails(updateDoc(reference, { ownerId: "alice" }));
  });
});

describe("operational logs", () => {
  test("owner can create and read an immutable structured log", async () => {
    const path = logPath("alice");
    const reference = doc(dbFor("alice"), path);

    await assertSucceeds(setDoc(reference, operationalLog()));
    await assertSucceeds(getDoc(reference));
    await assertFails(updateDoc(reference, { outcome: "succeeded" }));
    await assertFails(deleteDoc(reference));
  });

  test("owner can delete only an expired log", async () => {
    const expiredPath = logPath("alice", "expired");
    const expiredAt = Timestamp.fromDate(new Date(Date.now() - 60 * 1000));
    const oldOccurredAt = Timestamp.fromDate(new Date(Date.now() - 31 * 24 * 60 * 60 * 1000));
    await seed(
      expiredPath,
      operationalLog({ occurredAt: oldOccurredAt, expiresAt: expiredAt }),
    );

    await assertSucceeds(deleteDoc(doc(dbFor("alice"), expiredPath)));
  });

  test("anonymous and other users cannot access a user's logs", async () => {
    const path = logPath("alice");
    await seed(path, operationalLog({ occurredAt: updatedAt }));

    await assertFails(getDoc(doc(anonymousDb(), path)));
    await assertFails(setDoc(doc(anonymousDb(), path), operationalLog()));
    await assertFails(getDoc(doc(dbFor("bob"), path)));
    await assertFails(setDoc(doc(dbFor("bob"), path), operationalLog()));
  });

  test("rejects malformed, oversized, and over-retained logs", async () => {
    const db = dbFor("alice");
    const invalidDocuments = [
      operationalLog({ schemaVersion: 2 }),
      operationalLog({ event: "" }),
      operationalLog({ event: "x".repeat(81) }),
      operationalLog({ platform: "ios" }),
      operationalLog({ correlationId: "" }),
      operationalLog({ durationMs: -1 }),
      operationalLog({ errorMessage: "x".repeat(501) }),
      operationalLog({ expiresAt: Timestamp.fromDate(new Date(Date.now() + 32 * 24 * 60 * 60 * 1000)) }),
      withoutField(operationalLog(), "fatal"),
      { ...operationalLog(), email: "aluno@ufmg.br" },
    ];

    for (const [index, data] of invalidDocuments.entries()) {
      await assertFails(setDoc(doc(db, logPath("alice", `invalid-${index}`)), data));
    }
  });
});

describe("meeting documents", () => {
  test("accept valid schedules owned by the tenant", async () => {
    await seed(coursePath("alice"), course());
    await assertSucceeds(
      setDoc(doc(dbFor("alice"), meetingPath("alice")), meeting()),
    );
  });

  test("reject schedules whose parent course does not exist", async () => {
    await assertFails(
      setDoc(doc(dbFor("alice"), meetingPath("alice")), meeting()),
    );
  });

  test("reject invalid schedules and document shapes", async () => {
    await seed(coursePath("alice"), course());
    const db = dbFor("alice");
    const invalidDocuments = [
      meeting({ weekday: 0 }),
      meeting({ weekday: 8 }),
      meeting({ startMinutes: -1 }),
      meeting({ endMinutes: 1441 }),
      meeting({ startMinutes: 600, endMinutes: 600 }),
      meeting({ lessonCount: 3 }),
      meeting({ lessonCount: 1, callCount: 2 }),
      meeting({ callCount: 3 }),
      { ...meeting(), latitude: -19.87 },
    ];

    for (const [index, data] of invalidDocuments.entries()) {
      await assertFails(
        setDoc(doc(db, meetingPath("alice", `invalid-${index}`)), data),
      );
    }
  });
});

describe("session documents", () => {
  test("accept unresolved, pending, and resolved attendance", async () => {
    await seed(coursePath("alice"), course());
    const db = dbFor("alice");

    await assertSucceeds(setDoc(doc(db, sessionPath("alice", "unresolved")), session()));
    await assertSucceeds(
      setDoc(
        doc(db, sessionPath("alice", "pending")),
        session({
          firstPing: "indisponivel",
          secondPing: "fora",
          attendanceStatus: "pendente",
        }),
      ),
    );
    await assertSucceeds(
      setDoc(
        doc(db, sessionPath("alice", "resolved")),
        session({
          firstPing: "fora",
          secondPing: "no_campus",
          attendanceStatus: "chegou_atrasado",
          absences: 1,
        }),
      ),
    );
  });

  test("reject sessions whose parent course does not exist", async () => {
    await assertFails(
      setDoc(doc(dbFor("alice"), sessionPath("alice")), session()),
    );
  });

  test("reject invalid evidence, attendance, configuration, and shape", async () => {
    await seed(coursePath("alice"), course());
    const db = dbFor("alice");
    const invalidDocuments = [
      session({ endsAt: Timestamp.fromDate(new Date("2026-08-03T10:00:00Z")) }),
      session({ lessonCount: 3 }),
      session({ lessonCount: 1, callCount: 2 }),
      session({ firstPing: "campus-a" }),
      session({ secondPing: "unknown" }),
      session({ attendanceStatus: "unknown" }),
      session({ calendarStatus: "unknown" }),
      session({ absences: 1 }),
      session({ attendanceStatus: "pendente", absences: 0 }),
      session({ attendanceStatus: "presente", absences: null }),
      session({ attendanceStatus: "presente", absences: -1 }),
      session({ attendanceStatus: "presente", absences: 3 }),
      { ...session(), longitude: -43.96 },
    ];

    for (const [index, data] of invalidDocuments.entries()) {
      await assertFails(
        setDoc(doc(db, sessionPath("alice", `invalid-${index}`)), data),
      );
    }
  });
});
