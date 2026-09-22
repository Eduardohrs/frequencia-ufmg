// This is an integration boundary over Firebase SDKs. Application behavior is
// tested through AppLogger fakes; delivery is smoke-tested against Firebase.
// coverage:ignore-file

import 'package:firebase_analytics/firebase_analytics.dart';
import 'package:firebase_crashlytics/firebase_crashlytics.dart';
import 'package:flutter/foundation.dart';

import 'app_logger.dart';
import 'error_log_details.dart';

class FirebaseAppLogger implements AppLogger {
  FirebaseAppLogger()
    : _analytics = FirebaseAnalytics.instance,
      _crashlytics = kIsWeb ? null : FirebaseCrashlytics.instance;

  final FirebaseAnalytics _analytics;
  final FirebaseCrashlytics? _crashlytics;

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    await _analytics.logEvent(name: name, parameters: parameters);
    await _crashlytics?.log(
      'event=$name parameters=${sanitizeLogText(parameters?.toString()) ?? '{}'}',
    );
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
  }) async {
    final details = ErrorLogDetails.from(error);
    await _analytics.logEvent(
      name: 'app_exception',
      parameters: details.analyticsParameters(context: context, fatal: fatal),
    );
    await _crashlytics?.recordError(
      SanitizedAppException(details),
      stackTrace,
      reason: 'context=$context',
      information: [
        'type=${details.type}',
        if (details.code != null) 'code=${details.code}',
        if (details.message != null) 'message=${details.message}',
        if (details.details != null) 'details=${details.details}',
      ],
      fatal: fatal,
    );
  }
}
