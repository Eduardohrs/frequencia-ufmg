import { createApp, type AppDependencies, type Env } from "./app";
import { verifyFirebaseAppCheck, verifyFirebaseIdToken } from "./auth";

const dependencies: AppDependencies = {
  now: () => Date.now(),
  requestId: () => crypto.randomUUID(),
  verifyAppCheck: verifyFirebaseAppCheck,
  verifyIdToken: verifyFirebaseIdToken,
};

export default createApp(dependencies) satisfies ExportedHandler<Env>;
