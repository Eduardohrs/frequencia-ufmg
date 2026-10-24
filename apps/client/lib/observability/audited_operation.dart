import 'dart:async';

import 'app_logger.dart';

final Object _operationIdZoneKey = Object();
int _correlationSequence = 0;

String? get currentOperationId => Zone.current[_operationIdZoneKey] as String?;

String newCorrelationId(String label) {
  final sequence = _correlationSequence++;
  return '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${sequence.toRadixString(36)}-$label';
}

enum AuditedOperation {
  googleSignIn('auth_google_sign_in'),
  logout('auth_logout'),
  courseList('firestore_course_list'),
  courseCreate('course_create'),
  courseUpdate('course_update'),
  courseSave('firestore_course_save'),
  courseDelete('firestore_course_delete'),
  meetingList('firestore_meeting_list'),
  meetingSave('firestore_meeting_save'),
  meetingDelete('firestore_meeting_delete'),
  sessionList('firestore_session_list'),
  sessionSave('firestore_session_save'),
  sessionDelete('firestore_session_delete'),
  sessionGeneration('session_generation'),
  calendarException('calendar_exception'),
  assessmentUpdate('assessment_update'),
  manualAttendance('manual_attendance'),
  academicOverviewLoad('academic_overview_load'),
  academicOverviewFallback('academic_overview_fallback'),
  ufmgSessionStatus('ufmg_session_status'),
  ufmgSessionConnect('ufmg_session_connect'),
  ufmgSessionDisconnect('ufmg_session_disconnect'),
  ufmgCourseImport('ufmg_course_import'),
  ufmgScheduleImport('ufmg_schedule_import'),
  moodleDateImport('moodle_date_import'),
  moodleDateList('moodle_date_list'),
  moodleContentDiscovery('moodle_content_discovery'),
  moodleMaterialCatalogList('moodle_material_catalog_list'),
  moodleMobileCapability('moodle_mobile_capability'),
  moodleSync('moodle_sync'),
  moodleDiarioPlanProbe('moodle_diario_plan_probe'),
  moodleTeachingPlanImport('moodle_teaching_plan_import'),
  moodleTeachingPlanReconciliation('moodle_teaching_plan_reconciliation'),
  moodleMaterialOpen('moodle_material_open'),
  moodleMaterialCacheList('moodle_material_cache_list'),
  moodleMaterialCacheSave('moodle_material_cache_save'),
  moodleMaterialDownloadEnqueue('moodle_material_download_enqueue'),
  moodleMaterialCacheOpen('moodle_material_cache_open'),
  moodleMaterialCacheRemove('moodle_material_cache_remove'),
  moodleMaterialCacheClear('moodle_material_cache_clear'),
  ufmgSync('ufmg_sync');

  const AuditedOperation(this.eventPrefix);

  final String eventPrefix;
}

Future<T> runAuditedOperation<T>({
  required AppLogger logger,
  required AuditedOperation operation,
  required Future<T> Function() action,
}) async {
  final stopwatch = Stopwatch()..start();
  final eventPrefix = operation.eventPrefix;
  final operationId = newCorrelationId(operation.name);
  return runZoned<Future<T>>(() async {
    _deliver(
      logger.logEvent(
        '${eventPrefix}_started',
        parameters: {
          'operation': eventPrefix,
          'operation_id': operationId,
          'outcome': 'started',
        },
      ),
    );
    try {
      final result = await action();
      _deliver(
        logger.logEvent(
          '${eventPrefix}_succeeded',
          parameters: {
            'operation': eventPrefix,
            'operation_id': operationId,
            'outcome': 'succeeded',
            'duration_ms': stopwatch.elapsedMilliseconds,
          },
        ),
      );
      return result;
    } catch (error, stackTrace) {
      final duration = stopwatch.elapsedMilliseconds;
      _deliver(
        logger.recordError(
          error,
          stackTrace,
          context: eventPrefix,
          parameters: {'operation_id': operationId, 'duration_ms': duration},
        ),
      );
      _deliver(
        logger.logEvent(
          '${eventPrefix}_failed',
          parameters: {
            'operation': eventPrefix,
            'operation_id': operationId,
            'outcome': 'failed',
            'duration_ms': duration,
          },
        ),
      );
      rethrow;
    }
  }, zoneValues: {_operationIdZoneKey: operationId});
}

void _deliver(Future<void> delivery) {
  unawaited(delivery.catchError((_) {}));
}
