import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/services.dart';
import 'package:google_sign_in/google_sign_in.dart';

const _redacted = '[REDACTED]';

final class ErrorLogDetails {
  const ErrorLogDetails({
    required this.type,
    this.code,
    this.message,
    this.details,
  });

  factory ErrorLogDetails.from(Object error) {
    if (error is GoogleSignInException) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: error.code.name,
        message: sanitizeLogText(error.description),
        details: sanitizeLogText(error.details?.toString()),
      );
    }
    if (error is FirebaseAuthException) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: error.code,
        message: sanitizeLogText(error.message),
      );
    }
    if (error is PlatformException) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: error.code,
        message: sanitizeLogText(error.message),
        details: sanitizeLogText(error.details?.toString()),
      );
    }
    return ErrorLogDetails(
      type: error.runtimeType.toString(),
      message: sanitizeLogText(error.toString()),
    );
  }

  final String type;
  final String? code;
  final String? message;
  final String? details;

  String get summary => [
    type,
    if (code != null) 'code=$code',
    if (message != null) 'message=$message',
    if (details != null) 'details=$details',
  ].join(', ');

  Map<String, Object> analyticsParameters({
    required String context,
    required bool fatal,
  }) => {
    'context': context,
    'error_type': type,
    'error_code': ?code,
    if (message case final message?) 'error_message': _limit(message, 100),
    if (details case final details?) 'error_details': _limit(details, 100),
    'fatal': fatal ? 1 : 0,
  };
}

final class SanitizedAppException implements Exception {
  const SanitizedAppException(this.details);

  final ErrorLogDetails details;

  @override
  String toString() => details.summary;
}

String? sanitizeLogText(String? value) {
  if (value == null) return null;
  var sanitized = value;
  sanitized = sanitized.replaceAll(
    RegExp(r'Bearer\s+[A-Za-z0-9._~+/=-]+', caseSensitive: false),
    'Bearer $_redacted',
  );
  sanitized = sanitized.replaceAll(
    RegExp(r'[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}'),
    _redacted,
  );
  sanitized = sanitized.replaceAllMapped(
    RegExp(
      r'\b(access[_-]?token|id[_-]?token|refresh[_-]?token|password|passwd|authorization|cookie|client[_-]?secret|api[_-]?key)\b\s*[:=]\s*([^\s,;&]+)',
      caseSensitive: false,
    ),
    (match) => '${match.group(1)}=$_redacted',
  );
  sanitized = sanitized.replaceAll(
    RegExp(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', caseSensitive: false),
    _redacted,
  );
  return _limit(sanitized, 500);
}

String _limit(String value, int maximumLength) => value.length <= maximumLength
    ? value
    : '${value.substring(0, maximumLength - 3)}...';
