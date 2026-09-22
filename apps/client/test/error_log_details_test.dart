import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/error_log_details.dart';
import 'package:google_sign_in/google_sign_in.dart';

void main() {
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
