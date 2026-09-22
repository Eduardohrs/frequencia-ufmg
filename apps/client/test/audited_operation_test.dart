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
      expect(logger.parameters[0]!['operation'], operation.eventPrefix);
      expect(logger.parameters[0]!['outcome'], 'started');
      expect(logger.parameters[0]!['operation_id'], isNotEmpty);
      expect(logger.parameters[1]!['operation'], operation.eventPrefix);
      expect(logger.parameters[1]!['outcome'], 'succeeded');
      expect(
        logger.parameters[1]!['operation_id'],
        logger.parameters[0]!['operation_id'],
      );
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
      expect(logger.parameters[0]!['operation'], operation.eventPrefix);
      expect(logger.parameters[0]!['outcome'], 'started');
      expect(logger.parameters[0]!['operation_id'], isNotEmpty);
      expect(logger.parameters[1]!['operation'], operation.eventPrefix);
      expect(logger.parameters[1]!['outcome'], 'failed');
      expect(
        logger.parameters[1]!['operation_id'],
        logger.parameters[0]!['operation_id'],
      );
      expect(logger.errorContexts, [operation.eventPrefix]);
      expect(logger.errorParameters, [
        {'operation_id': logger.parameters[0]!['operation_id']},
      ]);
    });
  }
}

class _FakeAppLogger implements AppLogger {
  final events = <String>[];
  final parameters = <Map<String, Object>?>[];
  final errorContexts = <String>[];
  final errorParameters = <Map<String, Object>?>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
    this.parameters.add(parameters);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
    errorParameters.add(parameters);
  }
}
