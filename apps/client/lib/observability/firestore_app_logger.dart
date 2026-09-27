import 'app_logger.dart';
import 'error_log_details.dart';
import 'operational_log_store.dart';

typedef CurrentUserId = String? Function();
typedef CurrentTime = DateTime Function();
typedef CorrelationId = String Function();

final class FirestoreAppLogger implements AppLogger {
  FirestoreAppLogger({
    required OperationalLogStore store,
    required CurrentUserId currentUserId,
    required String platform,
    CurrentTime? now,
    CorrelationId? correlationId,
  }) : _store = store,
       _currentUserId = currentUserId,
       _platform = platform,
       _now = now ?? DateTime.now,
       _correlationId = correlationId ?? _newCorrelationId;

  final OperationalLogStore _store;
  final CurrentUserId _currentUserId;
  final String _platform;
  final CurrentTime _now;
  final CorrelationId _correlationId;
  String? _lastUserId;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    final userId = _userId();
    if (userId == null) return;
    final timestamp = _now().toUtc();
    await _store.add(
      userId,
      _document(
        timestamp: timestamp,
        level: 'info',
        event: name,
        correlationId:
            _stringParameter(parameters, 'operation_id') ??
            _stringParameter(parameters, 'error_id') ??
            _correlationId(),
        operation: _stringParameter(parameters, 'operation'),
        outcome: _stringParameter(parameters, 'outcome'),
        durationMs: _integerParameter(parameters, 'duration_ms'),
      ),
    );
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    final userId = _userId();
    if (userId == null) return;
    final timestamp = _now().toUtc();
    final details = ErrorLogDetails.from(error);
    await _store.add(
      userId,
      _document(
        timestamp: timestamp,
        level: 'error',
        event: 'app_exception',
        correlationId:
            _stringParameter(parameters, 'operation_id') ??
            _stringParameter(parameters, 'error_id') ??
            _correlationId(),
        operation: context,
        outcome: 'failed',
        durationMs: _integerParameter(parameters, 'duration_ms'),
        errorType: details.type,
        errorCode: details.code,
        errorMessage: details.message,
        errorDetails: details.details,
        fatal: fatal,
      ),
    );
  }

  String? _userId() {
    final current = _currentUserId();
    if (current != null) _lastUserId = current;
    return current ?? _lastUserId;
  }

  Map<String, Object?> _document({
    required DateTime timestamp,
    required String level,
    required String event,
    required String correlationId,
    String? operation,
    String? outcome,
    int? durationMs,
    String? errorType,
    String? errorCode,
    String? errorMessage,
    String? errorDetails,
    bool fatal = false,
  }) => {
    'schemaVersion': 1,
    'occurredAt': timestamp,
    'expiresAt': timestamp.add(const Duration(days: 30)),
    'level': level,
    'event': _safe(event, 80),
    'entryPoint': 'client',
    'platform': _safe(_platform, 16),
    'correlationId': _safe(correlationId, 128),
    'operation': _safeNullable(operation, 80),
    'outcome': _safeNullable(outcome, 24),
    'durationMs': durationMs,
    'errorType': _safeNullable(errorType, 120),
    'errorCode': _safeNullable(errorCode, 120),
    'errorMessage': _safeNullable(errorMessage, 500),
    'errorDetails': _safeNullable(errorDetails, 500),
    'fatal': fatal,
  };
}

String? _stringParameter(Map<String, Object>? parameters, String key) {
  final value = parameters?[key];
  return value is String ? value : null;
}

int? _integerParameter(Map<String, Object>? parameters, String key) {
  final value = parameters?[key];
  return value is int && value >= 0 ? value : null;
}

String _safe(String value, int maximumLength) {
  final sanitized = sanitizeLogText(value) ?? '';
  return sanitized.length <= maximumLength
      ? sanitized
      : sanitized.substring(0, maximumLength);
}

String? _safeNullable(String? value, int maximumLength) =>
    value == null ? null : _safe(value, maximumLength);

String _newCorrelationId() =>
    '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-client';
