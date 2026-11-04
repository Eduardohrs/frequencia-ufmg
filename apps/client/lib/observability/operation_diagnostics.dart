import 'dart:async';
import 'dart:convert';

import 'app_logger.dart';
import 'error_log_details.dart';

void _deliver(Future<void> delivery) =>
    unawaited(delivery.catchError((Object _) {}));

void emitOperationalEvent(
  AppLogger logger,
  String event,
  Map<String, Object> fields,
) => _deliver(
  Future<void>.sync(
    () => logger.logEvent(
      event,
      parameters: {...fields, 'details': _operationalDetails(fields)},
    ),
  ),
);

void recordOperationalFailure(
  AppLogger logger,
  Object error,
  StackTrace stack,
  String context,
  Map<String, Object> fields, {
  required String failureCode,
}) => _deliver(
  Future<void>.sync(
    () => logger.recordError(
      _OperationalFailure(error, fields, failureCode),
      stack,
      context: context,
      parameters: fields,
    ),
  ),
);

String _operationalDetails(Map<String, Object> fields) {
  final details = Map<String, Object>.of(fields)
    ..remove('operation_id')
    ..remove('duration_ms')
    ..remove('screen');
  return sanitizeDiagnosticDetails(jsonEncode(details))!;
}

final class _OperationalFailure implements StructuredAppError {
  _OperationalFailure(this.cause, Map<String, Object> fields, this.logCode)
    : fields = Map.unmodifiable(fields);
  final Object cause;
  final Map<String, Object> fields;
  @override
  final String logCode;
  @override
  String? get logMessage => ErrorLogDetails.from(cause).message;
  @override
  String get logDetails {
    final error = ErrorLogDetails.from(cause);
    return _operationalDetails({
      ...fields,
      'cause_type': error.type,
      'cause_code': ?error.code,
      'cause_details': ?error.details,
    });
  }
}
