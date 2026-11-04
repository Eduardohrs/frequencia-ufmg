import '../../backend/python_backend_transport.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';

/// Actionable results only; successful counters belong in telemetry.
class AcademicSyncIssue {
  const AcademicSyncIssue(
    this.courseId,
    this.courseCode,
    this.stage,
    this.reason, {
    this.changes = const [],
  });
  final List<PythonTeachingPlanChange> changes;
  final String courseId, courseCode, stage, reason;
}

List<AcademicSyncIssue> moodleSyncIssues(PythonMoodleSyncResult result) => [
  for (final course in result.dates.failedCourses)
    AcademicSyncIssue(
      '${course['course_id'] ?? ''}',
      '${course['course_code'] ?? ''}',
      'dates',
      '${course['reason'] ?? 'update_failed'}',
    ),
  for (final course
      in result.activitySnapshots?.failedCourses ??
          const <Map<String, Object?>>[])
    AcademicSyncIssue(
      '${course['course_id'] ?? ''}',
      '${course['course_code'] ?? ''}',
      'activities',
      '${course['reason'] ?? 'update_failed'}',
    ),
  if (result.activitySnapshots case final activity?
      when activity.failed > 0 && activity.failedCourses.isEmpty)
    const AcademicSyncIssue('', '', 'activities', 'update_failed'),
];
List<AcademicSyncIssue> unifiedSyncIssues(
  PythonUnifiedAcademicSyncResult result,
) => [
  ...moodleSyncIssues(result.moodle),
  for (final issue in result.exceptions)
    if (issue.reason != 'teaching_plan_not_published')
      AcademicSyncIssue(
        issue.courseId,
        issue.courseCode,
        'teaching_plan',
        issue.reason,
        changes: issue.changes,
      ),
  if (result.siga.schedules.conflicts > 0 ||
      result.siga.schedules.missingCourses > 0)
    const AcademicSyncIssue('', '', 'schedule', 'schedule_review'),
  if (result.moodle.dates.unmatched > 0)
    const AcademicSyncIssue('', '', 'dates', 'unmatched_dates'),
];
Map<String, Object> sigaSyncDetails(PythonUFMGSigaSyncResult result) => {
  'courses_created': result.courses.created,
  'courses_existing': result.courses.existing,
  'courses_total': result.courses.total,
  'schedules_updated': result.schedules.updated,
  'schedules_unchanged': result.schedules.unchanged,
  'schedule_conflicts': result.schedules.conflicts,
  'courses_missing': result.schedules.missingCourses,
  'meetings_imported': result.schedules.meetingsImported,
};
Map<String, Object> moodleSyncDetails(PythonMoodleSyncResult result) => {
  'dates_created': result.dates.created,
  'dates_updated': result.dates.updated,
  'dates_unchanged': result.dates.unchanged,
  'dates_unmatched': result.dates.unmatched,
  'dates_removed': result.dates.removed,
  'dates_failed': result.dates.failed,
  'materials_found': result.candidateTotal,
  'activities_updated': result.activitySnapshots?.updated ?? 0,
  'activities_reused': result.activitySnapshots?.reused ?? 0,
  'activities_failed': result.activitySnapshots?.failed ?? 0,
  'download_capability': result.capabilities == null
      ? 'unknown'
      : result.capabilities!.directDownloadSupported
      ? 'available'
      : 'unavailable',
};
void logSyncFeedback(
  AppLogger logger,
  String source,
  Map<String, Object> counts,
  List<AcademicSyncIssue> issues, {
  String? operationId,
}) {
  final id = operationId ?? newCorrelationId('sync_feedback');
  emitOperationalEvent(logger, 'academic_sync_result_details', {
    'operation_id': id,
    'stage': 'result',
    'source': source,
    ...counts,
    'issue_count': issues.length,
  });
  for (final issue in issues) {
    emitOperationalEvent(logger, 'academic_sync_course_issue', {
      'operation_id': id,
      'stage': issue.stage,
      'source': source,
      'course_id': issue.courseId,
      'course_code': issue.courseCode,
      'reason': issue.reason,
    });
  }
}
