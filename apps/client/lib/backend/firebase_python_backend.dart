// This file is a thin boundary over native/web Firebase plugins and compile-time
// deployment settings. Its behavior is covered through the injected transport.
// coverage:ignore-file

import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'python_backend_transport.dart';
import 'academic_sync_progress.dart';

const _settings = PythonBackendSettings(
  enabled: bool.fromEnvironment('ENABLE_PYTHON_BACKEND'),
  endpoint: String.fromEnvironment('PYTHON_BACKEND_ORIGIN'),
);
const _webSiteKey = String.fromEnvironment('FIREBASE_APP_CHECK_WEB_SITE_KEY');
const _androidDebugProviderEnabled = bool.fromEnvironment(
  'FIREBASE_APP_CHECK_ANDROID_DEBUG_PROVIDER',
);
const pythonScheduleWritesEnabled = bool.fromEnvironment(
  'ENABLE_PYTHON_SCHEDULE_WRITES',
);
const pythonSessionWritesEnabled = bool.fromEnvironment(
  'ENABLE_PYTHON_SESSION_WRITES',
);
const pythonOverviewReadsEnabled = bool.fromEnvironment(
  'ENABLE_PYTHON_OVERVIEW_READS',
);

BackendIdentityVerifier? createFirebasePythonBackendVerifier() {
  final endpoint = _settings.endpointUri;
  if (endpoint == null) return null;
  return _FirebasePythonBackendVerifier(endpoint);
}

final class _FirebasePythonBackendVerifier
    implements
        BackendIdentityVerifier,
        BackendAcademicWorkspaceGateway,
        BackendCourseSyncPolicyGateway,
        BackendAttendanceEvaluator,
        BackendCourseGateway,
        BackendScheduleGateway,
        BackendSessionGateway,
        BackendUFMGSessionGateway,
        BackendUnifiedAcademicSyncGateway,
        BackendAcademicSyncProgressGateway,
        BackendResumableAcademicSyncGateway,
        BackendOfficialCalendarGateway,
        BackendDiarioPlanGateway,
        BackendOverviewGateway {
  _FirebasePythonBackendVerifier(Uri endpoint)
    : _transport = PythonBackendTransport(
        endpoint: endpoint,
        tokens: _FirebasePythonBackendTokens(),
        client: http.Client(),
      );

  final PythonBackendTransport _transport;
  Future<void>? _activation;

  @override
  Future<void> verifyIdentity() async {
    await (_activation ??= _activateAppCheck());
    await _transport.verifyIdentity();
  }

  @override
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus() async {
    await (_activation ??= _activateAppCheck());
    return _transport.getUFMGSessionStatus();
  }

  @override
  Future<PythonUFMGSessionStatus> connectUFMG({
    required String username,
    required String password,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.connectUFMG(username: username, password: password);
  }

  @override
  Future<PythonUFMGSessionStatus> disconnectUFMG() async {
    await (_activation ??= _activateAppCheck());
    return _transport.disconnectUFMG();
  }

  @override
  Future<PythonUFMGCourseImportResult> importUFMGCourses() async {
    await (_activation ??= _activateAppCheck());
    return _transport.importUFMGCourses();
  }

  @override
  Future<PythonUFMGScheduleImportResult> importUFMGSchedules() async {
    await (_activation ??= _activateAppCheck());
    return _transport.importUFMGSchedules();
  }

  Future<BackendAcademicWorkspaceGateway> _workspaceGateway() async {
    await (_activation ??= _activateAppCheck());
    return _transport.workspace;
  }

  @override
  Future<PythonCourseActivitySnapshot> loadCourseActivitySnapshot(
    String courseId,
  ) async => (await _workspaceGateway()).loadCourseActivitySnapshot(courseId);
  @override
  Future<List<PythonMoodleDate>> listCourseDates(String courseId) async =>
      (await _workspaceGateway()).listCourseDates(courseId);
  @override
  Future<void> saveCourseDate(
    String courseId,
    String dateId, {
    required String title,
    required DateTime dueAt,
    required String kind,
  }) async => (await _workspaceGateway()).saveCourseDate(
    courseId,
    dateId,
    title: title,
    dueAt: dueAt,
    kind: kind,
  );
  @override
  Future<void> deleteCourseDate(String courseId, String dateId) async =>
      (await _workspaceGateway()).deleteCourseDate(courseId, dateId);
  @override
  Future<Map<String, Object?>?> loadCoursePlan(String courseId) async =>
      (await _workspaceGateway()).loadCoursePlan(courseId);
  @override
  Future<List<PythonMoodleActivity>> listCourseActivities(
    String courseId,
  ) async => (await _workspaceGateway()).listCourseActivities(courseId);
  @override
  Future<PythonMoodleActivityDetail> loadCourseActivity(
    String courseId,
    String sourceId,
  ) async => (await _workspaceGateway()).loadCourseActivity(courseId, sourceId);

  @override
  Future<PythonMoodleDateImportResult> importMoodleDates() async {
    await (_activation ??= _activateAppCheck());
    return _transport.importMoodleDates();
  }

  @override
  Future<List<PythonMoodleDate>> listMoodleDates() async {
    await (_activation ??= _activateAppCheck());
    return _transport.listMoodleDates();
  }

  @override
  Future<PythonMoodleContentDiscovery> discoverMoodleContent() async {
    await (_activation ??= _activateAppCheck());
    return _transport.discoverMoodleContent();
  }

  @override
  Future<PythonMoodleContentDiscovery> listMoodleMaterialCatalog() async {
    await (_activation ??= _activateAppCheck());
    return _transport.listMoodleMaterialCatalog();
  }

  @override
  Future<PythonMoodleMobileCapabilities> probeMoodleMobileCapabilities() async {
    await (_activation ??= _activateAppCheck());
    return _transport.probeMoodleMobileCapabilities();
  }

  @override
  Future<PythonMoodleSyncResult> syncMoodle() async {
    await (_activation ??= _activateAppCheck());
    return _transport.syncMoodle();
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncAllAcademicData() async {
    await (_activation ??= _activateAppCheck());
    return _transport.syncAllAcademicData(background: true);
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncWithProgress(
    String operationId, {
    bool force = false,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.syncAllAcademicData(
      progressId: operationId,
      background: true,
      force: force,
    );
  }

  @override
  Future<bool> coursePlanSyncPaused(String courseId) async {
    await (_activation ??= _activateAppCheck());
    return _transport.courseSyncPolicy.coursePlanSyncPaused(courseId);
  }

  @override
  Future<void> setCoursePlanSyncPaused(
    String courseId, {
    required bool paused,
  }) async {
    await (_activation ??= _activateAppCheck());
    await _transport.courseSyncPolicy.setCoursePlanSyncPaused(
      courseId,
      paused: paused,
    );
  }

  @override
  Future<String?> pendingAcademicSyncId() async {
    await (_activation ??= _activateAppCheck());
    return _transport.pendingAcademicSyncId();
  }

  @override
  Stream<AcademicSyncProgress> watchSyncProgress(String operationId) async* {
    await (_activation ??= _activateAppCheck());
    yield* FirebaseFirestore.instance
        .doc(
          'users/${FirebaseAuth.instance.currentUser!.uid}/syncProgress/current',
        )
        .snapshots()
        .where(
          (snapshot) =>
              snapshot.exists && snapshot.data()?['operationId'] == operationId,
        )
        .map((snapshot) => AcademicSyncProgress.fromMap(snapshot.data()!));
  }

  @override
  Future<PythonOfficialCalendarPreview> previewOfficialCalendar() async {
    await (_activation ??= _activateAppCheck());
    return _transport.previewOfficialCalendar();
  }

  @override
  Future<PythonOfficialCalendarApplyResult> applyOfficialCalendar(
    List<PythonOfficialCalendarChange> changes,
  ) async {
    await (_activation ??= _activateAppCheck());
    return _transport.applyOfficialCalendar(changes);
  }

  @override
  Future<PythonDiarioPlanProbe> probeMoodleDiarioPlan({
    required String term,
    required String sourceId,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.probeMoodleDiarioPlan(term: term, sourceId: sourceId);
  }

  @override
  Future<PythonTeachingPlanImport> importMoodleTeachingPlan({
    required String courseId,
    required String term,
    required String sourceId,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.importMoodleTeachingPlan(
      courseId: courseId,
      term: term,
      sourceId: sourceId,
    );
  }

  @override
  Future<PythonTeachingPlanReconciliation> reconcileMoodleTeachingPlan({
    required String courseId,
    required bool apply,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.reconcileMoodleTeachingPlan(
      courseId: courseId,
      apply: apply,
    );
  }

  @override
  Future<List<PythonMoodleMaterialFile>> listMoodleMaterialFiles({
    required String term,
    required String courseId,
    required String sourceId,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.listMoodleMaterialFiles(
      term: term,
      courseId: courseId,
      sourceId: sourceId,
    );
  }

  @override
  Future<PythonUFMGSigaSyncResult> syncSiga() async {
    await (_activation ??= _activateAppCheck());
    return _transport.syncSiga();
  }

  @override
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.evaluateAttendanceStatus(
      lessons: lessons,
      calls: calls,
      status: status,
    );
  }

  @override
  Future<List<PythonCourse>> listCourses() async {
    await (_activation ??= _activateAppCheck());
    return _transport.listCourses();
  }

  @override
  Future<List<PythonOverviewItem>> loadOverview() async {
    await (_activation ??= _activateAppCheck());
    return _transport.loadOverview();
  }

  @override
  Future<PythonCourse> saveCourse(PythonCourse course) async {
    await (_activation ??= _activateAppCheck());
    return _transport.saveCourse(course);
  }

  @override
  Future<void> deleteCourse(String courseId) async {
    await (_activation ??= _activateAppCheck());
    await _transport.deleteCourse(courseId);
  }

  @override
  Future<PythonSchedule> getSchedule(String courseId) async {
    await (_activation ??= _activateAppCheck());
    return _transport.getSchedule(courseId);
  }

  @override
  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.saveSchedule(
      courseId: courseId,
      startsOn: startsOn,
      endsOn: endsOn,
      meetings: meetings,
      confirmDestructive: confirmDestructive,
    );
  }

  @override
  Future<PythonAttendanceMutation> saveAttendance({
    required String courseId,
    required String sessionId,
    required String status,
    required int maximumAbsences,
    required bool useDefaultAbsences,
    int? correctedAbsences,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.saveAttendance(
      courseId: courseId,
      sessionId: sessionId,
      status: status,
      maximumAbsences: maximumAbsences,
      useDefaultAbsences: useDefaultAbsences,
      correctedAbsences: correctedAbsences,
    );
  }

  @override
  Future<PythonCalendarStatusMutation> saveCalendarStatus({
    required String courseId,
    required String sessionId,
    required String calendarStatus,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.saveCalendarStatus(
      courseId: courseId,
      sessionId: sessionId,
      calendarStatus: calendarStatus,
    );
  }

  static Future<void> _activateAppCheck() async {
    if (kIsWeb && _webSiteKey.isEmpty) {
      throw StateError('Firebase App Check web site key is not configured.');
    }
    await FirebaseAppCheck.instance.activate(
      providerWeb: ReCaptchaEnterpriseProvider(_webSiteKey),
      providerAndroid: selectAndroidAppCheckProvider(
        debugProviderEnabled: _androidDebugProviderEnabled,
      ),
    );
  }
}

@visibleForTesting
AndroidAppCheckProvider selectAndroidAppCheckProvider({
  required bool debugProviderEnabled,
}) => debugProviderEnabled
    ? const AndroidDebugProvider()
    : const AndroidPlayIntegrityProvider();

final class _FirebasePythonBackendTokens implements PythonBackendTokens {
  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken(
      forceRefresh,
    );
    return token ?? '';
  }

  @override
  Future<String> appCheckToken({required bool limitedUse}) async {
    if (limitedUse) return FirebaseAppCheck.instance.getLimitedUseToken();
    return await FirebaseAppCheck.instance.getToken() ?? '';
  }
}
