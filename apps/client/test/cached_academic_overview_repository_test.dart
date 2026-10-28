import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/cached_academic_overview_repository.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/data/shared_preferences_academic_overview_cache.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  for (final remoteFails in [false, true]) {
    test(
      'discards an overview after auth changes during remote read (failure=$remoteFails)',
      () async {
        var owner = 'alice';
        final cache = _MemoryOverviewSnapshotCache();
        final remote = _DeferredSnapshotRemote();
        final repository = CachedAcademicOverviewRepository(
          remote: remote,
          cache: cache,
          currentUserId: () => owner,
          logger: _Logger(),
        );
        final pending = repository.loadOverview();
        owner = 'bob';
        if (remoteFails) {
          remote.result.completeError(StateError('network'));
        } else {
          remote.result.complete(
            AcademicOverviewSnapshot(courses: [], sessionsByCourse: {}),
          );
        }
        await expectLater(pending, throwsStateError);
        expect(cache.values, isEmpty);
        expect(
          cache.readUsers,
          isEmpty,
          reason: 'Must not fall back to the next account cache',
        );
      },
    );
  }
  test(
    'does not return a cached snapshot if identity changes during cache read',
    () async {
      var owner = 'alice';
      final cache = _MemoryOverviewSnapshotCache();
      final repository = CachedAcademicOverviewRepository(
        remote: _SnapshotRemote(
          AcademicOverviewSnapshot(courses: [], sessionsByCourse: {}),
        ),
        cache: cache,
        currentUserId: () => owner,
        logger: _Logger(),
      );
      await repository.loadOverview();
      cache.onRead = () => owner = 'bob';
      expect(await repository.loadCachedOverview(), isNull);
      expect(
        cache.values.containsKey('alice'),
        isTrue,
        reason: 'Auth change is not corruption',
      );
      expect(cache.values.containsKey('bob'), isFalse);
    },
  );
  test(
    'does not return old owner data after the cache write completes',
    () async {
      var owner = 'alice';
      final cache = _MemoryOverviewSnapshotCache()
        ..onWrite = () => owner = 'bob';
      final repository = CachedAcademicOverviewRepository(
        remote: _SnapshotRemote(
          AcademicOverviewSnapshot(courses: [], sessionsByCourse: {}),
        ),
        cache: cache,
        currentUserId: () => owner,
        logger: _Logger(),
      );
      await expectLater(repository.loadOverview(), throwsStateError);
      expect(cache.values.keys, ['alice']);
    },
  );

  test(
    'date cache survives restart, partial refresh and legacy snapshots without sharing users',
    () async {
      final source = await PythonOverviewRepository(
        gateway: _OverviewGateway.success(),
        logger: _Logger(),
      ).loadOverview();
      final date = PythonMoodleDate(
        id: 'moodle-1',
        courseId: 'course-1',
        courseCode: 'DCC203',
        title: 'Parte 2',
        dueAt: DateTime.utc(2026, 10, 28, 2),
        kind: 'assignment',
      );
      final remote = _SnapshotRemote(
        AcademicOverviewSnapshot(
          courses: source.courses,
          sessionsByCourse: source.sessionsByCourse,
          datesByCourse: {
            'course-1': [date],
          },
        ),
      );
      final cache = _MemoryOverviewSnapshotCache();
      final repository = CachedAcademicOverviewRepository(
        remote: remote,
        cache: cache,
        currentUserId: () => 'user-1',
        logger: _Logger(),
      );
      await repository.loadOverview();
      final restored = await repository.loadCachedOverview();
      expect(restored!.datesByCourse['course-1']!.single.title, 'Parte 2');
      expect(restored.datesByCourse['course-1']!.single.dueAt, date.dueAt);
      remote.snapshot = AcademicOverviewSnapshot(
        courses: source.courses,
        sessionsByCourse: source.sessionsByCourse,
        unavailableDateCourses: {'course-1'},
      );
      final partial = await repository.loadOverview();
      expect(partial.datesByCourse['course-1']!.single.title, 'Parte 2');
      expect(partial.unavailableDateCourses, {'course-1'});
      final freshUser = CachedAcademicOverviewRepository(
        remote: remote,
        cache: cache,
        currentUserId: () => 'user-2',
        logger: _Logger(),
      );
      expect(
        (await freshUser.loadOverview()).datesByCourse['course-1'],
        isEmpty,
      );
      final json = jsonDecode(cache.values['user-1']!) as Map<String, dynamic>;
      json.remove('dates_by_course');
      json.remove('unavailable_date_courses');
      cache.values['user-1'] = jsonEncode(json);
      expect(
        (await repository.loadCachedOverview())!.datesByCourse['course-1'],
        isEmpty,
      );
      for (final invalidId in ['bad', 123]) {
        json['dates_by_course'] = {
          'course-1': [
            {'id': invalidId},
          ],
        };
        cache.values['user-1'] = jsonEncode(json);
        expect(await repository.loadCachedOverview(), isNull);
      }
      remote.snapshot = AcademicOverviewSnapshot(
        courses: [],
        sessionsByCourse: {},
        unavailableDateCourses: {'course-1'},
      );
      expect((await repository.loadOverview()).datesByCourse, isEmpty);
    },
  );

  test(
    'restores the last successful overview after the app restarts offline',
    () async {
      final cache = _MemoryOverviewSnapshotCache();
      final logger = _Logger();
      final online = CachedAcademicOverviewRepository(
        remote: PythonOverviewRepository(
          gateway: _OverviewGateway.success()..online = true,
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
      expect(restored.courses.single.tracksAttendance, isFalse);
      expect(restored.courses.single.modality.code, 'online');
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
  bool online = false;
  _OverviewGateway.success() : _error = null;

  _OverviewGateway.failure() : _error = StateError('offline');

  _OverviewGateway.withError(this._error);

  final Object? _error;

  @override
  Future<List<PythonOverviewItem>> loadOverview() async {
    if (_error != null) throw _error;
    return [
      PythonOverviewItem(
        course: PythonCourse.fromJson({
          if (online) 'modality': 'online',
          if (online) 'attendance_policy': 'no_call',
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
  final readUsers = <String>[];
  void Function()? onRead;
  void Function()? onWrite;

  @override
  Future<String?> read(String userId) async {
    readUsers.add(userId);
    onRead?.call();
    if (readError case final error?) throw error;
    return values[userId];
  }

  @override
  Future<void> write(String userId, String value) async {
    if (writeError case final error?) throw error;
    values[userId] = value;
    onWrite?.call();
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

class _SnapshotRemote implements AcademicOverviewRepository {
  _SnapshotRemote(this.snapshot);
  AcademicOverviewSnapshot snapshot;
  @override
  Future<AcademicOverviewSnapshot> loadOverview() async => snapshot;
}

class _DeferredSnapshotRemote implements AcademicOverviewRepository {
  final result = Completer<AcademicOverviewSnapshot>();
  @override
  Future<AcademicOverviewSnapshot> loadOverview() => result.future;
}
