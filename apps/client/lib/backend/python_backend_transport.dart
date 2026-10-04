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

abstract interface class BackendAttendanceEvaluator {
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  });
}

final class PythonAttendanceDecision {
  const PythonAttendanceDecision({
    required this.status,
    required this.absences,
  });

  final String status;
  final int? absences;
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

final class PythonBackendTransport
    implements BackendIdentityVerifier, BackendAttendanceEvaluator {
  PythonBackendTransport({
    required Uri endpoint,
    required PythonBackendTokens tokens,
    required http.Client client,
    this.timeout = const Duration(seconds: 30),
  }) : _endpoint = endpoint,
       _tokens = tokens,
       _client = client;

  final Uri _endpoint;
  final PythonBackendTokens _tokens;
  final http.Client _client;
  final Duration timeout;

  @override
  Future<void> verifyIdentity() async {
    final response = await _authenticatedRequest(path: '/v1/identity');
    if (_isAuthenticated(response.body)) return;
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  @override
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  }) async {
    final response = await _authenticatedRequest(
      path: '/v1/attendance/evaluate',
      body: {'lessons': lessons, 'calls': calls, 'status': status},
    );
    return _attendanceDecision(response.body, maximumAbsences: lessons);
  }

  Future<http.Response> _authenticatedRequest({
    required String path,
    Map<String, Object>? body,
  }) async {
    var forceIdentityRefresh = false;
    for (var attempt = 0; attempt < 2; attempt += 1) {
      final response = await _request(
        forceIdentityRefresh: forceIdentityRefresh,
        path: path,
        body: body,
      );
      final error = _errorCode(response);
      if (response.statusCode == 200) return response;
      if (attempt == 0 && error == 'unauthorized') {
        forceIdentityRefresh = true;
        continue;
      }
      if (attempt == 0 && error == 'app_check_replayed') continue;
      throw _exceptionFor(response.statusCode, error, response.headers);
    }
    throw const PythonBackendException(PythonBackendError.invalidResponse);
  }

  Future<http.Response> _request({
    required bool forceIdentityRefresh,
    required String path,
    required Map<String, Object>? body,
  }) async {
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
      final headers = {
        'Authorization': 'Bearer $idToken',
        'X-Firebase-AppCheck': appCheckToken,
      };
      final uri = _endpoint.resolve(path);
      final request = body == null
          ? _client.get(uri, headers: headers)
          : _client.post(
              uri,
              headers: {...headers, 'Content-Type': 'application/json'},
              body: jsonEncode(body),
            );
      return await request.timeout(timeout);
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

  static PythonAttendanceDecision _attendanceDecision(
    String body, {
    required int maximumAbsences,
  }) {
    try {
      final value = jsonDecode(body);
      if (value is! Map<String, dynamic> ||
          value.keys.toSet().difference({'status', 'absences'}).isNotEmpty) {
        throw const FormatException();
      }
      final status = value['status'];
      final absences = value['absences'];
      const allowedStatuses = {
        'presente',
        'chegou_atrasado',
        'saiu_mais_cedo',
        'ausente',
        'pendente',
      };
      final validAbsences =
          absences == null ||
          absences is int && absences >= 0 && absences <= maximumAbsences;
      if (status is! String ||
          !allowedStatuses.contains(status) ||
          !validAbsences ||
          (status == 'pendente') != (absences == null)) {
        throw const FormatException();
      }
      return PythonAttendanceDecision(
        status: status,
        absences: absences as int?,
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
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
