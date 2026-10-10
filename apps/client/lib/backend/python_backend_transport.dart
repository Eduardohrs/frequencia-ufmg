import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../observability/audited_operation.dart';

enum PythonBackendError {
  appCheckInvalid,
  credentialsUnavailable,
  destructiveConflict,
  invalidResponse,
  rateLimited,
  replayed,
  scheduleConflict,
  timeout,
  unauthorized,
  unavailable,
}

enum PythonBackendCredential { firebaseIdentity, appCheck }

enum _BackendMethod { get, post, put, delete }

final class PythonBackendException implements Exception {
  const PythonBackendException(
    this.code, {
    this.retryAfter,
    this.destructiveSessions,
    this.credential,
  });

  final PythonBackendError code;
  final Duration? retryAfter;
  final int? destructiveSessions;
  final PythonBackendCredential? credential;

  @override
  String toString() => credential == null
      ? 'PythonBackendException(${code.name})'
      : 'PythonBackendException(${code.name}, credential=${credential!.name})';
}

bool isTransientPythonBackendFailure(Object error) =>
    error is PythonBackendException &&
    (error.code == PythonBackendError.timeout ||
        error.code == PythonBackendError.unavailable);

abstract interface class PythonBackendTokens {
  Future<String> firebaseIdToken({required bool forceRefresh});

  Future<String> limitedUseAppCheckToken();
}

abstract interface class BackendIdentityVerifier {
  Future<void> verifyIdentity();
}

abstract interface class BackendAttendanceEvaluator {
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  });
}

abstract interface class BackendCourseGateway {
  Future<List<PythonCourse>> listCourses();

  Future<PythonCourse> saveCourse(PythonCourse course);

  Future<void> deleteCourse(String courseId);
}

abstract interface class BackendScheduleGateway {
  Future<PythonSchedule> getSchedule(String courseId);

  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  });
}

abstract interface class BackendSessionGateway {
  Future<PythonAttendanceMutation> saveAttendance({
    required String courseId,
    required String sessionId,
    required String status,
    required int maximumAbsences,
    required bool useDefaultAbsences,
    int? correctedAbsences,
  });

  Future<PythonCalendarStatusMutation> saveCalendarStatus({
    required String courseId,
    required String sessionId,
    required String calendarStatus,
  });
}

abstract interface class BackendOverviewGateway {
  Future<List<PythonOverviewItem>> loadOverview();
}

final class PythonCourse {
  const PythonCourse({
    required this.id,
    required this.code,
    required this.name,
    required this.workload,
    required this.term,
    required this.startsOn,
    required this.endsOn,
    required this.createdAt,
    required this.updatedAt,
  });

  factory PythonCourse.fromJson(Map<String, Object?> json) {
    const keys = {
      'id',
      'code',
      'name',
      'workload',
      'term',
      'starts_on',
      'ends_on',
      'created_at',
      'updated_at',
    };
    if (json.keys.toSet().difference(keys).isNotEmpty ||
        keys.difference(json.keys.toSet()).isNotEmpty) {
      throw const FormatException();
    }
    final startsOn = _nullableDate(json['starts_on']);
    final endsOn = _nullableDate(json['ends_on']);
    final createdAt = _requiredDate(json['created_at']);
    final updatedAt = _requiredDate(json['updated_at']);
    final id = json['id'];
    final code = json['code'];
    final name = json['name'];
    final workload = json['workload'];
    final term = json['term'];
    if (id is! String ||
        id.isEmpty ||
        id.length > 128 ||
        id.contains('/') ||
        id.contains(r'\') ||
        code is! String ||
        code.isEmpty ||
        code != code.toUpperCase() ||
        name is! String ||
        name.trim() != name ||
        name.isEmpty ||
        workload is! int ||
        workload <= 0 ||
        term is! String ||
        !RegExp(r'^\d{4}-[12]$').hasMatch(term) ||
        (startsOn == null) != (endsOn == null) ||
        startsOn != null && endsOn != null && startsOn.isAfter(endsOn) ||
        updatedAt.isBefore(createdAt)) {
      throw const FormatException();
    }
    return PythonCourse(
      id: id,
      code: code,
      name: name,
      workload: workload,
      term: term,
      startsOn: startsOn,
      endsOn: endsOn,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }

  final String id;
  final String code;
  final String name;
  final int workload;
  final String term;
  final DateTime? startsOn;
  final DateTime? endsOn;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toJson({bool includeId = true}) => {
    if (includeId) 'id': id,
    'code': code,
    'name': name,
    'workload': workload,
    'term': term,
    'starts_on': startsOn?.toUtc().toIso8601String(),
    'ends_on': endsOn?.toUtc().toIso8601String(),
    'created_at': createdAt.toUtc().toIso8601String(),
    'updated_at': updatedAt.toUtc().toIso8601String(),
  };

  static DateTime? _nullableDate(Object? value) =>
      value == null ? null : _requiredDate(value);

  static DateTime _requiredDate(Object? value) {
    if (value is! String) throw const FormatException();
    final parsed = DateTime.tryParse(value);
    if (parsed == null || !value.endsWith('Z')) throw const FormatException();
    return parsed.toUtc();
  }
}

final class PythonMeeting {
  const PythonMeeting({
    required this.id,
    required this.weekday,
    required this.startMinutes,
    required this.endMinutes,
    required this.lessonCount,
    required this.callCount,
    required this.createdAt,
    required this.updatedAt,
  });

  factory PythonMeeting.fromJson(Map<String, Object?> json) {
    const keys = {
      'id',
      'weekday',
      'start_minutes',
      'end_minutes',
      'lesson_count',
      'call_count',
      'created_at',
      'updated_at',
    };
    if (!_hasExactKeys(json, keys)) throw const FormatException();
    final id = json['id'];
    final weekday = json['weekday'];
    final start = json['start_minutes'];
    final end = json['end_minutes'];
    final lessons = json['lesson_count'];
    final calls = json['call_count'];
    final createdAt = PythonCourse._requiredDate(json['created_at']);
    final updatedAt = PythonCourse._requiredDate(json['updated_at']);
    if (id is! String ||
        id.isEmpty ||
        id.length > 128 ||
        id.trim() != id ||
        id.contains('/') ||
        id.contains(r'\') ||
        weekday is! int ||
        weekday < 1 ||
        weekday > 7 ||
        start is! int ||
        start < 0 ||
        start > 1439 ||
        end is! int ||
        lessons is! int ||
        !{1, 2, 4}.contains(lessons) ||
        end != start + lessons * 50 ||
        end > 1440 ||
        calls is! int ||
        !{1, 2}.contains(calls) ||
        lessons == 1 && calls == 2 ||
        updatedAt.isBefore(createdAt)) {
      throw const FormatException();
    }
    return PythonMeeting(
      id: id,
      weekday: weekday,
      startMinutes: start,
      endMinutes: end,
      lessonCount: lessons,
      callCount: calls,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }

  final String id;
  final int weekday;
  final int startMinutes;
  final int endMinutes;
  final int lessonCount;
  final int callCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toMutationJson() => {
    'id': id,
    'weekday': weekday,
    'start_minutes': startMinutes,
    'lesson_count': lessonCount,
    'call_count': callCount,
  };
}

final class PythonScheduleChanges {
  const PythonScheduleChanges({
    required this.meetingUpserts,
    required this.meetingDeletes,
    required this.sessionUpserts,
    required this.sessionDeletes,
    required this.destructiveDeletes,
  });

  factory PythonScheduleChanges.fromJson(Map<String, Object?> json) {
    const keys = {
      'meeting_upserts',
      'meeting_deletes',
      'session_upserts',
      'session_deletes',
      'destructive_deletes',
    };
    if (!_hasExactKeys(json, keys) ||
        json.values.any((value) => value is! int || value < 0)) {
      throw const FormatException();
    }
    return PythonScheduleChanges(
      meetingUpserts: json['meeting_upserts']! as int,
      meetingDeletes: json['meeting_deletes']! as int,
      sessionUpserts: json['session_upserts']! as int,
      sessionDeletes: json['session_deletes']! as int,
      destructiveDeletes: json['destructive_deletes']! as int,
    );
  }

  final int meetingUpserts;
  final int meetingDeletes;
  final int sessionUpserts;
  final int sessionDeletes;
  final int destructiveDeletes;
}

final class PythonSchedule {
  const PythonSchedule({
    required this.course,
    required this.meetings,
    required this.changes,
    this.isLocalCopy = false,
  });

  factory PythonSchedule.fromJson(Map<String, Object?> json) {
    if (!_hasExactKeys(json, {'course', 'meetings', 'changes'})) {
      throw const FormatException();
    }
    final meetings = json['meetings'];
    if (meetings is! List) throw const FormatException();
    return PythonSchedule(
      course: PythonCourse.fromJson(
        Map<String, Object?>.from(json['course']! as Map),
      ),
      meetings: meetings
          .map(
            (item) =>
                PythonMeeting.fromJson(Map<String, Object?>.from(item as Map)),
          )
          .toList(growable: false),
      changes: PythonScheduleChanges.fromJson(
        Map<String, Object?>.from(json['changes']! as Map),
      ),
    );
  }

  final PythonCourse course;
  final List<PythonMeeting> meetings;
  final PythonScheduleChanges changes;
  final bool isLocalCopy;
}

bool _hasExactKeys(Map<String, Object?> json, Set<String> keys) =>
    json.keys.toSet().difference(keys).isEmpty &&
    keys.difference(json.keys.toSet()).isEmpty;

final class PythonAttendanceDecision {
  const PythonAttendanceDecision({
    required this.status,
    required this.absences,
  });

  final String status;
  final int? absences;
}

final class PythonAttendanceMutation {
  const PythonAttendanceMutation({
    required this.status,
    required this.absences,
    required this.updatedAt,
  });

  final String status;
  final int? absences;
  final DateTime updatedAt;
}

final class PythonCalendarStatusMutation {
  const PythonCalendarStatusMutation({
    required this.calendarStatus,
    required this.updatedAt,
  });

  final String calendarStatus;
  final DateTime updatedAt;
}

final class PythonSession {
  const PythonSession({
    required this.id,
    required this.startsAt,
    required this.endsAt,
    required this.lessonCount,
    required this.callCount,
    required this.firstPing,
    required this.secondPing,
    required this.attendanceStatus,
    required this.absences,
    required this.calendarStatus,
    required this.assessmentTitle,
    required this.createdAt,
    required this.updatedAt,
  });

  factory PythonSession.fromJson(Map<String, Object?> json) {
    const keys = {
      'id',
      'starts_at',
      'ends_at',
      'lesson_count',
      'call_count',
      'first_ping',
      'second_ping',
      'attendance_status',
      'absences',
      'calendar_status',
      'assessment_title',
      'created_at',
      'updated_at',
    };
    if (!_hasExactKeys(json, keys)) throw const FormatException();
    final id = json['id'];
    final startsAt = PythonCourse._requiredDate(json['starts_at']);
    final endsAt = PythonCourse._requiredDate(json['ends_at']);
    final lessonCount = json['lesson_count'];
    final callCount = json['call_count'];
    final firstPing = json['first_ping'];
    final secondPing = json['second_ping'];
    final attendanceStatus = json['attendance_status'];
    final absences = json['absences'];
    final calendarStatus = json['calendar_status'];
    final assessmentTitle = json['assessment_title'];
    final createdAt = PythonCourse._requiredDate(json['created_at']);
    final updatedAt = PythonCourse._requiredDate(json['updated_at']);
    const pingStates = {'no_campus', 'fora', 'indisponivel'};
    const attendanceStates = {
      'presente',
      'chegou_atrasado',
      'saiu_mais_cedo',
      'ausente',
      'pendente',
    };
    const calendarStates = {
      'scheduled',
      'cancelled',
      'holiday',
      'no_call',
      'makeup',
    };
    final unresolved =
        attendanceStatus == null || attendanceStatus == 'pendente';
    if (id is! String ||
        id.isEmpty ||
        id.length > 128 ||
        id.trim() != id ||
        id.contains('/') ||
        id.contains(r'\') ||
        lessonCount is! int ||
        !{1, 2, 4}.contains(lessonCount) ||
        callCount is! int ||
        !{1, 2}.contains(callCount) ||
        lessonCount == 1 && callCount == 2 ||
        !endsAt.isAfter(startsAt) ||
        endsAt.difference(startsAt) != Duration(minutes: lessonCount * 50) ||
        firstPing != null &&
            (firstPing is! String || !pingStates.contains(firstPing)) ||
        secondPing != null &&
            (secondPing is! String || !pingStates.contains(secondPing)) ||
        attendanceStatus != null &&
            (attendanceStatus is! String ||
                !attendanceStates.contains(attendanceStatus)) ||
        unresolved != (absences == null) ||
        absences != null &&
            (absences is! int || absences < 0 || absences > lessonCount) ||
        calendarStatus is! String ||
        !calendarStates.contains(calendarStatus) ||
        assessmentTitle != null &&
            (assessmentTitle is! String ||
                assessmentTitle.trim() != assessmentTitle ||
                assessmentTitle.isEmpty ||
                assessmentTitle.length > 120) ||
        updatedAt.isBefore(createdAt)) {
      throw const FormatException();
    }
    return PythonSession(
      id: id,
      startsAt: startsAt,
      endsAt: endsAt,
      lessonCount: lessonCount,
      callCount: callCount,
      firstPing: firstPing as String?,
      secondPing: secondPing as String?,
      attendanceStatus: attendanceStatus as String?,
      absences: absences as int?,
      calendarStatus: calendarStatus,
      assessmentTitle: assessmentTitle as String?,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
  }

  final String id;
  final DateTime startsAt;
  final DateTime endsAt;
  final int lessonCount;
  final int callCount;
  final String? firstPing;
  final String? secondPing;
  final String? attendanceStatus;
  final int? absences;
  final String calendarStatus;
  final String? assessmentTitle;
  final DateTime createdAt;
  final DateTime updatedAt;
}

final class PythonOverviewItem {
  const PythonOverviewItem({required this.course, required this.sessions});

  final PythonCourse course;
  final List<PythonSession> sessions;
}

final class PythonBackendSettings {
  const PythonBackendSettings({required this.enabled, required this.endpoint});

  final bool enabled;
  final String endpoint;

  Uri? get endpointUri {
    if (!enabled) return null;
    final uri = Uri.tryParse(endpoint);
    final isLocal =
        uri?.scheme == 'http' &&
        (uri?.host == 'localhost' || uri?.host == '127.0.0.1');
    if (uri == null ||
        (!uri.hasScheme || (uri.scheme != 'https' && !isLocal)) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw ArgumentError.value(endpoint, 'endpoint', 'unsafe backend origin');
    }
    return uri.replace(path: '');
  }
}

final class PythonBackendTransport
    implements
        BackendIdentityVerifier,
        BackendAttendanceEvaluator,
        BackendCourseGateway,
        BackendScheduleGateway,
        BackendSessionGateway,
        BackendOverviewGateway {
  PythonBackendTransport({
    required Uri endpoint,
    required PythonBackendTokens tokens,
    required http.Client client,
    this.timeout = const Duration(seconds: 30),
  }) : _endpoint = endpoint,
       _tokens = tokens,
       _client = client;

  final Uri _endpoint;
  final PythonBackendTokens _tokens;
  final http.Client _client;
  final Duration timeout;

  @override
  Future<void> verifyIdentity() async {
    final response = await _authenticatedRequest(path: '/v1/identity');
    if (_isAuthenticated(response.body)) return;
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  @override
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  }) async {
    final response = await _authenticatedRequest(
      path: '/v1/attendance/evaluate',
      method: _BackendMethod.post,
      body: {'lessons': lessons, 'calls': calls, 'status': status},
    );
    return _attendanceDecision(response.body, maximumAbsences: lessons);
  }

  @override
  Future<List<PythonCourse>> listCourses() async {
    final response = await _authenticatedRequest(path: '/v1/courses');
    try {
      final value = jsonDecode(response.body);
      final courses = value is Map<String, dynamic> ? value['courses'] : null;
      if (courses is! List) throw const FormatException();
      return courses
          .map(
            (item) =>
                PythonCourse.fromJson(Map<String, Object?>.from(item as Map)),
          )
          .toList(growable: false);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<List<PythonOverviewItem>> loadOverview() async {
    final response = await _authenticatedRequest(path: '/v1/overview');
    try {
      final value = jsonDecode(response.body);
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, {'items'})) {
        throw const FormatException();
      }
      final items = value['items'];
      if (items is! List) throw const FormatException();
      return items
          .map((item) {
            final json = Map<String, Object?>.from(item as Map);
            if (!_hasExactKeys(json, {'course', 'sessions'})) {
              throw const FormatException();
            }
            final sessions = json['sessions'];
            if (sessions is! List) throw const FormatException();
            return PythonOverviewItem(
              course: PythonCourse.fromJson(
                Map<String, Object?>.from(json['course']! as Map),
              ),
              sessions: sessions
                  .map(
                    (session) => PythonSession.fromJson(
                      Map<String, Object?>.from(session as Map),
                    ),
                  )
                  .toList(growable: false),
            );
          })
          .toList(growable: false);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonCourse> saveCourse(PythonCourse course) async {
    _validateCourseId(course.id);
    final response = await _authenticatedRequest(
      path: '/v1/courses/${Uri.encodeComponent(course.id)}',
      method: _BackendMethod.put,
      body: course.toJson(includeId: false),
    );
    try {
      final value = jsonDecode(response.body);
      final saved = value is Map<String, dynamic> ? value['course'] : null;
      return PythonCourse.fromJson(Map<String, Object?>.from(saved as Map));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<void> deleteCourse(String courseId) async {
    _validateCourseId(courseId);
    final response = await _authenticatedRequest(
      path: '/v1/courses/${Uri.encodeComponent(courseId)}',
      method: _BackendMethod.delete,
    );
    try {
      final value = jsonDecode(response.body);
      if (value is Map<String, dynamic> && value['deleted'] == true) return;
    } catch (_) {}
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  @override
  Future<PythonSchedule> getSchedule(String courseId) async {
    _validateCourseId(courseId);
    final response = await _authenticatedRequest(
      path: '/v1/courses/${Uri.encodeComponent(courseId)}/schedule',
    );
    return _schedule(response.body);
  }

  @override
  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  }) async {
    _validateCourseId(courseId);
    final response = await _authenticatedRequest(
      path: '/v1/courses/${Uri.encodeComponent(courseId)}/schedule',
      method: _BackendMethod.put,
      body: {
        'starts_on': startsOn?.toUtc().toIso8601String(),
        'ends_on': endsOn?.toUtc().toIso8601String(),
        'meetings': meetings
            .map((item) => item.toMutationJson())
            .toList(growable: false),
        'confirm_destructive': confirmDestructive,
      },
    );
    return _schedule(response.body);
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
    _validateCourseId(courseId);
    _validateCourseId(sessionId);
    final response = await _authenticatedRequest(
      path:
          '/v1/courses/${Uri.encodeComponent(courseId)}/sessions/'
          '${Uri.encodeComponent(sessionId)}/attendance',
      method: _BackendMethod.put,
      body: {
        'status': status,
        if (!useDefaultAbsences) 'absences': correctedAbsences,
      },
    );
    final decision = _attendanceDecision(
      response.body,
      maximumAbsences: maximumAbsences,
      expectedKeys: const {'status', 'absences', 'updated_at'},
    );
    if (decision.status != status) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
    final updatedAt = _updatedAt(response.body);
    return PythonAttendanceMutation(
      status: decision.status,
      absences: decision.absences,
      updatedAt: updatedAt,
    );
  }

  @override
  Future<PythonCalendarStatusMutation> saveCalendarStatus({
    required String courseId,
    required String sessionId,
    required String calendarStatus,
  }) async {
    _validateCourseId(courseId);
    _validateCourseId(sessionId);
    final response = await _authenticatedRequest(
      path:
          '/v1/courses/${Uri.encodeComponent(courseId)}/sessions/'
          '${Uri.encodeComponent(sessionId)}/calendar-status',
      method: _BackendMethod.put,
      body: {'calendar_status': calendarStatus},
    );
    try {
      final value = jsonDecode(response.body);
      if (value is! Map<String, dynamic> ||
          !_hasExactKeys(value, const {'calendar_status', 'updated_at'})) {
        throw const FormatException();
      }
      final savedStatus = value['calendar_status'];
      const allowed = {'scheduled', 'cancelled', 'holiday', 'no_call'};
      if (savedStatus is! String || !allowed.contains(savedStatus)) {
        throw const FormatException();
      }
      if (savedStatus != calendarStatus) throw const FormatException();
      return PythonCalendarStatusMutation(
        calendarStatus: savedStatus,
        updatedAt: PythonCourse._requiredDate(value['updated_at']),
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  Future<http.Response> _authenticatedRequest({
    required String path,
    _BackendMethod method = _BackendMethod.get,
    Map<String, Object?>? body,
  }) async {
    var forceIdentityRefresh = false;
    final requestId = currentOperationId ?? newCorrelationId('request');
    for (var attempt = 0; attempt < 2; attempt += 1) {
      final response = await _request(
        forceIdentityRefresh: forceIdentityRefresh,
        requestId: requestId,
        path: path,
        method: method,
        body: body,
      );
      final error = _errorCode(response);
      if (response.statusCode == 200) return response;
      if (attempt == 0 && error == 'unauthorized') {
        forceIdentityRefresh = true;
        continue;
      }
      if (attempt == 0 && error == 'app_check_replayed') continue;
      throw _exceptionFor(
        response.statusCode,
        error,
        response.headers,
        destructiveSessions: _destructiveSessions(response),
      );
    }
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  Future<http.Response> _request({
    required bool forceIdentityRefresh,
    required String requestId,
    required String path,
    required _BackendMethod method,
    required Map<String, Object?>? body,
  }) async {
    try {
      final (idToken, appCheckToken) = await _credentials(
        forceIdentityRefresh: forceIdentityRefresh,
      );
      final headers = {
        'Authorization': 'Bearer $idToken',
        'X-Firebase-AppCheck': appCheckToken,
        'X-Request-ID': requestId,
      };
      final uri = _endpoint.resolve(path);
      final request = switch (method) {
        _BackendMethod.get => _client.get(uri, headers: headers),
        _BackendMethod.delete => _client.delete(uri, headers: headers),
        _BackendMethod.post => _client.post(
          uri,
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(body),
        ),
        _BackendMethod.put => _client.put(
          uri,
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(body),
        ),
      };
      return await request.timeout(timeout);
    } on PythonBackendException {
      rethrow;
    } on TimeoutException {
      throw const PythonBackendException(PythonBackendError.timeout);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.unavailable);
    }
  }

  Future<(String, String)> _credentials({
    required bool forceIdentityRefresh,
  }) async {
    late final String idToken;
    try {
      idToken = await _tokens.firebaseIdToken(
        forceRefresh: forceIdentityRefresh,
      );
    } catch (_) {
      throw const PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.firebaseIdentity,
      );
    }
    if (idToken.isEmpty) {
      throw const PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.firebaseIdentity,
      );
    }
    late final String appCheckToken;
    try {
      appCheckToken = await _tokens.limitedUseAppCheckToken();
    } catch (_) {
      throw const PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.appCheck,
      );
    }
    if (appCheckToken.isEmpty) {
      throw const PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.appCheck,
      );
    }
    return (idToken, appCheckToken);
  }

  static bool _isAuthenticated(String body) {
    try {
      final value = jsonDecode(body);
      return value is Map<String, dynamic> && value['authenticated'] == true;
    } catch (_) {
      return false;
    }
  }

  static PythonAttendanceDecision _attendanceDecision(
    String body, {
    required int maximumAbsences,
    Set<String> expectedKeys = const {'status', 'absences'},
  }) {
    try {
      final value = jsonDecode(body);
      if (value is! Map<String, dynamic> ||
          !_hasExactKeys(value, expectedKeys)) {
        throw const FormatException();
      }
      final status = value['status'];
      final absences = value['absences'];
      const allowedStatuses = {
        'presente',
        'chegou_atrasado',
        'saiu_mais_cedo',
        'ausente',
        'pendente',
      };
      final validAbsences =
          absences == null ||
          absences is int && absences >= 0 && absences <= maximumAbsences;
      if (status is! String ||
          !allowedStatuses.contains(status) ||
          !validAbsences ||
          (status == 'pendente') != (absences == null)) {
        throw const FormatException();
      }
      return PythonAttendanceDecision(
        status: status,
        absences: absences as int?,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  static DateTime _updatedAt(String body) {
    try {
      final value = jsonDecode(body) as Map<String, dynamic>;
      return PythonCourse._requiredDate(value['updated_at']);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  static PythonSchedule _schedule(String body) {
    try {
      final value = jsonDecode(body);
      return PythonSchedule.fromJson(Map<String, Object?>.from(value as Map));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  static String? _errorCode(http.Response response) {
    try {
      final value = jsonDecode(response.body);
      return value is Map<String, dynamic> && value['error'] is String
          ? value['error'] as String
          : null;
    } catch (_) {
      return null;
    }
  }

  static int? _destructiveSessions(http.Response response) {
    try {
      final value = jsonDecode(response.body);
      final count = value is Map<String, dynamic>
          ? value['destructive_sessions']
          : null;
      return count is int && count > 0 && count <= 450 ? count : null;
    } catch (_) {
      return null;
    }
  }

  static PythonBackendException _exceptionFor(
    int status,
    String? error,
    Map<String, String> headers, {
    int? destructiveSessions,
  }) {
    if (status == 401 && error == 'app_check_invalid') {
      return const PythonBackendException(PythonBackendError.appCheckInvalid);
    }
    if (status == 401) {
      return const PythonBackendException(PythonBackendError.unauthorized);
    }
    if (status == 409 && error == 'app_check_replayed') {
      return const PythonBackendException(PythonBackendError.replayed);
    }
    if (status == 409 &&
        error == 'schedule_destructive_conflict' &&
        destructiveSessions != null) {
      return PythonBackendException(
        PythonBackendError.destructiveConflict,
        destructiveSessions: destructiveSessions,
      );
    }
    if (status == 409 && error == 'schedule_overlap') {
      return const PythonBackendException(PythonBackendError.scheduleConflict);
    }
    if (status == 429) {
      final seconds = int.tryParse(headers['retry-after'] ?? '');
      return PythonBackendException(
        PythonBackendError.rateLimited,
        retryAfter: seconds != null && seconds > 0 && seconds <= 3600
            ? Duration(seconds: seconds)
            : null,
      );
    }
    if (status == 503) {
      return const PythonBackendException(PythonBackendError.unavailable);
    }
    return const PythonBackendException(PythonBackendError.invalidResponse);
  }

  static void _validateCourseId(String value) {
    if (value.isEmpty ||
        value.length > 128 ||
        value.trim() != value ||
        value.contains('/') ||
        value.contains(r'\')) {
      throw ArgumentError.value(value, 'courseId', 'unsafe course id');
    }
  }
}
