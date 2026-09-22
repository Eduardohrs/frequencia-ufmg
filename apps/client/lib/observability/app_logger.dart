abstract interface class AppLogger {
  Future<void> logEvent(String name, {Map<String, Object>? parameters});

  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
  });
}
