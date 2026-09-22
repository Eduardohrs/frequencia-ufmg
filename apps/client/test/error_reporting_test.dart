import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/error_reporting.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('reports Flutter framework and asynchronous errors as fatal', () async {
    final logger = _FakeAppLogger();
    final presented = <FlutterErrorDetails>[];
    final previousFlutterHandler = FlutterError.onError;
    final previousPlatformHandler = PlatformDispatcher.instance.onError;
    addTearDown(() {
      FlutterError.onError = previousFlutterHandler;
      PlatformDispatcher.instance.onError = previousPlatformHandler;
    });

    configureErrorReporting(logger);
    configureErrorReporting(logger, presentError: presented.add);
    final frameworkDetails = FlutterErrorDetails(
      exception: StateError('framework test'),
    );
    FlutterError.onError!(frameworkDetails);
    final handled = PlatformDispatcher.instance.onError!(
      StateError('async test'),
      StackTrace.current,
    );
    await Future<void>.delayed(Duration.zero);

    expect(presented, [frameworkDetails]);
    expect(handled, isTrue);
    expect(logger.contexts, ['flutter_framework', 'uncaught_async']);
    expect(logger.fatalValues, [true, true]);
    expect(logger.parameters[0]!['error_id'], endsWith('-flutter'));
    expect(logger.parameters[1]!['error_id'], endsWith('-async'));
  });
}

class _FakeAppLogger implements AppLogger {
  final contexts = <String>[];
  final fatalValues = <bool>[];
  final parameters = <Map<String, Object>?>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {}

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    contexts.add(context);
    fatalValues.add(fatal);
    this.parameters.add(parameters);
  }
}
