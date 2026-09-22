// This is an integration boundary over Firebase SDKs. Application behavior is
// tested through AppLogger fakes; delivery is smoke-tested against Firebase.
// coverage:ignore-file

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';

import 'app_logger.dart';

class FirebaseAppLogger implements AppLogger {
  FirebaseAppLogger()
    : _analytics = FirebaseAnalytics.instance,
      _crashlytics = kIsWeb ? null : FirebaseCrashlytics.instance;

  final FirebaseAnalytics _analytics;
  final FirebaseCrashlytics? _crashlytics;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    await _analytics.logEvent(name: name, parameters: parameters);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
  }) async {
    await _analytics.logEvent(
      name: 'app_exception',
      parameters: {
        'context': context,
        'error_type': error.runtimeType.toString(),
        'fatal': fatal ? 1 : 0,
      },
    );
    await _crashlytics?.recordError(
      error.runtimeType.toString(),
      stackTrace,
      reason: context,
      fatal: fatal,
    );
  }
}
