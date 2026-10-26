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

String? _credentialDiagnostics(Object error) {
  final details = ErrorLogDetails.from(error);
  if (details.code == null) return null;
  return 'sdk_code=${details.code} sdk_message=${details.message ?? ""}';
}

final class PythonBackendException implements Exception, StructuredAppError {
  const PythonBackendException(
    this.code, {
    this.retryAfter,
    this.destructiveSessions,
    this.credential,
    this.causeType,
    this.requestContext,
    this.credentialDetails,
  });

  final PythonBackendError code;
  final Duration? retryAfter;
  final int? destructiveSessions;
  final PythonBackendCredential? credential;
  final String? causeType;
  final String? requestContext;
  final String? credentialDetails;

  @override
  String get logCode => code.name;

  @override
  String get logMessage => 'Python backend request failed.';

  @override
  String? get logDetails {
    final values = [
      ?requestContext,
      if (credential case final value?) 'credential=${value.name}',
      if (causeType case final value?) 'cause=$value',
      ?credentialDetails,
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

  Future<PythonMoodleSyncResult> syncMoodle();

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

  Future<PythonTeachingPlanImport> importMoodleTeachingPlan({
    required String courseId,
    required String term,
    required String sourceId,
  });

  Future<PythonTeachingPlanReconciliation> reconcileMoodleTeachingPlan({
    required String courseId,
    required bool apply,
  });
}

abstract interface class BackendUnifiedAcademicSyncGateway {
  Future<PythonUnifiedAcademicSyncResult> syncAllAcademicData();
}

abstract interface class BackendOfficialCalendarGateway {
  Future<PythonOfficialCalendarPreview> previewOfficialCalendar();

  Future<PythonOfficialCalendarApplyResult> applyOfficialCalendar(
    List<PythonOfficialCalendarChange> changes,
  );
}

final class PythonOfficialCalendarChange {
  const PythonOfficialCalendarChange({
    required this.courseId,
    required this.courseCode,
    required this.sessionId,
    required this.date,
    required this.startsAt,
    required this.endsAt,
    required this.eventTitle,
  });

  final String courseId;
  final String courseCode;
  final String sessionId;
  final DateTime date;
  final DateTime startsAt;
  final DateTime endsAt;
  final String eventTitle;
}

final class PythonOfficialCalendarPreview {
  const PythonOfficialCalendarPreview({required this.candidates});

  final List<PythonOfficialCalendarChange> candidates;
}

final class PythonOfficialCalendarApplyResult {
  const PythonOfficialCalendarApplyResult({
    required this.applied,
    required this.skipped,
  });

  final int applied;
  final int skipped;
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

final class PythonMoodleSyncResult {
  const PythonMoodleSyncResult({
    required this.dates,
    required this.candidateTotal,
    required this.capabilities,
  });

  final PythonMoodleDateImportResult dates;
  final int candidateTotal;
  final PythonMoodleMobileCapabilities? capabilities;
}

final class PythonTeachingPlanSyncSummary {
  const PythonTeachingPlanSyncSummary({
    required this.available,
    required this.imported,
    required this.applied,
    required this.unchanged,
    required this.reviewRequired,
  });

  final int available;
  final int imported;
  final int applied;
  final int unchanged;
  final int reviewRequired;
}

final class PythonAcademicSyncException {
  const PythonAcademicSyncException({
    required this.courseId,
    required this.courseCode,
    required this.reason,
    required this.candidateCount,
    required this.changes,
    required this.conflicting,
    required this.assessmentConflicts,
  });

  final String courseId;
  final String courseCode;
  final String reason;
  final int candidateCount;
  final List<PythonTeachingPlanChange> changes;
  final int conflicting;
  final int assessmentConflicts;
}

final class PythonUnifiedAcademicSyncResult {
  const PythonUnifiedAcademicSyncResult({
    required this.siga,
    required this.moodle,
    required this.teachingPlans,
    required this.exceptions,
  });

  final PythonUFMGSigaSyncResult siga;
  final PythonMoodleSyncResult moodle;
  final PythonTeachingPlanSyncSummary teachingPlans;
  final List<PythonAcademicSyncException> exceptions;
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

final class PythonTeachingPlanImport {
  const PythonTeachingPlanImport({
    required this.assessmentTotal,
    required this.undatedAssessmentTotal,
    required this.criteriaTotal,
    required this.scheduleTotal,
    required this.createdDates,
    required this.updatedDates,
    required this.removedDates,
    this.notPublished = false,
  });

  final int assessmentTotal;
  final int undatedAssessmentTotal;
  final int criteriaTotal;
  final int scheduleTotal;
  final int createdDates;
  final int updatedDates;
  final int removedDates;
  final bool notPublished;
}

final class PythonTeachingPlanReconciliation {
  const PythonTeachingPlanReconciliation({
    required this.mode,
    required this.matched,
    required this.missing,
    required this.conflicting,
    required this.assessmentsLinked,
    required this.assessmentConflicts,
    required this.outsideSchedule,
    required this.applied,
    required this.changes,
    required this.excluded,
    required this.workloadValidation,
  });

  final String mode;
  final int matched;
  final int missing;
  final int conflicting;
  final int assessmentsLinked;
  final int assessmentConflicts;
  final int outsideSchedule;
  final int applied;
  final List<PythonTeachingPlanChange> changes;
  final List<PythonTeachingPlanChange> excluded;
  final PythonWorkloadValidation? workloadValidation;
}

final class PythonWorkloadValidation {
  const PythonWorkloadValidation({
    required this.status,
    required this.expectedLessonUnits,
    required this.actualLessonUnits,
    required this.differenceLessonUnits,
    required this.expectedTypicalMeetings,
    required this.activeEncounters,
    required this.excludedEncounters,
    required this.scheduledLessonUnits,
    required this.noCallLessonUnits,
    required this.makeupLessonUnits,
  });

  factory PythonWorkloadValidation.fromJson(Map<String, Object?> json) {
    const keys = {
      'status',
      'expected_lesson_units',
      'actual_lesson_units',
      'difference_lesson_units',
      'expected_typical_meetings',
      'active_encounters',
      'excluded_encounters',
      'scheduled_lesson_units',
      'no_call_lesson_units',
      'makeup_lesson_units',
    };
    if (!_hasExactKeys(json, keys)) throw const FormatException();
    final status = json['status'];
    int integer(String key, {bool positive = false}) {
      final value = json[key];
      if (value is! int || positive && value <= 0 || !positive && value < 0) {
        throw const FormatException();
      }
      return value;
    }

    final difference = json['difference_lesson_units'];
    if (status is! String ||
        !{'aligned', 'below_expected', 'above_expected'}.contains(status) ||
        difference is! int) {
      throw const FormatException();
    }
    final expected = integer('expected_lesson_units', positive: true);
    final actual = integer('actual_lesson_units');
    if (actual - expected != difference ||
        (difference == 0) != (status == 'aligned') ||
        (difference < 0) != (status == 'below_expected')) {
      throw const FormatException();
    }
    return PythonWorkloadValidation(
      status: status,
      expectedLessonUnits: expected,
      actualLessonUnits: actual,
      differenceLessonUnits: difference,
      expectedTypicalMeetings: integer(
        'expected_typical_meetings',
        positive: true,
      ),
      activeEncounters: integer('active_encounters'),
      excludedEncounters: integer('excluded_encounters'),
      scheduledLessonUnits: integer('scheduled_lesson_units'),
      noCallLessonUnits: integer('no_call_lesson_units'),
      makeupLessonUnits: integer('makeup_lesson_units'),
    );
  }

  final String status;
  final int expectedLessonUnits;
  final int actualLessonUnits;
  final int differenceLessonUnits;
  final int expectedTypicalMeetings;
  final int activeEncounters;
  final int excludedEncounters;
  final int scheduledLessonUnits;
  final int noCallLessonUnits;
  final int makeupLessonUnits;
}

final class PythonTeachingPlanChange {
  const PythonTeachingPlanChange({
    required this.action,
    required this.date,
    required this.startsAt,
    required this.endsAt,
    required this.subject,
    this.reason,
  });

  factory PythonTeachingPlanChange.fromJson(Map<String, Object?> json) {
    const requiredKeys = {
      'action',
      'occurrence_key',
      'date',
      'starts_at',
      'ends_at',
      'subject',
    };
    final allowed = {...requiredKeys, 'reason'};
    if (json.keys.toSet().difference(allowed).isNotEmpty ||
        requiredKeys.difference(json.keys.toSet()).isNotEmpty) {
      throw const FormatException();
    }
    final action = json['action'];
    final date = DateTime.tryParse('${json['date']}');
    final startsAt = json['starts_at'];
    final endsAt = json['ends_at'];
    final subject = json['subject'];
    final reason = json['reason'];
    if (action is! String ||
        !{
          'create_session',
          'remove_session',
          'link_assessment',
          'excluded',
        }.contains(action) ||
        date == null ||
        startsAt is! String ||
        endsAt is! String ||
        subject is! String ||
        subject.isEmpty ||
        reason != null && reason is! String) {
      throw const FormatException();
    }
    return PythonTeachingPlanChange(
      action: action,
      date: date,
      startsAt: startsAt,
      endsAt: endsAt,
      subject: subject,
      reason: reason as String?,
    );
  }

  final String action;
  final DateTime date;
  final String startsAt;
  final String endsAt;
  final String subject;
  final String? reason;
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
    if (!_hasExactKeys(json, keys)) {
      throw const FormatException();
    }
    final id = json['id'];
    final courseId = json['course_id'];
    final courseCode = json['course_code'];
    final title = json['title'];
    final kind = json['kind'];
    final source = json['source'];
    final sourceId = json['source_id'];
    final dueAt = _utcDate(json['due_at']);
    _utcDate(json['created_at']);
    _utcDate(json['updated_at']);
    if (id is! String ||
        courseId is! String ||
        courseCode is! String ||
        title is! String ||
        sourceId is! String ||
        source is! String ||
        kind is! String ||
        !const {'moodle', 'diario'}.contains(source) ||
        id != '$source-$sourceId' ||
        courseId.isEmpty ||
        courseCode.isEmpty ||
        title.isEmpty ||
        title.length > 120 ||
        !const {'assignment', 'quiz', 'event', 'assessment'}.contains(kind)) {
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
    this.modality = 'in_person',
    this.attendancePolicy = 'required',
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
    if (json.keys.toSet().difference({
          ...keys,
          'modality',
          'attendance_policy',
        }).isNotEmpty ||
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
    final modality = json['modality'] ?? 'in_person';
    final policy = json['attendance_policy'] ?? 'required';
    if (!['in_person', 'online'].contains(modality) ||
        !['required', 'no_call'].contains(policy) ||
        modality == 'online' && policy != 'no_call') {
      throw const FormatException('Invalid attendance policy');
    }
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
      modality: modality as String,
      attendancePolicy: policy as String,
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
  final String modality;
  final String attendancePolicy;
  final String code;
  final String name;
  final int workload;
  final String term;
  final DateTime? startsOn;
  final DateTime? endsOn;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toJson({bool includeId = true}) => {
    if (modality != 'in_person' || attendancePolicy != 'required') ...{
      'modality': modality,
      'attendance_policy': attendancePolicy,
    },
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
        BackendUnifiedAcademicSyncGateway,
        BackendOfficialCalendarGateway,
        BackendOverviewGateway {
  PythonBackendTransport({
    required Uri endpoint,
    required PythonBackendTokens tokens,
    required http.Client client,
    this.timeout = const Duration(seconds: 30),
    this.longRunningTimeout = const Duration(seconds: 90),
  }) : _endpoint = endpoint,
       _tokens = tokens,
       _client = client;

  final Uri _endpoint;
  final PythonBackendTokens _tokens;
  final http.Client _client;
  final Duration timeout;
  final Duration longRunningTimeout;
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
      return _moodleMobileCapabilities(jsonDecode(response.body));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonMoodleSyncResult> syncMoodle() async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/sync/moodle',
      method: _BackendMethod.post,
      body: const {},
    );
    try {
      return _moodleSyncResult(jsonDecode(response.body));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  PythonMoodleSyncResult _moodleSyncResult(Object? raw) {
    final value = raw;
    if (value is! Map<String, dynamic> ||
        !_hasExactKeys(value, const {'dates', 'content', 'capabilities'})) {
      throw const FormatException();
    }
    final dates = _moodleDateImportResult(value['dates']);
    final content = Map<String, Object?>.from(value['content'] as Map);
    if (!_hasExactKeys(content, const {
      'course_total',
      'candidate_total',
      'metaturma_candidate_total',
      'found',
      'empty',
      'unmatched',
      'ambiguous',
    })) {
      throw const FormatException();
    }
    final courseTotal = content['course_total'];
    final candidateTotal = content['candidate_total'];
    final metaturmaTotal = content['metaturma_candidate_total'];
    final statuses = [
      content['found'],
      content['empty'],
      content['unmatched'],
      content['ambiguous'],
    ];
    if (courseTotal is! int ||
        courseTotal < 0 ||
        courseTotal > 50 ||
        candidateTotal is! int ||
        candidateTotal < 0 ||
        candidateTotal > 500 ||
        metaturmaTotal is! int ||
        metaturmaTotal < 0 ||
        metaturmaTotal > candidateTotal ||
        statuses.any((count) => count is! int || count < 0) ||
        statuses.cast<int>().fold<int>(0, (sum, count) => sum + count) !=
            courseTotal) {
      throw const FormatException();
    }
    final rawCapabilities = value['capabilities'];
    final capabilities = rawCapabilities == null
        ? null
        : _moodleMobileCapabilities(rawCapabilities);
    return PythonMoodleSyncResult(
      dates: dates,
      candidateTotal: candidateTotal,
      capabilities: capabilities,
    );
  }

  PythonMoodleMobileCapabilities _moodleMobileCapabilities(Object? raw) {
    final value = Map<String, Object?>.from(raw as Map);
    const keys = {
      'term',
      'direct_download_supported',
      'download_files',
      'private_file_access',
      'webservice_token_issued',
    };
    if (!_hasExactKeys(value, keys)) throw const FormatException();
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
        direct != (downloads && privateAccess)) {
      throw const FormatException();
    }
    return PythonMoodleMobileCapabilities(
      term: term,
      directDownloadSupported: direct,
      downloadFiles: downloads,
      privateFileAccess: privateAccess,
      webserviceTokenIssued: issued,
    );
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
          !const {'redirect', 'form', 'link'}.contains(delivery) ||
          !const {'pdf', 'html'}.contains(value['format']) ||
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

  Future<PythonTeachingPlanImport> importMoodleTeachingPlan({
    required String courseId,
    required String term,
    required String sourceId,
  }) async {
    _validateCourseId(courseId);
    final numericSourceId = int.tryParse(sourceId);
    if (!RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
        numericSourceId == null ||
        numericSourceId < 1 ||
        numericSourceId > 2147483647) {
      throw ArgumentError('invalid Diario plan identity');
    }
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/import/teaching-plan',
      method: _BackendMethod.post,
      body: {'course_id': courseId, 'term': term, 'source_id': numericSourceId},
    );
    try {
      final value = jsonDecode(response.body);
      const keys = {
        'course_id',
        'term',
        'source_id',
        'plan',
        'assessment_total',
        'undated_assessment_total',
        'dates_created',
        'dates_updated',
        'dates_unchanged',
        'dates_removed',
        'criteria_total',
        'schedule_total',
        'confidence',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      int count(String key, int maximum) {
        final count = value[key];
        if (count is! int || count < 0 || count > maximum) {
          throw const FormatException();
        }
        return count;
      }

      if (value['course_id'] != courseId ||
          value['term'] != term ||
          value['source_id'] != sourceId ||
          !const {
            'created',
            'updated',
            'unchanged',
            'not_published',
          }.contains(value['plan']) ||
          value['confidence'] != 'authoritative') {
        throw const FormatException();
      }
      count('dates_unchanged', 100);
      return PythonTeachingPlanImport(
        notPublished: value['plan'] == 'not_published',
        assessmentTotal: count('assessment_total', 100),
        undatedAssessmentTotal: count('undated_assessment_total', 100),
        criteriaTotal: count('criteria_total', 100),
        scheduleTotal: count('schedule_total', 1000),
        createdDates: count('dates_created', 100),
        updatedDates: count('dates_updated', 100),
        removedDates: count('dates_removed', 100),
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  Future<PythonTeachingPlanReconciliation> reconcileMoodleTeachingPlan({
    required String courseId,
    required bool apply,
  }) async {
    _validateCourseId(courseId);
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/reconcile/teaching-plan',
      method: _BackendMethod.post,
      body: {'course_id': courseId, 'apply': apply},
    );
    try {
      final value = jsonDecode(response.body);
      const keys = {
        'course_id',
        'mode',
        'matched',
        'missing',
        'conflicting',
        'assessments_linked',
        'assessment_conflicts',
        'outside_schedule',
        'workload_validation',
        'applied',
        'changes',
        'excluded',
        'conflicts',
      };
      if (value is! Map<String, dynamic> || !_hasExactKeys(value, keys)) {
        throw const FormatException();
      }
      int count(String key) {
        final result = value[key];
        if (result is! int || result < 0 || result > 450) {
          throw const FormatException();
        }
        return result;
      }

      final mode = value['mode'];
      final conflicts = value['conflicts'];
      final changes = value['changes'];
      final excluded = value['excluded'];
      final workloadValidation = value['workload_validation'];
      if (value['course_id'] != courseId ||
          mode != (apply ? 'applied' : 'preview') ||
          conflicts is! List ||
          conflicts.length != count('conflicting') ||
          changes is! List ||
          excluded is! List) {
        throw const FormatException();
      }
      List<PythonTeachingPlanChange> decodeChanges(List<Object?> values) =>
          values
              .map(
                (item) => PythonTeachingPlanChange.fromJson(
                  Map<String, Object?>.from(item as Map),
                ),
              )
              .toList(growable: false);
      final decodedChanges = decodeChanges(changes.cast<Object?>());
      final decodedExcluded = decodeChanges(excluded.cast<Object?>());
      final outsideChanges = decodedChanges
          .where((change) => change.action == 'remove_session')
          .length;
      if (decodedExcluded.length + outsideChanges !=
              count('outside_schedule') ||
          workloadValidation != null && workloadValidation is! Map) {
        throw const FormatException();
      }
      return PythonTeachingPlanReconciliation(
        mode: mode as String,
        matched: count('matched'),
        missing: count('missing'),
        conflicting: count('conflicting'),
        assessmentsLinked: count('assessments_linked'),
        assessmentConflicts: count('assessment_conflicts'),
        outsideSchedule: count('outside_schedule'),
        applied: count('applied'),
        changes: decodedChanges,
        excluded: decodedExcluded,
        workloadValidation: workloadValidation == null
            ? null
            : PythonWorkloadValidation.fromJson(
                Map<String, Object?>.from(workloadValidation as Map),
              ),
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
      return _sigaSyncResult(jsonDecode(response.body));
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  PythonUFMGSigaSyncResult _sigaSyncResult(Object? raw) {
    final value = raw;
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
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncAllAcademicData({
    String? progressId,
  }) async {
    final response = await _authenticatedRequest(
      path: '/v1/ufmg/sync/all',
      method: _BackendMethod.post,
      body: {'progress_id': ?progressId},
      requestTimeout: longRunningTimeout,
    );
    try {
      final value = Map<String, Object?>.from(jsonDecode(response.body) as Map);
      if (!_hasExactKeys(value, const {
        'siga',
        'moodle',
        'teaching_plans',
        'exceptions',
      })) {
        throw const FormatException();
      }
      final summary = Map<String, Object?>.from(
        value['teaching_plans']! as Map,
      );
      if (!_hasExactKeys(summary, const {
        'available',
        'imported',
        'applied',
        'unchanged',
        'review_required',
      })) {
        throw const FormatException();
      }
      int count(String key, {int maximum = 500}) {
        final result = summary[key];
        if (result is! int || result < 0 || result > maximum) {
          throw const FormatException();
        }
        return result;
      }

      final available = count('available', maximum: 50);
      final imported = count('imported', maximum: 50);
      final applied = count('applied');
      final unchanged = count('unchanged', maximum: 50);
      final reviewRequired = count('review_required', maximum: 50);
      if (imported > available ||
          unchanged + reviewRequired > available ||
          reviewRequired > imported + (available - imported)) {
        throw const FormatException();
      }
      final rawExceptions = value['exceptions'];
      if (rawExceptions is! List ||
          rawExceptions.length > 50 ||
          rawExceptions.length != reviewRequired) {
        throw const FormatException();
      }
      final exceptions = rawExceptions
          .map((rawException) {
            final item = Map<String, Object?>.from(rawException as Map);
            if (!_hasExactKeys(item, const {
              'course_id',
              'course_code',
              'reason',
              'candidate_count',
              'changes',
              'conflicting',
              'assessment_conflicts',
            })) {
              throw const FormatException();
            }
            final courseId = item['course_id'];
            final courseCode = item['course_code'];
            final reason = item['reason'];
            final candidateCount = item['candidate_count'];
            final conflicting = item['conflicting'];
            final assessmentConflicts = item['assessment_conflicts'];
            final rawChanges = item['changes'];
            if (courseId is! String ||
                courseId.isEmpty ||
                courseCode is! String ||
                courseCode.isEmpty ||
                reason is! String ||
                !{
                  'ambiguous_teaching_plan',
                  'reconciliation_conflict',
                  'teaching_plan_unavailable',
                  'teaching_plan_not_published',
                }.contains(reason) ||
                candidateCount is! int ||
                candidateCount < 1 ||
                candidateCount > 20 ||
                conflicting is! int ||
                conflicting < 0 ||
                conflicting > 500 ||
                assessmentConflicts is! int ||
                assessmentConflicts < 0 ||
                assessmentConflicts > 500 ||
                rawChanges is! List ||
                rawChanges.length > 20) {
              throw const FormatException();
            }
            final changes = rawChanges
                .map(
                  (change) => PythonTeachingPlanChange.fromJson(
                    Map<String, Object?>.from(change as Map),
                  ),
                )
                .toList(growable: false);
            if (reason == 'ambiguous_teaching_plan' &&
                    (candidateCount < 2 ||
                        conflicting != 0 ||
                        assessmentConflicts != 0 ||
                        changes.isNotEmpty) ||
                reason == 'reconciliation_conflict' &&
                    (candidateCount != 1 ||
                        conflicting + assessmentConflicts == 0) ||
                (reason == 'teaching_plan_unavailable' ||
                        reason == 'teaching_plan_not_published') &&
                    (candidateCount != 1 ||
                        conflicting != 0 ||
                        assessmentConflicts != 0 ||
                        changes.isNotEmpty)) {
              throw const FormatException();
            }
            return PythonAcademicSyncException(
              courseId: courseId,
              courseCode: courseCode,
              reason: reason,
              candidateCount: candidateCount,
              changes: changes,
              conflicting: conflicting,
              assessmentConflicts: assessmentConflicts,
            );
          })
          .toList(growable: false);
      return PythonUnifiedAcademicSyncResult(
        siga: _sigaSyncResult(value['siga']),
        moodle: _moodleSyncResult(value['moodle']),
        teachingPlans: PythonTeachingPlanSyncSummary(
          available: available,
          imported: imported,
          applied: applied,
          unchanged: unchanged,
          reviewRequired: reviewRequired,
        ),
        exceptions: exceptions,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonOfficialCalendarPreview> previewOfficialCalendar() async {
    final response = await _authenticatedRequest(
      path: '/v1/calendar/official/preview',
      method: _BackendMethod.post,
      body: const {},
      requestTimeout: longRunningTimeout,
    );
    try {
      final value = Map<String, Object?>.from(jsonDecode(response.body) as Map);
      if (!_hasExactKeys(value, const {'candidates', 'counts'})) {
        throw const FormatException();
      }
      final raw = value['candidates'];
      if (raw is! List || raw.length > 100) throw const FormatException();
      final candidates = raw
          .map((entry) {
            final item = Map<String, Object?>.from(entry as Map);
            if (!_hasExactKeys(item, const {
                  'course_id',
                  'course_code',
                  'session_id',
                  'date',
                  'starts_at',
                  'ends_at',
                  'events',
                  'from',
                  'to',
                }) ||
                item['from'] != 'scheduled' ||
                item['to'] != 'holiday') {
              throw const FormatException();
            }
            final events = item['events'];
            if (events is! List || events.isEmpty || events.length > 10) {
              throw const FormatException();
            }
            final event = Map<String, Object?>.from(events.first as Map);
            if (!_hasExactKeys(event, const {
                  'title',
                  'source_url',
                  'confidence',
                }) ||
                event['confidence'] != 'official') {
              throw const FormatException();
            }
            final courseId = item['course_id'];
            final courseCode = item['course_code'];
            final sessionId = item['session_id'];
            final title = event['title'];
            if (courseId is! String ||
                courseId.isEmpty ||
                courseCode is! String ||
                courseCode.isEmpty ||
                sessionId is! String ||
                sessionId.isEmpty ||
                title is! String ||
                title.isEmpty) {
              throw const FormatException();
            }
            return PythonOfficialCalendarChange(
              courseId: courseId,
              courseCode: courseCode,
              sessionId: sessionId,
              date: DateTime.parse(item['date']! as String),
              startsAt: _utcDate(item['starts_at']),
              endsAt: _utcDate(item['ends_at']),
              eventTitle: title,
            );
          })
          .toList(growable: false);
      return PythonOfficialCalendarPreview(candidates: candidates);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonOfficialCalendarApplyResult> applyOfficialCalendar(
    List<PythonOfficialCalendarChange> changes,
  ) async {
    final response = await _authenticatedRequest(
      path: '/v1/calendar/official/apply',
      method: _BackendMethod.post,
      body: {
        'changes': [
          for (final change in changes)
            {'course_id': change.courseId, 'session_id': change.sessionId},
        ],
      },
      requestTimeout: longRunningTimeout,
    );
    try {
      final value = Map<String, Object?>.from(jsonDecode(response.body) as Map);
      if (!_hasExactKeys(value, const {'applied', 'skipped'})) {
        throw const FormatException();
      }
      final applied = value['applied'];
      final skipped = value['skipped'];
      if (applied is! int ||
          applied < 0 ||
          applied > 100 ||
          skipped is! int ||
          skipped < 0 ||
          skipped > 100) {
        throw const FormatException();
      }
      return PythonOfficialCalendarApplyResult(
        applied: applied,
        skipped: skipped,
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
    Duration? requestTimeout,
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
        requestTimeout: requestTimeout ?? timeout,
      );
      final error = _errorCode(response);
      if (response.statusCode == 200) return response;
      if (attempt == 0 && error == 'unauthorized') {
        forceIdentityRefresh = true;
        continue;
      }
      if (attempt == 0 && error == 'app_check_replayed') continue;
      final failure = _exceptionFor(
        response.statusCode,
        error,
        response.headers,
        destructiveSessions: _destructiveSessions(response),
      );
      throw PythonBackendException(
        failure.code,
        retryAfter: failure.retryAfter,
        destructiveSessions: failure.destructiveSessions,
        credential: failure.credential,
        causeType: failure.causeType,
        requestContext:
            'stage=http_response method=${method.name} path=$path '
            'status=${response.statusCode} backend_error=$error '
            'request_id=$requestId server_request_id=${response.headers['x-request-id'] ?? 'absent'} '
            'attempt=${attempt + 1}',
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
    required Duration requestTimeout,
  }) async {
    try {
      return await _request(
        forceIdentityRefresh: forceIdentityRefresh,
        requestId: requestId,
        path: path,
        method: method,
        body: body,
        requestTimeout: requestTimeout,
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
        requestTimeout: requestTimeout,
      );
    }
  }

  Future<http.Response> _request({
    required bool forceIdentityRefresh,
    required String requestId,
    required String path,
    required _BackendMethod method,
    required Map<String, Object?>? body,
    required Duration requestTimeout,
  }) async {
    final elapsed = Stopwatch()..start();
    var stage = 'credentials';
    try {
      final (idToken, appCheckToken) = await _credentials(
        forceIdentityRefresh: forceIdentityRefresh,
        limitedUseAppCheck:
            method != _BackendMethod.get &&
            !(method == _BackendMethod.post &&
                path == '/v1/ufmg/moodle/material-files'),
      );
      final headers = {
        'Authorization': 'Bearer $idToken',
        'X-Firebase-AppCheck': appCheckToken,
        'X-Request-ID': requestId,
      };
      final uri = _endpoint.resolve(path);
      stage = 'transport';
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
      return await request.timeout(requestTimeout);
    } on PythonBackendException catch (error) {
      throw PythonBackendException(
        error.code,
        credential: error.credential,
        causeType: error.causeType,
        credentialDetails: error.credentialDetails,
        requestContext:
            'stage=$stage method=${method.name} path=$path '
            'request_id=$requestId elapsed_ms=${elapsed.elapsedMilliseconds}',
      );
    } on TimeoutException {
      throw PythonBackendException(
        PythonBackendError.timeout,
        causeType: 'TimeoutException',
        requestContext:
            'stage=$stage method=${method.name} path=$path '
            'request_id=$requestId elapsed_ms=${elapsed.elapsedMilliseconds} '
            'timeout_ms=${requestTimeout.inMilliseconds}',
      );
    } catch (error) {
      throw PythonBackendException(
        PythonBackendError.unavailable,
        causeType: error.runtimeType.toString(),
        requestContext:
            'stage=$stage method=${method.name} path=$path '
            'request_id=$requestId elapsed_ms=${elapsed.elapsedMilliseconds} '
            'cause=${sanitizeLogText(error.toString())}',
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
        credentialDetails: _credentialDiagnostics(error),
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
        credentialDetails: _credentialDiagnostics(error),
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
