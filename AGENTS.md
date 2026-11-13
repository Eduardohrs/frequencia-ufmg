# Repository guidance

Eduardo owns merge decisions. Do not merge, enable auto-merge, push directly to main, or deploy as part of a review. Reviewers must not change production data or use real attendance records as test fixtures.

## Code Review Rules

### Evidence and scope
- Review the current head SHA against its base and recheck prior findings against the actual new code. Follow callers through the production path; a helper, mock-only test or unused wrapper does not deliver the feature.
- Report reproducible, consequential defects with a concrete trigger, impact and file/line. Distinguish confirmed defects from missing evidence; do not invent infrastructure causes (including IPv4/IPv6) from generic timeouts. Do not repeat resolved findings or block on stylistic preferences.
- Check requirements in tasks/plan.md and the relevant session/audit documents. A session must deliver a user-testable outcome; report unconnected UI/backend pieces and lost requirements.
- Review every new push independently of a human readiness announcement. Review completion does not mean CI, deploy or production validation passed. State the tested revision and actual evidence; never call pending/failed/cancelled/missing checks green. A positive official Codecov comment for the current patch may substitute only a delayed Codecov status.
- Keep local, mocked transport, physical-device, deployed-build and production-log evidence distinct. Reuse accepted equivalent tests when behavior has not changed; do not demand another identical device test solely because a merge happened.

### Persistence, integration and free-tier compatibility
- Validate actual SDK versions, response objects, nested payloads, query encoding and HTTP status contracts on the real call path. Prefer transport-level contract tests to mocks that invent a convenient SDK interface.
- Server API keys can bypass document ACLs: enforce authenticated ownership on reads, lists, updates and deletes, including drafts and persisted decisions. Never trust a caller-supplied owner ID.
- Reuse configured existing infrastructure. New database/collection IDs, indexes, credentials or scopes require a concrete compatible setup path within the free plan. Do not assume another database is allowed or that a deploy credential can administer schemas. One-time provisioning is not a reason to require admin credentials on every deployment.
- Validate dependencies before activating new code; a setup failure must preserve the working release. Keep runtime credentials limited to runtime needs. Pin compatible build tooling consistently across CI, web deploy and APK release; do not weaken coverage or exclude live code to make CI pass.

### Academic data and offline behavior
- Preserve real attendance, manual corrections and the latest successful snapshots. Changing a schedule must reconcile old generated sessions, not accumulate duplicates or delete recorded attendance silently. Reject overlapping sessions across and within disciplines.
- Respect documented attendance rules for pending records, cancelled/holiday classes, classes without roll call, online disciplines and replacement classes. Keep assessment dates and lesson schedules consistent without interpreting every imported event as a new class.
- Sync best effort per source/course: a failed import must not clear successful cached data or abort unrelated courses. Repeated syncs must be idempotent; persisted manual conflict choices must survive reopening and repeat sync until the source changes.
- Save recoverable forms locally before attempting network persistence; isolate caches/drafts by account. Only clear the matching draft after confirmed success. Offline screens must retain schedules, sessions and activities, not merely course names. Reconcile pending writes without double-applying them.
- Keep imported activities visible in global and course-specific views with correct course association. Material bytes should download directly from Moodle to the device under the established design, not silently consume our server bandwidth/storage.

### Background execution and diagnostics
- Distinguish scheduling, permission checks, actual location capture, queued delivery and confirmed server persistence. An alarm firing is not proof a fresh location was captured. Check timestamp/accuracy and cached-location handling, per-campus configuration and the documented one/two-ping rules.
- Android foreground success does not prove background operation: preparation and transfer must both survive the supported screen-lock/app-removed/battery scenarios. Do not equate swipe-away with force-stop, or promise unsupported OS behavior. Keep device tests explicitly scoped and preserve user data/settings.
- Batch downloads should use a stable aggregate notification, not a notification per file. Cancellation and partial failure must leave an accurate saved-file list; deleted or failed files must not remain presented as available offline.
- Errors need correlation, operation/stage, source/course, status/reason and duration sufficient to distinguish transport, auth, upstream, parsing and persistence failures. Course/file names are useful context; never log passwords, cookies, tokens, signed credentials or API keys. Bound retries, buffers and telemetry volume so diagnostics cannot starve functional reads/writes.
- User messages must be short and actionable, linking to the affected item or resolution. Do not expose debug menus, giant zero-count summaries or implementation details as ordinary navigation. Prefer recognizable course names/nicknames to codes and preserve coherent navigation.
