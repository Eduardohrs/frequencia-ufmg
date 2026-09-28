import 'dart:async';

import 'app_logger.dart';

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
  sessionGeneration('session_generation');

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
  final operationId =
      '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-${operation.name}';
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
}

void _deliver(Future<void> delivery) {
  unawaited(delivery.catchError((_) {}));
}
