// This is an integration boundary over Firebase SDKs. Application behavior is
// tested through AppLogger fakes; delivery is smoke-tested against Firebase.
// coverage:ignore-file

import 'dart:convert';

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
    final safeParameters = _sanitizeParameters(parameters);
    await _analytics.logEvent(name: name, parameters: safeParameters);
    await _crashlytics?.log(
      jsonEncode({'event': name, 'parameters': ?safeParameters}),
    );
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    final details = ErrorLogDetails.from(error);
    final safeParameters = _sanitizeParameters(parameters);
    await _analytics.logEvent(
      name: 'app_exception',
      parameters: {
        ...details.analyticsParameters(context: context, fatal: fatal),
        ...?safeParameters,
      },
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
        if (safeParameters != null) 'parameters=${jsonEncode(safeParameters)}',
      ],
      fatal: fatal,
    );
  }
}

Map<String, Object>? _sanitizeParameters(Map<String, Object>? parameters) {
  if (parameters == null) return null;
  return parameters.map(
    (key, value) =>
        MapEntry(key, value is String ? sanitizeLogText(value) ?? '' : value),
  );
}
