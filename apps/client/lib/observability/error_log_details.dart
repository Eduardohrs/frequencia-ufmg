import 'dart:convert';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/services.dart';
import 'package:google_sign_in/google_sign_in.dart';

const _redacted = '[REDACTED]';

abstract interface class StructuredAppError {
  String get logCode;
  String? get logMessage;
  String? get logDetails;
}

final class ErrorLogDetails {
  const ErrorLogDetails({
    required this.type,
    this.code,
    this.message,
    this.details,
  });

  factory ErrorLogDetails.from(Object error) {
    if (error is StructuredAppError) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: sanitizeLogText(error.logCode),
        message: sanitizeLogText(error.logMessage),
        details: sanitizeDiagnosticDetails(error.logDetails),
      );
    }
    if (error is GoogleSignInException) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: error.code.name,
        message: sanitizeLogText(error.description),
        details: sanitizeDiagnosticDetails(error.details?.toString()),
      );
    }
    if (error is FirebaseAuthException) {
      return ErrorLogDetails(
        type: error.runtimeType.toString(),
        code: error.code,
        message: sanitizeLogText(error.message),
      );
    }
    if (error is FirebaseException) {
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
        details: sanitizeDiagnosticDetails(error.details?.toString()),
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

String? sanitizeLogText(String? value, {int maximumLength = 500}) {
  if (value == null) return null;
  var sanitized = value;
  sanitized = sanitized.replaceAllMapped(
    RegExp(
      r'("(?:password|passwd|token|access[_-]?token|refresh[_-]?token|id[_-]?token|authorization|cookie|set[_-]?cookie|api[_-]?key|client[_-]?secret)"\s*:\s*)"(?:\\.|[^"\\])*"',
      caseSensitive: false,
    ),
    (match) => '${match.group(1)}"$_redacted"',
  );
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
      r'\b(token|access[_-]?token|id[_-]?token|refresh[_-]?token|app[_-]?check[_-]?token|password|passwd|authorization|cookie|client[_-]?secret|api[_-]?key)\b\s*[:=]\s*([^\s,;&]+)',
      caseSensitive: false,
    ),
    (match) => '${match.group(1)}=$_redacted',
  );
  sanitized = sanitized.replaceAll(
    RegExp(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', caseSensitive: false),
    _redacted,
  );
  return _limit(sanitized, maximumLength);
}

String _limit(String value, int maximumLength) => value.length <= maximumLength
    ? value
    : '${value.substring(0, maximumLength - 3)}...';

const diagnosticDetailsLimit = 8192;
final _diagnosticSecretKey = RegExp(
  r'^(password|passwd|token|access[_-]?token|id[_-]?token|refresh[_-]?token|app[_-]?check[_-]?token|authorization|cookie|set[_-]?cookie|client[_-]?secret|api[_-]?key)$',
  caseSensitive: false,
);

/// Keep structured reports parseable and bounded; never cut JSON mid-field.
String? sanitizeDiagnosticDetails(String? value) {
  if (value == null) return null;
  String sanitized;
  var truncated = false;
  try {
    sanitized = jsonEncode(_diagnosticNode(jsonDecode(value), 0));
  } on FormatException {
    sanitized = sanitizeLogText(value, maximumLength: diagnosticDetailsLimit)!;
    truncated = value.length > diagnosticDetailsLimit;
  }
  if (!truncated && utf8.encode(sanitized).length <= diagnosticDetailsLimit) {
    return sanitized;
  }
  return jsonEncode({
    'details_truncated': true,
    'original_length': value.length,
    'preview': sanitized.substring(
      0,
      sanitized.length < 512 ? sanitized.length : 512,
    ),
  });
}

Object? _diagnosticNode(Object? value, int depth) {
  if (depth > 8) return '[MAX_DEPTH]';
  if (value is Map) {
    return <String, Object?>{
      for (final entry in value.entries.take(64))
        entry.key
            .toString(): _diagnosticSecretKey.hasMatch(entry.key.toString())
            ? _redacted
            : _diagnosticNode(entry.value, depth + 1),
      if (value.length > 64) 'fields_omitted': value.length - 64,
    };
  }
  if (value is List) {
    return [
      for (final item in value.take(64)) _diagnosticNode(item, depth + 1),
      if (value.length > 64) {'items_omitted': value.length - 64},
    ];
  }
  if (value is String) {
    return sanitizeLogText(value, maximumLength: diagnosticDetailsLimit);
  }
  return value;
}
