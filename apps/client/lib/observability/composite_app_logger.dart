import 'app_logger.dart';

final class CompositeAppLogger implements AppLogger {
  CompositeAppLogger(Iterable<AppLogger> delegates)
    : _delegates = List.unmodifiable(delegates);

  final List<AppLogger> _delegates;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) =>
      Future.wait(
        _deliveries(
          (delegate) => delegate.logEvent(name, parameters: parameters),
        ),
      );

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) => Future.wait(
    _deliveries(
      (delegate) => delegate.recordError(
        error,
        stackTrace,
        context: context,
        fatal: fatal,
        parameters: parameters,
      ),
    ),
  );

  List<Future<void>> _deliveries(
    Future<void> Function(AppLogger delegate) deliver,
  ) => [
    for (final delegate in _delegates)
      Future<void>.sync(() => deliver(delegate)),
  ];
}
