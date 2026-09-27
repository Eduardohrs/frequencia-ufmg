import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';

void main() {
  final now = DateTime.utc(2026, 9, 27, 20);

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
