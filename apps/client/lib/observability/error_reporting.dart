import 'dart:async';

import 'package:flutter/foundation.dart';

import 'app_logger.dart';

void configureErrorReporting(
  AppLogger logger, {
  void Function(FlutterErrorDetails)? presentError,
}) {
  final presenter = presentError ?? FlutterError.presentError;
  FlutterError.onError = (details) {
    presenter(details);
    unawaited(
      logger.recordError(
        details.exception,
        details.stack ?? StackTrace.current,
        context: 'flutter_framework',
        fatal: true,
      ),
    );
  };
  PlatformDispatcher.instance.onError = (error, stackTrace) {
    unawaited(
      logger.recordError(
        error,
        stackTrace,
        context: 'uncaught_async',
        fatal: true,
      ),
    );
    return true;
  };
}
