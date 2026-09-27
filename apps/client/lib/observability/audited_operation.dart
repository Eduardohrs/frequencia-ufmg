import 'app_logger.dart';

enum AuditedOperation {
  googleSignIn('auth_google_sign_in'),
  logout('auth_logout'),
  courseList('firestore_course_list'),
  courseSave('firestore_course_save'),
  courseDelete('firestore_course_delete'),
  meetingList('firestore_meeting_list'),
  meetingSave('firestore_meeting_save'),
  meetingDelete('firestore_meeting_delete'),
  sessionList('firestore_session_list'),
  sessionSave('firestore_session_save'),
  sessionDelete('firestore_session_delete');

  const AuditedOperation(this.eventPrefix);

  final String eventPrefix;
}

Future<T> runAuditedOperation<T>({
  required AppLogger logger,
  required AuditedOperation operation,
  required Future<T> Function() action,
}) async {
  final eventPrefix = operation.eventPrefix;
  final operationId =
      '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-${operation.name}';
  await logger.logEvent(
    '${eventPrefix}_started',
    parameters: {
      'operation': eventPrefix,
      'operation_id': operationId,
      'outcome': 'started',
    },
  );
  try {
    final result = await action();
    await logger.logEvent(
      '${eventPrefix}_succeeded',
      parameters: {
        'operation': eventPrefix,
        'operation_id': operationId,
        'outcome': 'succeeded',
      },
    );
    return result;
  } catch (error, stackTrace) {
    await logger.recordError(
      error,
      stackTrace,
      context: eventPrefix,
      parameters: {'operation_id': operationId},
    );
    await logger.logEvent(
      '${eventPrefix}_failed',
      parameters: {
        'operation': eventPrefix,
        'operation_id': operationId,
        'outcome': 'failed',
      },
    );
    rethrow;
  }
}
