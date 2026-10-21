import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../observability/audited_operation.dart';
import '../observability/error_log_details.dart';

enum PythonBackendError {
  appCheckInvalid,
  credentialsUnavailable,
  destructiveConflict,
  invalidResponse,
  moodleAuthorizationRequired,
  rateLimited,
  replayed,
  scheduleConflict,
  timeout,
  unauthorized,
  ufmgCredentialsInvalid,
  ufmgReauthenticationRequired,
  ufmgUnavailable,
  unavailable,
}

enum PythonBackendCredential { firebaseIdentity, appCheck }

enum _BackendMethod { get, post, put, delete }

final class PythonBackendException implements Exception, StructuredAppError {
  const PythonBackendException(
    this.code, {
    this.retryAfter,
    this.destructiveSessions,
    this.credential,
    this.causeType,
  });

  final PythonBackendError code;
  final Duration? retryAfter;
  final int? destructiveSessions;
  final PythonBackendCredential? credential;
  final String? causeType;

  @override
  String get logCode => code.name;

  @override
  String get logMessage => 'Python backend request failed.';

  @override
  String? get logDetails {
    final values = [
      if (credential case final value?) 'credential=${value.name}',
      if (causeType case final value?) 'cause=$value',
    ];
    return values.isEmpty ? null : values.join(', ');
  }

  @override
  String toString() {
    final details = logDetails;
    return details == null
        ? 'PythonBackendException(${code.name})'
        : 'PythonBackendException(${code.name}, $details)';
  }
}

bool isTransientPythonBackendFailure(Object error) =>
    error is PythonBackendException &&
    (error.code == PythonBackendError.credentialsUnavailable ||
        error.code == PythonBackendError.timeout ||
        error.code == PythonBackendError.unavailable);

abstract interface class PythonBackendTokens {
  Future<String> firebaseIdToken({required bool forceRefresh});

  Future<String> appCheckToken({required bool limitedUse});
}

abstract interface class BackendIdentityVerifier {
  Future<void> verifyIdentity();
}

abstract interface class BackendUFMGSessionGateway {
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus();

  Future<PythonUFMGSessionStatus> connectUFMG({
    required String username,
    required String password,
  });

  Future<PythonUFMGSessionStatus> disconnectUFMG();

  Future<PythonUFMGCourseImportResult> importUFMGCourses();

  Future<PythonUFMGScheduleImportResult> importUFMGSchedules();

  Future<PythonMoodleDateImportResult> importMoodleDates();

  Future<List<PythonMoodleDate>> listMoodleDates();

  Future<PythonMoodleContentDiscovery> discoverMoodleContent();

  Future<PythonMoodleContentDiscovery> listMoodleMaterialCatalog();

  Future<PythonMoodleMobileCapabilities> probeMoodleMobileCapabilities();

  Future<List<PythonMoodleMaterialFile>> listMoodleMaterialFiles({
    required String term,
    required String courseId,
    required String sourceId,
  });

  Future<PythonUFMGSigaSyncResult> syncSiga();
}

abstract interface class BackendDiarioPlanGateway {
  Future<PythonDiarioPlanProbe> probeMoodleDiarioPlan({
    required String term,
    required String sourceId,
  });
}

enum PythonMoodleContentStatus { found, empty, unmatched, ambiguous }

enum PythonMoodleContentOrigin { canonical, metaturma }

final class PythonMoodleMobileCapabilities {
  const PythonMoodleMobileCapabilities({
    required this.term,
    required this.directDownloadSupported,
    required this.downloadFiles,
    required this.privateFileAccess,
    required this.webserviceTokenIssued,
  });

  final String term;
  final bool directDownloadSupported;
  final bool downloadFiles;
  final bool privateFileAccess;
  final bool webserviceTokenIssued;
}

final class PythonDiarioPlanProbe {
  const PythonDiarioPlanProbe({
    required this.term,
    required this.sourceId,
    required this.delivery,
    required this.contentLength,
  });

  final String term;
  final String sourceId;
  final String delivery;
  final int contentLength;
}

final class PythonMoodleContentCandidate {
  const PythonMoodleContentCandidate({
    required this.sourceId,
    required this.moodleCourseId,
    required this.kind,
    required this.title,
    required this.url,
    required this.relevance,
    required this.origin,
  });

  factory PythonMoodleContentCandidate.fromJson(Map<String, Object?> json) {
    const keys = {
      'source_id',
      'moodle_course_id',
      'kind',
      'title',
      'url',
      'relevance',
      'origin',
    };
    if (!_hasExactKeys(json, keys)) throw const FormatException();
    final sourceId = json['source_id'];
    final moodleCourseId = json['moodle_course_id'];
    final kind = json['kind'];
    final title = json['title'];
    final rawUrl = json['url'];
    final relevance = json['relevance'];
    final origin = switch (json['origin']) {
      'canonical' => PythonMoodleContentOrigin.canonical,
      'metaturma' => PythonMoodleContentOrigin.metaturma,
      _ => null,
    };
    final uri = rawUrl is String ? Uri.tryParse(rawUrl) : null;
    if (sourceId is! String ||
        !_moodleSourceId.hasMatch(sourceId) ||
        (int.tryParse(sourceId) ?? 0) > 2147483647 ||
        moodleCourseId is! String ||
        !_moodleSourceId.hasMatch(moodleCourseId) ||
        (int.tryParse(moodleCourseId) ?? 0) > 2147483647 ||
        kind is! String ||
        !const {'page', 'file', 'text', 'link'}.contains(kind) ||
        title is! String ||
        title.isEmpty ||
        title.trim() != title ||
        title.length > 1024 ||
        relevance is! String ||
        !const {'teaching_plan', 'schedule', 'other'}.contains(relevance) ||
        origin == null ||
        (kind == 'text') != (rawUrl == null) ||
        (rawUrl != null &&
            (uri == null || !_isSafeMoodleMaterialUri(uri, sourceId, kind)))) {
      throw const FormatException();
    }
    return PythonMoodleContentCandidate(
      sourceId: sourceId,
      moodleCourseId: moodleCourseId,
      kind: kind,
      title: title,
      url: uri,
      relevance: relevance,
      origin: origin,
    );
  }

  final String sourceId;
  final String moodleCourseId;
  final String kind;
  final String title;
  final Uri? url;
  final String relevance;
  final PythonMoodleContentOrigin origin;

  bool get canOpenDirectly =>
      url != null && _isSafeMoodleMaterialUri(url!, sourceId, kind);
}

final class PythonMoodleMaterialFile {
  const PythonMoodleMaterialFile({
    required this.name,
    required this.url,
    required this.size,
    required this.mimeType,
  });

  factory PythonMoodleMaterialFile.fromJson(Map<String, Object?> json) {
    if (!_hasExactKeys(json, const {'name', 'url', 'size', 'mime_type'})) {
      throw const FormatException();
    }
    final name = json['name'];
    final rawUrl = json['url'];
    final size = json['size'];
    final mimeType = json['mime_type'];
    final url = rawUrl is String ? Uri.tryParse(rawUrl) : null;
    if (name is! String ||
        name.isEmpty ||
        name.trim() != name ||
        name.length > 255 ||
        url == null ||
        !_isSafeMoodleDownloadUri(url) ||
        size is! int ||
        size < 0 ||
        size > 10000000000 ||
        mimeType is! String ||
        !RegExp(r'^[a-z0-9.+-]+/[a-z0-9.+-]+$').hasMatch(mimeType)) {
      throw const FormatException();
    }
    return PythonMoodleMaterialFile(
      name: name,
      url: url,
      size: size,
      mimeType: mimeType,
    );
  }

  final String name;
  final Uri url;
  final int size;
  final String mimeType;
}

bool _isSafeMoodleDownloadUri(Uri uri) {
  final segments = uri.pathSegments;
  return uri.scheme == 'https' &&
      uri.host == 'virtual.ufmg.br' &&
      !uri.hasPort &&
      uri.userInfo.isEmpty &&
      !uri.hasFragment &&
      segments.length >= 8 &&
      _moodlePeriod.hasMatch(segments[0]) &&
      segments[1] == 'tokenpluginfile.php' &&
      RegExp(r'^[A-Za-z0-9]{16,256}$').hasMatch(segments[2]) &&
      !segments.skip(3).any((segment) => segment.isEmpty || segment == '..') &&
      uri.queryParametersAll.length == 1 &&
      uri.queryParametersAll['forcedownload']?.length == 1 &&
      uri.queryParametersAll['forcedownload']?.single == '1';
}

final RegExp _moodleSourceId = RegExp(r'^[1-9][0-9]{0,9}$');
final RegExp _moodlePeriod = RegExp(r'^[0-9]{5}$');

bool _isSafeMoodleMaterialUri(Uri uri, String sourceId, String kind) {
  final segments = uri.pathSegments;
  if (uri.scheme != 'https' ||
      uri.host != 'virtual.ufmg.br' ||
      uri.hasPort ||
      uri.userInfo.isNotEmpty ||
      uri.hasFragment ||
      segments.length != 4 ||
      !_moodlePeriod.hasMatch(segments[0]) ||
      segments[1] != 'mod' ||
      segments[3] != 'view.php' ||
      uri.queryParametersAll.length != 1 ||
      uri.queryParametersAll['id']?.length != 1 ||
      uri.queryParametersAll['id']?.single != sourceId) {
    return false;
  }
  return switch (kind) {
    'page' => const {'page', 'book'}.contains(segments[2]),
    'file' => const {'resource', 'folder'}.contains(segments[2]),
    'link' => segments[2] == 'url',
    _ => false,
  };
}

final class PythonMoodleCourseContent {
  const PythonMoodleCourseContent({
    required this.courseId,
    required this.courseCode,
    required this.term,
    required this.moodleCourseId,
    required this.status,
    required this.candidates,
  });

  final String courseId;
  final String courseCode;
  final String term;
  final String? moodleCourseId;
  final PythonMoodleContentStatus status;
  final List<PythonMoodleContentCandidate> candidates;
}

final class PythonMoodleContentDiscovery {
  const PythonMoodleContentDiscovery({
    required this.courses,
    required this.candidateTotal,
    required this.metaturmaCandidateTotal,
  });

  final List<PythonMoodleCourseContent> courses;
  final int candidateTotal;
  final int metaturmaCandidateTotal;
}

final class PythonUFMGCourseImportResult {
  const PythonUFMGCourseImportResult({
    required this.created,
    required this.existing,
    required this.total,
  });

  final int created;
  final int existing;
  final int total;
}

final class PythonUFMGScheduleImportResult {
  const PythonUFMGScheduleImportResult({
    required this.total,
    required this.updated,
    required this.unchanged,
    required this.conflicts,
    required this.missingCourses,
    required this.meetingsImported,
  });

  final int total;
  final int updated;
  final int unchanged;
  final int conflicts;
  final int missingCourses;
  final int meetingsImported;
}

final class PythonUFMGSigaSyncResult {
  const PythonUFMGSigaSyncResult({
    required this.courses,
    required this.schedules,
    required this.checkedAt,
    required this.nextAutomaticSyncAt,
  });

  final PythonUFMGCourseImportResult courses;
  final PythonUFMGScheduleImportResult schedules;
  final DateTime checkedAt;
  final DateTime nextAutomaticSyncAt;
}

final class PythonMoodleDateImportResult {
  const PythonMoodleDateImportResult({
    required this.total,
    required this.matched,
    required this.unmatched,
    required this.created,
    required this.updated,
    required this.unchanged,
  });

  final int total;
  final int matched;
  final int unmatched;
  final int created;
  final int updated;
  final int unchanged;
}

final class PythonMoodleDate {
  const PythonMoodleDate({
    required this.id,
    required this.courseId,
    required this.courseCode,
    required this.title,
    required this.dueAt,
    required this.kind,
  });

  factory PythonMoodleDate.fromJson(Map<String, Object?> json) {
    const keys = {
      'id',
      'course_id',
      'course_code',
      'title',
      'due_at',
      'kind',
      'source',
      'source_id',
      'created_at',
      'updated_at',
    };
    if (!_hasExactKeys(json, keys) || json['source'] != 'moodle') {
      throw const FormatException();
    }
    final id = json['id'];
    final courseId = json['course_id'];
    final courseCode = json['course_code'];
    final title = json['title'];
    final kind = json['kind'];
    final sourceId = json['source_id'];
    final dueAt = _utcDate(json['due_at']);
    _utcDate(json['created_at']);
    _utcDate(json['updated_at']);
    if (id is! String ||
        courseId is! String ||
        courseCode is! String ||
        title is! String ||
        sourceId is! String ||
        kind is! String ||
        id != 'moodle-$sourceId' ||
        courseId.isEmpty ||
        courseCode.isEmpty ||
        title.isEmpty ||
        title.length > 120 ||
        !const {'assignment', 'quiz', 'event'}.contains(kind)) {
      throw const FormatException();
    }
    return PythonMoodleDate(
      id: id,
      courseId: courseId,
      courseCode: courseCode,
      title: title,
      dueAt: dueAt,
      kind: kind,
    );
  }

  final String id;
  final String courseId;
  final String courseCode;
  final String title;
  final DateTime dueAt;
  final String kind;
}

final class PythonUFMGSessionStatus {
  const PythonUFMGSessionStatus({
    required this.connected,
    required this.reauthenticationRequired,
    this.createdAt,
    this.expiresAt,
  });

  final bool connected;
  final bool reauthenticationRequired;
  final DateTime? createdAt;
  final DateTime? expiresAt;
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

abstract interface class LocalFirstScheduleGateway
    implements BackendScheduleGateway {
  Future<PythonSchedule?> getCachedSchedule(String courseId);
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

PythonUFMGCourseImportResult _courseImportResult(Object? value) {
  if (value is! Map<String, dynamic> ||
      !_hasExactKeys(value, const {'created', 'existing', 'total'})) {
    throw const FormatException();
  }
  final created = value['created'];
  final existing = value['existing'];
  final total = value['total'];
  if (created is! int ||
      existing is! int ||
      total is! int ||
      created < 0 ||
      existing < 0 ||
      total != created + existing) {
    throw const FormatException();
  }
  return PythonUFMGCourseImportResult(
    created: created,
    existing: existing,
    total: total,
  );
}

PythonUFMGScheduleImportResult _scheduleImportResult(Object? value) {
  const keys = {
    'total',
    'updated',
    'unchanged',
    'conflicts',
    'missing_courses',
    'meetings_imported',
  };
  if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
    throw const FormatException();
  }
  final counts = keys.map((key) => value[key]).toList();
  if (counts.any((count) => count is! int || count < 0)) {
    throw const FormatException();
  }
  final total = value['total'] as int;
  final updated = value['updated'] as int;
  final unchanged = value['unchanged'] as int;
  final conflicts = value['conflicts'] as int;
  final missingCourses = value['missing_courses'] as int;
  final meetingsImported = value['meetings_imported'] as int;
  if (total != updated + unchanged + conflicts + missingCourses ||
      meetingsImported > updated * 32) {
    throw const FormatException();
  }
  return PythonUFMGScheduleImportResult(
    total: total,
    updated: updated,
    unchanged: unchanged,
    conflicts: conflicts,
    missingCourses: missingCourses,
    meetingsImported: meetingsImported,
  );
}

PythonMoodleDateImportResult _moodleDateImportResult(Object? value) {
  const keys = {
    'total',
    'matched',
    'unmatched',
    'created',
    'updated',
    'unchanged',
  };
  if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
    throw const FormatException();
  }
  final counts = keys.map((key) => value[key]).toList();
  if (counts.any((count) => count is! int || count < 0 || count > 500)) {
    throw const FormatException();
  }
  final result = PythonMoodleDateImportResult(
    total: value['total'] as int,
    matched: value['matched'] as int,
    unmatched: value['unmatched'] as int,
    created: value['created'] as int,
    updated: value['updated'] as int,
    unchanged: value['unchanged'] as int,
  );
  if (result.total != result.matched + result.unmatched ||
      result.matched != result.created + result.updated + result.unchanged) {
    throw const FormatException();
  }
  return result;
}

DateTime _utcDate(Object? value) {
  if (value is! String || !value.endsWith('Z')) throw const FormatException();
  final parsed = DateTime.tryParse(value);
  if (parsed == null || !parsed.isUtc) throw const FormatException();
  return parsed;
}

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
        BackendUFMGSessionGateway,
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
  Future<String>? _regularAppCheckTokenInFlight;

  @override
  Future<void> verifyIdentity() async {
    final response = await _authenticatedRequest(path: '/v1/identity');
    if (_isAuthenticated(response.body)) return;
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  @override
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus() async {
    final response = await _authenticatedRequest(path: '/v1/ufmg/session');
    return _ufmgSessionStatus(response.body);
  }

  @override
  Future<PythonUFMGSessionStatus> connectUFMG({
    required String username,
    required String password,
  }) async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/session',
      method: _BackendMethod.post,
      body: {'username': username, 'password': password},
    );
    return _ufmgSessionStatus(response.body);
  }

  @override
  Future<PythonUFMGSessionStatus> disconnectUFMG() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/session',
      method: _BackendMethod.delete,
    );
    return _ufmgSessionStatus(response.body);
  }

  @override
  Future<PythonUFMGCourseImportResult> importUFMGCourses() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/import/courses',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      final value = jsonDecode(response.body);
      if (value is! Map<String, dynamic> ||
          !_hasExactKeys(value, const {'created', 'existing', 'total'})) {
        throw const FormatException();
      }
      final created = value['created'];
      final existing = value['existing'];
      final total = value['total'];
      if (created is! int ||
          existing is! int ||
          total is! int ||
          created < 0 ||
          existing < 0 ||
          total != created + existing) {
        throw const FormatException();
      }
      return PythonUFMGCourseImportResult(
        created: created,
        existing: existing,
        total: total,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonUFMGScheduleImportResult> importUFMGSchedules() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/import/schedules',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      final value = jsonDecode(response.body);
      return _scheduleImportResult(value);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonMoodleDateImportResult> importMoodleDates() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/import/dates',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      return _moodleDateImportResult(jsonDecode(response.body));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonMoodleContentDiscovery> discoverMoodleContent() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/discover/content',
      method: _BackendMethod.post,
      body: const {},
    );
    return _moodleContentDiscovery(
      response.body,
      includesCandidateCourseIds: false,
    );
  }

  @override
  Future<PythonMoodleContentDiscovery> listMoodleMaterialCatalog() async {
    final response = await _authenticatedRequest(path: '/v1/moodle/materials');
    return _moodleContentDiscovery(
      response.body,
      includesCandidateCourseIds: true,
    );
  }

  PythonMoodleContentDiscovery _moodleContentDiscovery(
    String body, {
    required bool includesCandidateCourseIds,
  }) {
    try {
      final value = jsonDecode(body);
      final keys = <String>{
        'courses',
        'course_total',
        'candidate_total',
        'metaturma_candidate_total',
        'found',
        'empty',
        'unmatched',
        'ambiguous',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      final rawCourses = value['courses'];
      final candidateTotal = value['candidate_total'];
      final metaturmaCandidateTotal = value['metaturma_candidate_total'];
      if (rawCourses is! List ||
          rawCourses.length > 50 ||
          value['course_total'] != rawCourses.length ||
          candidateTotal is! int ||
          candidateTotal < 0 ||
          candidateTotal > 500 ||
          metaturmaCandidateTotal is! int ||
          metaturmaCandidateTotal < 0 ||
          metaturmaCandidateTotal > candidateTotal) {
        throw const FormatException();
      }
      final counts = <PythonMoodleContentStatus, int>{};
      var candidates = 0;
      final courses = rawCourses
          .map((raw) {
            final json = Map<String, Object?>.from(raw as Map);
            if (!_hasExactKeys(json, const {
              'course_id',
              'course_code',
              'term',
              'moodle_course_id',
              'status',
              'candidates',
            })) {
              throw const FormatException();
            }
            final courseId = json['course_id'];
            final courseCode = json['course_code'];
            final term = json['term'];
            final moodleCourseId = json['moodle_course_id'];
            final rawStatus = json['status'];
            final rawCandidates = json['candidates'];
            final status = switch (rawStatus) {
              'found' => PythonMoodleContentStatus.found,
              'empty' => PythonMoodleContentStatus.empty,
              'unmatched' => PythonMoodleContentStatus.unmatched,
              'ambiguous' => PythonMoodleContentStatus.ambiguous,
              _ => null,
            };
            if (courseId is! String ||
                courseId.isEmpty ||
                courseCode is! String ||
                courseCode.isEmpty ||
                courseCode != courseCode.toUpperCase() ||
                term is! String ||
                !RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
                (moodleCourseId != null &&
                    (moodleCourseId is! String ||
                        !_moodleSourceId.hasMatch(moodleCourseId))) ||
                status == null ||
                rawCandidates is! List ||
                rawCandidates.length > 500) {
              throw const FormatException();
            }
            final parsedCandidates = rawCandidates
                .map((item) {
                  final candidate = Map<String, Object?>.from(item as Map);
                  if (!includesCandidateCourseIds) {
                    candidate['moodle_course_id'] = moodleCourseId;
                  }
                  return PythonMoodleContentCandidate.fromJson(candidate);
                })
                .toList(growable: false);
            if ((status == PythonMoodleContentStatus.found) !=
                parsedCandidates.isNotEmpty) {
              throw const FormatException();
            }
            final matched =
                status == PythonMoodleContentStatus.found ||
                status == PythonMoodleContentStatus.empty;
            if (matched != (moodleCourseId is String)) {
              throw const FormatException();
            }
            candidates += parsedCandidates.length;
            counts[status] = (counts[status] ?? 0) + 1;
            return PythonMoodleCourseContent(
              courseId: courseId,
              courseCode: courseCode,
              term: term,
              moodleCourseId: moodleCourseId as String?,
              status: status,
              candidates: parsedCandidates,
            );
          })
          .toList(growable: false);
      if (candidates != candidateTotal ||
          courses
                  .expand((course) => course.candidates)
                  .where(
                    (candidate) =>
                        candidate.origin == PythonMoodleContentOrigin.metaturma,
                  )
                  .length !=
              metaturmaCandidateTotal ||
          PythonMoodleContentStatus.values.any(
            (status) => value[status.name] != (counts[status] ?? 0),
          )) {
        throw const FormatException();
      }
      return PythonMoodleContentDiscovery(
        courses: courses,
        candidateTotal: candidateTotal,
        metaturmaCandidateTotal: metaturmaCandidateTotal,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonMoodleMobileCapabilities> probeMoodleMobileCapabilities() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/moodle/capabilities',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      final value = jsonDecode(response.body);
      const keys = {
        'term',
        'direct_download_supported',
        'download_files',
        'private_file_access',
        'webservice_token_issued',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      final term = value['term'];
      final direct = value['direct_download_supported'];
      final downloads = value['download_files'];
      final privateAccess = value['private_file_access'];
      final issued = value['webservice_token_issued'];
      if (term is! String ||
          !RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
          direct is! bool ||
          downloads is! bool ||
          privateAccess is! bool ||
          issued is! bool ||
          direct != (downloads && privateAccess && issued)) {
        throw const FormatException();
      }
      return PythonMoodleMobileCapabilities(
        term: term,
        directDownloadSupported: direct,
        downloadFiles: downloads,
        privateFileAccess: privateAccess,
        webserviceTokenIssued: issued,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<List<PythonMoodleMaterialFile>> listMoodleMaterialFiles({
    required String term,
    required String courseId,
    required String sourceId,
  }) async {
    final numericCourseId = int.tryParse(courseId);
    final numericSourceId = int.tryParse(sourceId);
    if (!RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
        numericCourseId == null ||
        numericCourseId < 1 ||
        numericCourseId > 2147483647 ||
        numericSourceId == null ||
        numericSourceId < 1 ||
        numericSourceId > 2147483647) {
      throw ArgumentError('invalid Moodle material identity');
    }
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/moodle/material-files',
      method: _BackendMethod.post,
      body: {
        'term': term,
        'course_id': numericCourseId,
        'source_id': numericSourceId,
      },
    );
    try {
      final value = jsonDecode(response.body);
      if (value is! Map<String, dynamic> ||
          !_hasExactKeys(value, const {'files', 'count'})) {
        throw const FormatException();
      }
      final rawFiles = value['files'];
      if (rawFiles is! List ||
          rawFiles.length > 100 ||
          value['count'] != rawFiles.length) {
        throw const FormatException();
      }
      return rawFiles
          .map(
            (raw) => PythonMoodleMaterialFile.fromJson(
              Map<String, Object?>.from(raw as Map),
            ),
          )
          .toList(growable: false);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  Future<PythonDiarioPlanProbe> probeMoodleDiarioPlan({
    required String term,
    required String sourceId,
  }) async {
    final numericSourceId = int.tryParse(sourceId);
    if (!RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
        numericSourceId == null ||
        numericSourceId < 1 ||
        numericSourceId > 2147483647) {
      throw ArgumentError('invalid Diario plan identity');
    }
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/moodle/diario-plan',
      method: _BackendMethod.post,
      body: {'term': term, 'source_id': numericSourceId},
    );
    try {
      final value = jsonDecode(response.body);
      const keys = {
        'available',
        'delivery',
        'format',
        'content_length',
        'term',
        'source_id',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      final delivery = value['delivery'];
      final contentLength = value['content_length'];
      if (value['available'] is! bool ||
          value['available'] != true ||
          !const {'redirect', 'form'}.contains(delivery) ||
          value['format'] != 'pdf' ||
          contentLength is! int ||
          contentLength < 9 ||
          contentLength > 20 * 1024 * 1024 ||
          value['term'] != term ||
          value['source_id'] != sourceId) {
        throw const FormatException();
      }
      return PythonDiarioPlanProbe(
        term: term,
        sourceId: sourceId,
        delivery: delivery as String,
        contentLength: contentLength,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<List<PythonMoodleDate>> listMoodleDates() async {
    final response = await _authenticatedRequest(path: '/v1/moodle/dates');
    try {
      final value = jsonDecode(response.body);
      final dates = value is Map<String, dynamic> ? value['dates'] : null;
      if (dates is! List || dates.length > 500) throw const FormatException();
      final result = dates
          .map(
            (item) => PythonMoodleDate.fromJson(
              Map<String, Object?>.from(item as Map),
            ),
          )
          .toList(growable: false);
      for (var index = 1; index < result.length; index++) {
        if (result[index].dueAt.isBefore(result[index - 1].dueAt)) {
          throw const FormatException();
        }
      }
      return result;
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonUFMGSigaSyncResult> syncSiga() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/sync/siga',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      final value = jsonDecode(response.body);
      const keys = {
        'courses',
        'schedules',
        'checked_at',
        'next_automatic_sync_at',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      final courses = _courseImportResult(value['courses']);
      final schedules = _scheduleImportResult(value['schedules']);
      final checkedAt = _utcDate(value['checked_at']);
      final nextAutomaticSyncAt = _utcDate(value['next_automatic_sync_at']);
      if (!nextAutomaticSyncAt.isAfter(checkedAt)) {
        throw const FormatException();
      }
      return PythonUFMGSigaSyncResult(
        courses: courses,
        schedules: schedules,
        checkedAt: checkedAt,
        nextAutomaticSyncAt: nextAutomaticSyncAt,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
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
      final response = await _requestWithReadRetry(
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

  Future<http.Response> _requestWithReadRetry({
    required bool forceIdentityRefresh,
    required String requestId,
    required String path,
    required _BackendMethod method,
    required Map<String, Object?>? body,
  }) async {
    try {
      return await _request(
        forceIdentityRefresh: forceIdentityRefresh,
        requestId: requestId,
        path: path,
        method: method,
        body: body,
      );
    } on PythonBackendException catch (error) {
      if (method != _BackendMethod.get ||
          (error.code != PythonBackendError.timeout &&
              error.code != PythonBackendError.unavailable)) {
        rethrow;
      }
      return _request(
        forceIdentityRefresh: forceIdentityRefresh,
        requestId: requestId,
        path: path,
        method: method,
        body: body,
      );
    }
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
        limitedUseAppCheck: method != _BackendMethod.get,
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
      throw const PythonBackendException(
        PythonBackendError.timeout,
        causeType: 'TimeoutException',
      );
    } catch (error) {
      throw PythonBackendException(
        PythonBackendError.unavailable,
        causeType: error.runtimeType.toString(),
      );
    }
  }

  Future<(String, String)> _credentials({
    required bool forceIdentityRefresh,
    required bool limitedUseAppCheck,
  }) async {
    late final String idToken;
    try {
      idToken = await _tokens.firebaseIdToken(
        forceRefresh: forceIdentityRefresh,
      );
    } catch (error) {
      throw PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.firebaseIdentity,
        causeType: error.runtimeType.toString(),
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
      appCheckToken = await _appCheckToken(limitedUse: limitedUseAppCheck);
    } catch (error) {
      throw PythonBackendException(
        PythonBackendError.credentialsUnavailable,
        credential: PythonBackendCredential.appCheck,
        causeType: error.runtimeType.toString(),
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

  Future<String> _appCheckToken({required bool limitedUse}) async {
    if (limitedUse) return _tokens.appCheckToken(limitedUse: true);
    final pending = _regularAppCheckTokenInFlight;
    if (pending != null) return pending;
    final request = _tokens.appCheckToken(limitedUse: false);
    _regularAppCheckTokenInFlight = request;
    try {
      return await request;
    } finally {
      if (identical(_regularAppCheckTokenInFlight, request)) {
        _regularAppCheckTokenInFlight = null;
      }
    }
  }

  static bool _isAuthenticated(String body) {
    try {
      final value = jsonDecode(body);
      return value is Map<String, dynamic> && value['authenticated'] == true;
    } catch (_) {
      return false;
    }
  }

  static PythonUFMGSessionStatus _ufmgSessionStatus(String body) {
    try {
      final value = jsonDecode(body);
      if (value is! Map<String, dynamic> || value['connected'] is! bool) {
        throw const FormatException();
      }
      final connected = value['connected'] as bool;
      if (!connected) {
        final onlyConnected = _hasExactKeys(value, const {'connected'});
        final withReason = _hasExactKeys(value, const {
          'connected',
          'reauthentication_required',
        });
        if (!onlyConnected &&
            (!withReason || value['reauthentication_required'] is! bool)) {
          throw const FormatException();
        }
        return PythonUFMGSessionStatus(
          connected: false,
          reauthenticationRequired: withReason
              ? value['reauthentication_required'] as bool
              : false,
        );
      }
      final withoutReason = _hasExactKeys(value, const {
        'connected',
        'created_at',
        'expires_at',
      });
      final withReason = _hasExactKeys(value, const {
        'connected',
        'created_at',
        'expires_at',
        'reauthentication_required',
      });
      if (!withoutReason &&
          (!withReason || value['reauthentication_required'] != false)) {
        throw const FormatException();
      }
      final createdAt = value['created_at'];
      final expiresAt = value['expires_at'];
      if (createdAt is! int ||
          expiresAt is! int ||
          createdAt < 0 ||
          expiresAt <= createdAt) {
        throw const FormatException();
      }
      return PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
        createdAt: DateTime.fromMillisecondsSinceEpoch(
          createdAt * 1000,
          isUtc: true,
        ),
        expiresAt: DateTime.fromMillisecondsSinceEpoch(
          expiresAt * 1000,
          isUtc: true,
        ),
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
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
    if (status == 401 && error == 'ufmg_credentials_invalid') {
      return const PythonBackendException(
        PythonBackendError.ufmgCredentialsInvalid,
      );
    }
    if (status == 401 && error == 'ufmg_reauthentication_required') {
      return const PythonBackendException(
        PythonBackendError.ufmgReauthenticationRequired,
      );
    }
    if (status == 401 && error == 'moodle_authorization_required') {
      return const PythonBackendException(
        PythonBackendError.moodleAuthorizationRequired,
      );
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
      if (error == 'ufmg_authentication_unavailable' ||
          error == 'ufmg_session_store_unavailable') {
        return const PythonBackendException(PythonBackendError.ufmgUnavailable);
      }
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
