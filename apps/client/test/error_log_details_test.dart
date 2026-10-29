import 'dart:convert';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/observability/error_log_details.dart';
import 'package:google_sign_in/google_sign_in.dart';

void main() {
  test(
    'structured diagnostic details preserve context and redact nested credentials',
    () {
      final data = jsonEncode({
        'course': 'POO',
        'padding': 'p' * 1000,
        'stage': 'location_fix',
        'nested': {
          'password': 'hidden-password',
          'authorization': 'hidden-authorization',
          'enabled': true,
        },
        'list': [
          null,
          42,
          {'api_key': 'hidden-api-key'},
        ],
        'message': 'Bearer hidden-bearer',
      });
      final result = sanitizeDiagnosticDetails(data)!;
      final decoded = jsonDecode(result) as Map;
      expect(decoded['course'], 'POO');
      expect(decoded['stage'], 'location_fix');
      for (final secret in [
        'hidden-password',
        'hidden-authorization',
        'hidden-api-key',
        'hidden-bearer',
      ]) {
        expect(result, isNot(contains(secret)));
      }
      expect(decoded['nested']['enabled'], true);
      expect(sanitizeDiagnosticDetails(null), isNull);
      expect(sanitizeDiagnosticDetails('stage=read'), 'stage=read');
      expect(sanitizeDiagnosticDetails(jsonEncode(true)), 'true');
      expect(
        sanitizeDiagnosticDetails('{"password":"do-not-log", broken'),
        isNot(contains('do-not-log')),
      );
    },
  );
  test(
    'oversized, deeply nested and wide diagnostics remain valid and explicitly bounded',
    () {
      for (final value in [
        jsonEncode({'large': 'x' * 9000}),
        'x' * 9000,
        jsonEncode({'large': '😀' * 3000}),
      ]) {
        final result = sanitizeDiagnosticDetails(value)!;
        expect(utf8.encode(result).length, lessThanOrEqualTo(8192));
        expect(jsonDecode(result)['details_truncated'], true);
      }
      final wide = {for (var i = 0; i < 70; i++) 'field$i': i};
      final map =
          jsonDecode(sanitizeDiagnosticDetails(jsonEncode(wide))!) as Map;
      expect(map['fields_omitted'], 6);
      final list =
          jsonDecode(
                sanitizeDiagnosticDetails(
                  jsonEncode(List.generate(70, (i) => i)),
                )!,
              )
              as List;
      expect(list.last, {'items_omitted': 6});
      Object nested = 'leaf';
      for (var i = 0; i < 12; i++) {
        nested = {'child': nested};
      }
      expect(
        sanitizeDiagnosticDetails(jsonEncode(nested)),
        contains('[MAX_DEPTH]'),
      );
    },
  );
  test('keeps useful Google sign-in details and redacts secrets', () {
    const error = GoogleSignInException(
      code: GoogleSignInExceptionCode.clientConfigurationError,
      description:
          'ApiException: 10 for aluno@ufmg.br with Bearer abcdefghijklmnop',
      details: 'id_token=abcdefghijkl.abcdefghijkl.abcdefghijkl',
    );

    final details = ErrorLogDetails.from(error);

    expect(details.type, 'GoogleSignInException');
    expect(details.code, 'clientConfigurationError');
    expect(details.message, contains('ApiException: 10'));
    expect(details.message, isNot(contains('aluno@ufmg.br')));
    expect(details.message, isNot(contains('abcdefghijklmnop')));
    expect(details.details, 'id_token=[REDACTED]');
  });

  test('extracts Firebase Auth errors without account data', () {
    final details = ErrorLogDetails.from(
      FirebaseAuthException(
        code: 'wrong-password',
        message: 'password=secret for pessoa@example.com',
      ),
    );

    expect(details.code, 'wrong-password');
    expect(details.message, 'password=[REDACTED] for [REDACTED]');
  });

  test('extracts Firestore error codes without exposing secrets', () {
    final details = ErrorLogDetails.from(
      FirebaseException(
        plugin: 'cloud_firestore',
        code: 'permission-denied',
        message: 'api_key=secret for pessoa@example.com',
      ),
    );

    expect(details.type, 'FirebaseException');
    expect(details.code, 'permission-denied');
    expect(details.message, 'api_key=[REDACTED] for [REDACTED]');
  });

  test('extracts platform error code, message, and safe details', () {
    final details = ErrorLogDetails.from(
      PlatformException(
        code: 'sign_in_failed',
        message: 'ApiException: 10',
        details: 'authorization: top-secret',
      ),
    );

    expect(details.code, 'sign_in_failed');
    expect(details.message, 'ApiException: 10');
    expect(details.details, 'authorization=[REDACTED]');
  });

  test('captures generic errors and limits stored messages', () {
    final details = ErrorLogDetails.from(StateError('x' * 600));
    final parameters = details.analyticsParameters(
      context: 'uncaught_async',
      fatal: true,
    );

    expect(details.message, hasLength(500));
    expect(details.message, endsWith('...'));
    expect(parameters['context'], 'uncaught_async');
    expect(parameters['error_type'], 'StateError');
    expect(parameters['error_message'], hasLength(100));
    expect(parameters['fatal'], 1);
    expect(parameters, isNot(contains('error_code')));
    expect(parameters, isNot(contains('error_details')));
    expect(SanitizedAppException(details).toString(), details.summary);
  });

  test('keeps structured backend codes and safe transport details', () {
    const error = PythonBackendException(
      PythonBackendError.unavailable,
      causeType: 'ClientException',
    );

    final details = ErrorLogDetails.from(error);

    expect(details.type, 'PythonBackendException');
    expect(details.code, 'unavailable');
    expect(details.message, 'Python backend request failed.');
    expect(details.details, 'cause=ClientException');
  });

  test('includes all structured fields for a nonfatal error', () {
    const details = ErrorLogDetails(
      type: 'PlatformException',
      code: 'network_error',
      message: 'Network unavailable',
      details: 'status=offline',
    );

    expect(details.analyticsParameters(context: 'sync', fatal: false), {
      'context': 'sync',
      'error_type': 'PlatformException',
      'error_code': 'network_error',
      'error_message': 'Network unavailable',
      'error_details': 'status=offline',
      'fatal': 0,
    });
    expect(
      details.summary,
      'PlatformException, code=network_error, message=Network unavailable, '
      'details=status=offline',
    );
  });

  test('sanitizer handles null and common credential forms', () {
    expect(sanitizeLogText(null), isNull);
    expect(
      sanitizeLogText(
        'cookie=session123; client-secret: hidden, api_key=publicish '
        'refresh_token=refresh-me',
      ),
      'cookie=[REDACTED]; client-secret=[REDACTED], '
      'api_key=[REDACTED] refresh_token=[REDACTED]',
    );
  });
}
