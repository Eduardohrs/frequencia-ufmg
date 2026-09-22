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
  await logger.logEvent(
    '${eventPrefix}_started',
    parameters: {'operation': eventPrefix, 'outcome': 'started'},
  );
  try {
    await action();
    await logger.logEvent(
      '${eventPrefix}_succeeded',
      parameters: {'operation': eventPrefix, 'outcome': 'succeeded'},
    );
  } catch (error, stackTrace) {
    await logger.recordError(error, stackTrace, context: eventPrefix);
    await logger.logEvent(
      '${eventPrefix}_failed',
      parameters: {'operation': eventPrefix, 'outcome': 'failed'},
    );
    rethrow;
  }
}
