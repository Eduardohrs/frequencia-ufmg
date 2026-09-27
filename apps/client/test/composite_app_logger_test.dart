import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/composite_app_logger.dart';

void main() {
  test('delivers events to every configured sink', () async {
    final first = _RecordingLogger();
    final second = _RecordingLogger();
    final logger = CompositeAppLogger([first, second]);

    await logger.logEvent('course_saved', parameters: {'outcome': 'success'});

    expect(first.events, ['course_saved']);
    expect(second.events, ['course_saved']);
  });

  test('attempts every sink when one delivery fails', () async {
    final healthy = _RecordingLogger();
    final logger = CompositeAppLogger([_FailingLogger(), healthy]);

    await expectLater(
      logger.recordError(
        StateError('save failed'),
        StackTrace.current,
        context: 'course_save',
      ),
      throwsStateError,
    );

    expect(healthy.errorContexts, ['course_save']);
  });
}

final class _RecordingLogger implements AppLogger {
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
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
  }
}

final class _FailingLogger implements AppLogger {
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) =>
      Future.error(StateError('sink unavailable'));

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) => Future.error(StateError('sink unavailable'));
}
