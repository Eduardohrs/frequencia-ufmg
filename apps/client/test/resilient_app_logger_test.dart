import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/resilient_app_logger.dart';

void main() {
  test('returns immediately while event delivery is pending', () async {
    final delegate = _ControllableLogger();
    final logger = ResilientAppLogger(delegate);

    await logger.logEvent('course_save');

    expect(delegate.eventCalls, 1);
    expect(delegate.eventDelivery.isCompleted, isFalse);
  });

  test(
    'reports an event delivery failure without sensitive parameters',
    () async {
      final messages = <String>[];
      final logger = ResilientAppLogger(
        _FailingLogger(),
        failureSink: messages.add,
      );

      await logger.logEvent(
        'course_save',
        parameters: {'secret': 'must-not-leak'},
      );
      await Future<void>.delayed(Duration.zero);

      final failure = jsonDecode(messages.single) as Map<String, dynamic>;
      expect(failure['event'], 'observability_delivery_failed');
      expect(failure['log_kind'], 'event');
      expect(failure['target'], 'course_save');
      expect(failure['error_type'], 'StateError');
      expect(messages.single, isNot(contains('must-not-leak')));
    },
  );

  test('reports a timeout when logging never completes', () async {
    final messages = <String>[];
    final logger = ResilientAppLogger(
      _ControllableLogger(),
      deliveryTimeout: Duration.zero,
      failureSink: messages.add,
    );

    await logger.recordError(
      StateError('business failure'),
      StackTrace.current,
      context: 'course_save',
    );
    await Future<void>.delayed(Duration.zero);

    final failure = jsonDecode(messages.single) as Map<String, dynamic>;
    expect(failure['log_kind'], 'error');
    expect(failure['target'], 'course_save');
    expect(failure['error_type'], 'TimeoutException');
  });

  test('identifies which transport timed out', () async {
    final messages = <String>[];
    final logger = ResilientAppLogger(
      _ControllableLogger(),
      transport: 'firebase_analytics',
      deliveryTimeout: Duration.zero,
      failureSink: messages.add,
    );

    await logger.logEvent('app_started');
    await Future<void>.delayed(Duration.zero);

    final failure = jsonDecode(messages.single) as Map<String, dynamic>;
    expect(failure['transport'], 'firebase_analytics');
    expect(failure['target'], 'app_started');
  });

  test('reports a logger that throws before returning a future', () async {
    final messages = <String>[];
    final logger = ResilientAppLogger(
      _SynchronouslyFailingLogger(),
      failureSink: messages.add,
    );

    await logger.logEvent('course_save');

    final failure = jsonDecode(messages.single) as Map<String, dynamic>;
    expect(failure['target'], 'course_save');
    expect(failure['error_type'], 'StateError');
  });
}

final class _ControllableLogger implements AppLogger {
  final eventDelivery = Completer<void>();
  final errorDelivery = Completer<void>();
  var eventCalls = 0;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) {
    eventCalls++;
    return eventDelivery.future;
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) => errorDelivery.future;
}

final class _FailingLogger implements AppLogger {
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) =>
      Future<void>.error(StateError('analytics unavailable'));

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) => Future<void>.error(StateError('crash reporting unavailable'));
}

final class _SynchronouslyFailingLogger implements AppLogger {
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) {
    throw StateError('synchronous logger failure');
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) {
    throw StateError('synchronous logger failure');
  }
}
