// This file is a thin boundary over native/web Firebase plugins and compile-time
// deployment settings. Its behavior is covered through the injected transport.
// coverage:ignore-file

import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import 'python_backend_transport.dart';

const _settings = PythonBackendSettings(
  enabled: bool.fromEnvironment('ENABLE_PYTHON_BACKEND'),
  endpoint: String.fromEnvironment('PYTHON_BACKEND_ORIGIN'),
);
const _webSiteKey = String.fromEnvironment('FIREBASE_APP_CHECK_WEB_SITE_KEY');

BackendIdentityVerifier? createFirebasePythonBackendVerifier() {
  final endpoint = _settings.endpointUri;
  if (endpoint == null) return null;
  return _FirebasePythonBackendVerifier(endpoint);
}

final class _FirebasePythonBackendVerifier
    implements BackendIdentityVerifier, BackendAttendanceEvaluator {
  _FirebasePythonBackendVerifier(Uri endpoint)
    : _transport = PythonBackendTransport(
        endpoint: endpoint,
        tokens: _FirebasePythonBackendTokens(),
        client: http.Client(),
      );

  final PythonBackendTransport _transport;
  Future<void>? _activation;

  @override
  Future<void> verifyIdentity() async {
    await (_activation ??= _activateAppCheck());
    await _transport.verifyIdentity();
  }

  @override
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  }) async {
    await (_activation ??= _activateAppCheck());
    return _transport.evaluateAttendanceStatus(
      lessons: lessons,
      calls: calls,
      status: status,
    );
  }

  static Future<void> _activateAppCheck() async {
    if (kIsWeb && _webSiteKey.isEmpty) {
      throw StateError('Firebase App Check web site key is not configured.');
    }
    await FirebaseAppCheck.instance.activate(
      providerWeb: ReCaptchaEnterpriseProvider(_webSiteKey),
      providerAndroid: kDebugMode
          ? const AndroidDebugProvider()
          : const AndroidPlayIntegrityProvider(),
    );
  }
}

final class _FirebasePythonBackendTokens implements PythonBackendTokens {
  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    final token = await FirebaseAuth.instance.currentUser?.getIdToken(
      forceRefresh,
    );
    return token ?? '';
  }

  @override
  Future<String> limitedUseAppCheckToken() =>
      FirebaseAppCheck.instance.getLimitedUseToken();
}
