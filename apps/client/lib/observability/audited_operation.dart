import 'app_logger.dart';

enum AuditedOperation {
  googleSignIn('auth_google_sign_in'),
  logout('auth_logout');

  const AuditedOperation(this.eventPrefix);

  final String eventPrefix;
}

Future<void> runAuditedOperation({
  required AppLogger logger,
  required AuditedOperation operation,
  required Future<void> Function() action,
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
    await action();
    await logger.logEvent(
      '${eventPrefix}_succeeded',
      parameters: {
        'operation': eventPrefix,
        'operation_id': operationId,
        'outcome': 'succeeded',
      },
    );
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
