import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/cached_academic_overview_repository.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/data/shared_preferences_academic_overview_cache.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  test(
    'restores the last successful overview after the app restarts offline',
    () async {
      final cache = _MemoryOverviewSnapshotCache();
      final logger = _Logger();
      final online = CachedAcademicOverviewRepository(
        remote: PythonOverviewRepository(
          gateway: _OverviewGateway.success(),
          logger: logger,
        ),
        cache: cache,
        currentUserId: () => 'user-1',
        logger: logger,
      );

      await online.loadOverview();

      final offlineAfterRestart = CachedAcademicOverviewRepository(
        remote: PythonOverviewRepository(
          gateway: _OverviewGateway.failure(),
          logger: logger,
        ),
        cache: cache,
        currentUserId: () => 'user-1',
        logger: logger,
      );
      final restored = await offlineAfterRestart.loadOverview();

      expect(restored.courses.single.code, 'DCC203');
      expect(restored.sessionsByCourse['course-1']!.single.id, 'session-1');
      expect(restored.isLocalCopy, isTrue);
      expect(logger.events, contains('academic_overview_cache_hit'));
    },
  );

  test('keeps the online result when writing the cache fails', () async {
    final cache = _MemoryOverviewSnapshotCache()
      ..writeError = StateError('disk unavailable');
    final logger = _Logger();
    final repository = CachedAcademicOverviewRepository(
      remote: PythonOverviewRepository(
        gateway: _OverviewGateway.success(),
        logger: logger,
      ),
      cache: cache,
      currentUserId: () => 'user-1',
      logger: logger,
    );

    final snapshot = await repository.loadOverview();

    expect(snapshot.courses.single.code, 'DCC203');
    expect(logger.errorContexts, contains('academic_overview_cache_write'));
  });

  test('preserves the remote error when there is no usable cache', () async {
    final remoteError = StateError('offline');
    final scenarios = <_MemoryOverviewSnapshotCache>[
      _MemoryOverviewSnapshotCache(),
      _MemoryOverviewSnapshotCache()..readError = StateError('read failed'),
      _MemoryOverviewSnapshotCache()..values['user-1'] = '{invalid',
      _MemoryOverviewSnapshotCache()
        ..values['user-1'] = '{invalid'
        ..removeError = StateError('remove failed'),
    ];

    for (final cache in scenarios) {
      final logger = _Logger();
      final repository = CachedAcademicOverviewRepository(
        remote: PythonOverviewRepository(
          gateway: _OverviewGateway.withError(remoteError),
          logger: logger,
        ),
        cache: cache,
        currentUserId: () => 'user-1',
        logger: logger,
      );

      await expectLater(repository.loadOverview(), throwsA(same(remoteError)));
    }
  });

  test(
    'does not share a cached overview without an authenticated user',
    () async {
      final error = StateError('offline');
      final logger = _Logger();
      final repository = CachedAcademicOverviewRepository(
        remote: PythonOverviewRepository(
          gateway: _OverviewGateway.withError(error),
          logger: logger,
        ),
        cache: _MemoryOverviewSnapshotCache(),
        currentUserId: () => null,
        logger: logger,
      );

      await expectLater(repository.loadOverview(), throwsA(same(error)));
    },
  );

  test(
    'shared preferences cache persists and removes one user snapshot',
    () async {
      SharedPreferencesAsyncPlatform.instance =
          InMemorySharedPreferencesAsync.empty();
      final cache = SharedPreferencesAcademicOverviewCache();

      await cache.write('user-1', 'snapshot');
      expect(await cache.read('user-1'), 'snapshot');
      expect(await cache.read('user-2'), isNull);

      await cache.remove('user-1');
      expect(await cache.read('user-1'), isNull);
    },
  );
}

final class _OverviewGateway implements BackendOverviewGateway {
  _OverviewGateway.success() : _error = null;

  _OverviewGateway.failure() : _error = StateError('offline');

  _OverviewGateway.withError(this._error);

  final Object? _error;

  @override
  Future<List<PythonOverviewItem>> loadOverview() async {
    if (_error != null) throw _error;
    return [
      PythonOverviewItem(
        course: PythonCourse.fromJson(const {
          'id': 'course-1',
          'code': 'DCC203',
          'name': 'POO',
          'workload': 60,
          'term': '2026-2',
          'starts_on': '2026-07-01T00:00:00Z',
          'ends_on': '2026-12-31T00:00:00Z',
          'created_at': '2026-07-01T12:00:00Z',
          'updated_at': '2026-07-01T12:00:00Z',
        }),
        sessions: [
          PythonSession.fromJson(const {
            'id': 'session-1',
            'starts_at': '2026-10-08T10:00:00Z',
            'ends_at': '2026-10-08T11:40:00Z',
            'lesson_count': 2,
            'call_count': 1,
            'first_ping': null,
            'second_ping': null,
            'attendance_status': 'pendente',
            'absences': null,
            'calendar_status': 'scheduled',
            'assessment_title': null,
            'created_at': '2026-07-01T12:00:00Z',
            'updated_at': '2026-10-08T12:00:00Z',
          }),
        ],
      ),
    ];
  }
}

final class _MemoryOverviewSnapshotCache implements AcademicOverviewCache {
  final values = <String, String>{};
  Object? readError;
  Object? writeError;
  Object? removeError;

  @override
  Future<String?> read(String userId) async {
    if (readError case final error?) throw error;
    return values[userId];
  }

  @override
  Future<void> write(String userId, String value) async {
    if (writeError case final error?) throw error;
    values[userId] = value;
  }

  @override
  Future<void> remove(String userId) async {
    if (removeError case final error?) throw error;
    values.remove(userId);
  }
}

final class _Logger implements AppLogger {
  final events = <String>[];
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
  }
}
