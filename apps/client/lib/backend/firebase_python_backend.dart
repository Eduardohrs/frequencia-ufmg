// This file is a thin boundary over native/web Firebase plugins and compile-time
// deployment settings. Its behavior is covered through the injected transport.
// coverage:ignore-file

import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'python_backend_transport.dart';

const _settings = PythonBackendSettings(
  enabled: bool.fromEnvironment('ENABLE_PYTHON_BACKEND'),
  endpoint: String.fromEnvironment('PYTHON_BACKEND_ORIGIN'),
);
const _webSiteKey = String.fromEnvironment('FIREBASE_APP_CHECK_WEB_SITE_KEY');
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
        BackendAttendanceEvaluator,
        BackendCourseGateway,
        BackendScheduleGateway,
        BackendSessionGateway,
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
      providerAndroid: kDebugMode
          ? const AndroidDebugProvider()
          : const AndroidPlayIntegrityProvider(),
    );
  }
}

final class _FirebasePythonBackendTokens implements PythonBackendTokens {
  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken(
      forceRefresh,
    );
    return token ?? '';
  }

  @override
  Future<String> limitedUseAppCheckToken() =>
      FirebaseAppCheck.instance.getLimitedUseToken();
}
