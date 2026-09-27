import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'app_logger.dart';
import 'error_log_details.dart';

typedef LogFailureSink = void Function(String message);

/// Keeps telemetry failures from becoming application failures.
final class ResilientAppLogger implements AppLogger {
  ResilientAppLogger(
    this._delegate, {
    Duration deliveryTimeout = const Duration(seconds: 5),
    LogFailureSink? failureSink,
  }) : _deliveryTimeout = deliveryTimeout,
       _failureSink = failureSink ?? debugPrint;

  final AppLogger _delegate;
  final Duration _deliveryTimeout;
  final LogFailureSink _failureSink;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    _schedule(
      () => _delegate.logEvent(name, parameters: parameters),
      kind: 'event',
      target: name,
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
    _schedule(
      () => _delegate.recordError(
        error,
        stackTrace,
        context: context,
        fatal: fatal,
        parameters: parameters,
      ),
      kind: 'error',
      target: context,
    );
  }

  void _schedule(
    Future<void> Function() send, {
    required String kind,
    required String target,
  }) {
    try {
      unawaited(
        send().timeout(_deliveryTimeout).catchError((Object error) {
          _reportFailure(error, kind: kind, target: target);
        }),
      );
    } catch (error) {
      _reportFailure(error, kind: kind, target: target);
    }
  }

  void _reportFailure(
    Object error, {
    required String kind,
    required String target,
  }) {
    final details = ErrorLogDetails.from(error);
    _failureSink(
      jsonEncode({
        'event': 'observability_delivery_failed',
        'log_kind': kind,
        'target': target,
        'error_type': details.type,
        if (details.code != null) 'error_code': details.code,
        if (details.message != null) 'error_message': details.message,
        'occurred_at': DateTime.now().toUtc().toIso8601String(),
      }),
    );
  }
}
