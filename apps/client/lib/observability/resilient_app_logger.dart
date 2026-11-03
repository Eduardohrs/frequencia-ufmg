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
    this.transport,
    LogFailureSink? failureSink,
  }) : _deliveryTimeout = deliveryTimeout,
       _failureSink = failureSink ?? debugPrint;

  final AppLogger _delegate;
  final String? transport;
  final Duration _deliveryTimeout;
  final LogFailureSink _failureSink;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    _schedule(
      () => _delegate.logEvent(name, parameters: parameters),
      kind: 'event',
      target: name,
      operationId: parameters?['operation_id'],
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
      operationId: parameters?['operation_id'],
    );
  }

  void _schedule(
    Future<void> Function() send, {
    required String kind,
    required String target,
    Object? operationId,
  }) {
    final watch = Stopwatch()..start();
    var overdue = false;
    void report(String event, String status, [Object? error]) {
      final details = error == null ? null : ErrorLogDetails.from(error);
      _failureSink(
        jsonEncode({
          'event': event,
          'delivery_status': status,
          'log_kind': kind,
          'target': target,
          if (transport != null) 'transport': transport,
          if (operationId is String) 'operation_id': operationId,
          'elapsed_ms': watch.elapsedMilliseconds,
          if (details != null) 'error_type': details.type,
          if (details?.code != null) 'error_code': details!.code,
          if (details?.message != null) 'error_message': details!.message,
          'occurred_at': DateTime.now().toUtc().toIso8601String(),
        }),
      );
    }

    // A deadline does not cancel a Firestore write queued by its SDK.
    final timer = Timer(_deliveryTimeout, () {
      overdue = true;
      report('observability_delivery_pending', 'awaiting_transport_ack');
    });
    try {
      unawaited(
        send().then<void>(
          (_) {
            timer.cancel();
            if (overdue) {
              report('observability_delivery_late_succeeded', 'acknowledged');
            }
          },
          onError: (Object error) {
            timer.cancel();
            report('observability_delivery_failed', 'rejected', error);
          },
        ),
      );
    } catch (error) {
      timer.cancel();
      report('observability_delivery_failed', 'rejected', error);
    }
  }
}
