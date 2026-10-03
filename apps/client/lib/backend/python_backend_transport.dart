import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

enum PythonBackendError {
  appCheckInvalid,
  credentialsUnavailable,
  invalidResponse,
  rateLimited,
  replayed,
  timeout,
  unauthorized,
  unavailable,
}

final class PythonBackendException implements Exception {
  const PythonBackendException(this.code, {this.retryAfter});

  final PythonBackendError code;
  final Duration? retryAfter;

  @override
  String toString() => 'PythonBackendException(${code.name})';
}

abstract interface class PythonBackendTokens {
  Future<String> firebaseIdToken({required bool forceRefresh});

  Future<String> limitedUseAppCheckToken();
}

abstract interface class BackendIdentityVerifier {
  Future<void> verifyIdentity();
}

final class PythonBackendSettings {
  const PythonBackendSettings({required this.enabled, required this.endpoint});

  final bool enabled;
  final String endpoint;

  Uri? get endpointUri {
    if (!enabled) return null;
    final uri = Uri.tryParse(endpoint);
    final isLocal =
        uri?.scheme == 'http' &&
        (uri?.host == 'localhost' || uri?.host == '127.0.0.1');
    if (uri == null ||
        (!uri.hasScheme || (uri.scheme != 'https' && !isLocal)) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw ArgumentError.value(endpoint, 'endpoint', 'unsafe backend origin');
    }
    return uri.replace(path: '');
  }
}

final class PythonBackendTransport implements BackendIdentityVerifier {
  PythonBackendTransport({
    required Uri endpoint,
    required PythonBackendTokens tokens,
    http.Client? client,
    this.timeout = const Duration(seconds: 10),
  }) : _endpoint = endpoint,
       _tokens = tokens,
       _client = client ?? http.Client();

  final Uri _endpoint;
  final PythonBackendTokens _tokens;
  final http.Client _client;
  final Duration timeout;

  @override
  Future<void> verifyIdentity() async {
    var forceIdentityRefresh = false;
    for (var attempt = 0; attempt < 2; attempt += 1) {
      final response = await _request(
        forceIdentityRefresh: forceIdentityRefresh,
      );
      final error = _errorCode(response);
      if (response.statusCode == 200) {
        if (_isAuthenticated(response.body)) return;
        throw const PythonBackendException(PythonBackendError.invalidResponse);
      }
      if (attempt == 0 && error == 'unauthorized') {
        forceIdentityRefresh = true;
        continue;
      }
      if (attempt == 0 && error == 'app_check_replayed') continue;
      throw _exceptionFor(response.statusCode, error, response.headers);
    }
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  Future<http.Response> _request({required bool forceIdentityRefresh}) async {
    try {
      final idToken = await _tokens.firebaseIdToken(
        forceRefresh: forceIdentityRefresh,
      );
      final appCheckToken = await _tokens.limitedUseAppCheckToken();
      if (idToken.isEmpty || appCheckToken.isEmpty) {
        throw const PythonBackendException(
          PythonBackendError.credentialsUnavailable,
        );
      }
      return await _client
          .get(
            _endpoint.resolve('/v1/identity'),
            headers: {
              'Authorization': 'Bearer $idToken',
              'X-Firebase-AppCheck': appCheckToken,
            },
          )
          .timeout(timeout);
    } on PythonBackendException {
      rethrow;
    } on TimeoutException {
      throw const PythonBackendException(PythonBackendError.timeout);
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.unavailable);
    }
  }

  static bool _isAuthenticated(String body) {
    try {
      final value = jsonDecode(body);
      return value is Map<String, dynamic> && value['authenticated'] == true;
    } catch (_) {
      return false;
    }
  }

  static String? _errorCode(http.Response response) {
    try {
      final value = jsonDecode(response.body);
      return value is Map<String, dynamic> && value['error'] is String
          ? value['error'] as String
          : null;
    } catch (_) {
      return null;
    }
  }

  static PythonBackendException _exceptionFor(
    int status,
    String? error,
    Map<String, String> headers,
  ) {
    if (status == 401 && error == 'app_check_invalid') {
      return const PythonBackendException(PythonBackendError.appCheckInvalid);
    }
    if (status == 401) {
      return const PythonBackendException(PythonBackendError.unauthorized);
    }
    if (status == 409 && error == 'app_check_replayed') {
      return const PythonBackendException(PythonBackendError.replayed);
    }
    if (status == 429) {
      final seconds = int.tryParse(headers['retry-after'] ?? '');
      return PythonBackendException(
        PythonBackendError.rateLimited,
        retryAfter: seconds != null && seconds > 0 && seconds <= 3600
            ? Duration(seconds: seconds)
            : null,
      );
    }
    if (status == 503) {
      return const PythonBackendException(PythonBackendError.unavailable);
    }
    return const PythonBackendException(PythonBackendError.invalidResponse);
  }
}
