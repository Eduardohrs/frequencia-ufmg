import 'dart:convert';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/material_download_failure.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';

void main() {
  test(
    'persists permission diagnostic flags with correlation, without changing legacy documents',
    () async {
      final store = _RecordingLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'user-1',
        platform: 'android',
      );
      await logger.logEvent(
        'attendance_permission_status',
        parameters: {
          'operation_id': 'permission-check-1',
          'details': jsonEncode({
            'android_sdk': 36,
            'foreground_location': true,
            'precise_location': false,
            'background_location': false,
          }),
        },
      );
      final document = store.documents.single;
      expect(document['correlationId'], 'permission-check-1');
      expect(
        jsonDecode(document['details']! as String),
        containsPair('precise_location', false),
      );
      await logger.logEvent('ordinary_event');
      expect(store.documents.last.containsKey('details'), isFalse);
      await logger.logEvent(
        'bounded_context',
        parameters: {'details': 'x' * 501},
      );
      expect((store.documents.last['details']! as String).length, 500);
    },
  );
  test(
    'persists batch material identity and the underlying transport failure',
    () async {
      final store = _RecordingLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'user-1',
        platform: 'android',
      );
      await logger.recordError(
        MaterialPreparationFailure(
          materialId: '2026-2/4953/63628',
          materialName: 'Orientacoes.pdf',
          courseCode: 'ELE028',
          cause: const PythonBackendException(
            PythonBackendError.unavailable,
            requestContext:
                'stage=http_response method=post path=/v1/ufmg/moodle/material-files '
                'status=503 backend_error=moodle_unavailable request_id=child-123 password=secret-value',
          ),
        ),
        StackTrace.current,
        context: 'moodle_material_prepare',
        parameters: {'operation_id': 'child-123', 'duration_ms': 4512},
      );
      final document = store.documents.single;
      expect(document['correlationId'], 'child-123');
      expect(document['durationMs'], 4512);
      expect(document['operation'], 'moodle_material_prepare');
      expect(document['errorCode'], 'unavailable');
      expect(
        document['errorMessage'],
        allOf(
          contains('prepare_files'),
          contains('ELE028'),
          contains('2026-2/4953/63628'),
          contains('Orientacoes.pdf'),
        ),
      );
      expect(
        document['errorDetails'],
        allOf(
          contains('status=503'),
          contains('backend_error=moodle_unavailable'),
          contains('request_id=child-123'),
          isNot(contains('secret-value')),
        ),
      );
    },
  );
  final now = DateTime.utc(2026, 9, 27, 20);

  test(
    'persists actionable transport diagnostics and redacts secrets',
    () async {
      final store = _RecordingLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'user-1',
        platform: 'web',
      );
      await logger.recordError(
        const PythonBackendException(
          PythonBackendError.unavailable,
          requestContext:
              'stage=http_response method=post '
              'path=/v1/calendar/official/preview status=503 '
              'backend_error=security_guard_unavailable request_id=request-123 '
              'server_request_id=server-123 password=secret-value',
        ),
        StackTrace.current,
        context: 'official_calendar_preview',
      );
      final document = store.documents.single;
      expect(document['operation'], 'official_calendar_preview');
      expect(
        document['errorDetails'],
        allOf(
          contains('status=503'),
          contains('backend_error=security_guard_unavailable'),
          contains('request_id=request-123'),
          contains('server_request_id=server-123'),
          isNot(contains('secret-value')),
        ),
      );
    },
  );

  test(
    'persists a structured correlated event for an authenticated user',
    () async {
      final store = _RecordingLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'user-1',
        platform: 'web',
        now: () => now,
        correlationId: () => 'generated-id',
      );

      await logger.logEvent(
        'firestore_course_save_failed',
        parameters: {
          'operation': 'firestore_course_save',
          'operation_id': 'operation-42',
          'outcome': 'failed',
          'duration_ms': 125,
          'screen': 'ufmg_connection',
          'action': 'download_all',
          'failure_code': 'io_failure',
        },
      );

      expect(store.userIds, ['user-1']);
      expect(store.documents.single, {
        'schemaVersion': 1,
        'occurredAt': now,
        'expiresAt': now.add(const Duration(days: 30)),
        'level': 'info',
        'event': 'firestore_course_save_failed',
        'entryPoint': 'client',
        'platform': 'web',
        'correlationId': 'operation-42',
        'operation': 'firestore_course_save',
        'outcome': 'failed',
        'durationMs': 125,
        'screen': 'ufmg_connection',
        'action': 'download_all',
        'failureCode': 'io_failure',
        'errorType': null,
        'errorCode': null,
        'errorMessage': null,
        'errorDetails': null,
        'fatal': false,
      });
    },
  );

  test(
    'persists sanitized errors without stack traces or account data',
    () async {
      final store = _RecordingLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'user-1',
        platform: 'android',
        now: () => now,
        correlationId: () => 'error-42',
      );

      await logger.recordError(
        FirebaseException(
          plugin: 'cloud_firestore',
          code: 'permission-denied',
          message: 'Bearer abcdefghijklmnop for aluno@ufmg.br',
        ),
        StackTrace.fromString('must-not-be-persisted'),
        context: 'firestore_course_save',
        parameters: {'duration_ms': 20},
      );

      final document = store.documents.single;
      expect(document['level'], 'error');
      expect(document['event'], 'app_exception');
      expect(document['correlationId'], 'error-42');
      expect(document['operation'], 'firestore_course_save');
      expect(document['durationMs'], 20);
      expect(document['errorType'], 'FirebaseException');
      expect(document['errorCode'], 'permission-denied');
      expect(document['errorMessage'], 'Bearer [REDACTED] for [REDACTED]');
      expect(document.values, isNot(contains('must-not-be-persisted')));
    },
  );

  test(
    'skips unauthenticated events and remembers the user through logout',
    () async {
      final store = _RecordingLogStore();
      String? userId;
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => userId,
        platform: 'web',
        now: () => now,
        correlationId: () => 'generated-id',
      );

      await logger.logEvent('auth_google_sign_in_started');
      userId = 'user-1';
      await logger.logEvent('auth_google_sign_in_succeeded');
      userId = null;
      await logger.logEvent('auth_logout_succeeded');

      expect(store.userIds, ['user-1', 'user-1']);
      expect(store.documents.map((document) => document['event']), [
        'auth_google_sign_in_succeeded',
        'auth_logout_succeeded',
      ]);
    },
  );

  test('bounds stored fields and generates correlation when absent', () async {
    final store = _RecordingLogStore();
    final logger = FirestoreAppLogger(
      store: store,
      currentUserId: () => 'user-1',
      platform: 'web',
      now: () => now,
    );

    await logger.logEvent(
      'x' * 81,
      parameters: {'operation': 'y' * 81, 'duration_ms': -1},
    );

    final document = store.documents.single;
    expect(document['event'], 'x' * 80);
    expect(document['operation'], 'y' * 80);
    expect(document['durationMs'], isNull);
    expect(document['correlationId'], endsWith('-client'));
  });
}

final class _RecordingLogStore implements OperationalLogStore {
  final userIds = <String>[];
  final documents = <Map<String, Object?>>[];

  @override
  Future<void> add(String userId, Map<String, Object?> document) async {
    userIds.add(userId);
    documents.add(document);
  }
}
