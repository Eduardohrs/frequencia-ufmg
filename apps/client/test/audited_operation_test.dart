import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/audited_operation.dart';

void main() {
  for (final operation in AuditedOperation.values) {
    test('${operation.name} logs its successful lifecycle', () async {
      final logger = _FakeAppLogger();

      await runAuditedOperation(
        logger: logger,
        operation: operation,
        action: () async {},
      );

      expect(logger.events, [
        '${operation.eventPrefix}_started',
        '${operation.eventPrefix}_succeeded',
      ]);
      expect(logger.errorContexts, isEmpty);
    });

    test('${operation.name} logs its failed lifecycle', () async {
      final logger = _FakeAppLogger();

      await expectLater(
        runAuditedOperation(
          logger: logger,
          operation: operation,
          action: () async => throw StateError('test failure'),
        ),
        throwsStateError,
      );

      expect(logger.events, [
        '${operation.eventPrefix}_started',
        '${operation.eventPrefix}_failed',
      ]);
      expect(logger.errorContexts, [operation.eventPrefix]);
    });
  }
}

class _FakeAppLogger implements AppLogger {
  final events = <String>[];
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
  }) async {
    errorContexts.add(context);
  }
}
