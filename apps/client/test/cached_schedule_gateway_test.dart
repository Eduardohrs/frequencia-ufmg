import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/cached_schedule_gateway.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/shared_preferences_schedule_cache.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  test('restores one user schedule after the app restarts offline', () async {
    final cache = _MemoryScheduleCache();
    final logger = _Logger();
    final online = CachedScheduleGateway(
      remote: _Gateway(schedule: _schedule()),
      cache: cache,
      currentUserId: () => 'user-1',
      logger: logger,
    );

    await online.getSchedule('course-1');

    final offline = CachedScheduleGateway(
      remote: _Gateway(error: StateError('offline')),
      cache: cache,
      currentUserId: () => 'user-1',
      logger: logger,
    );
    final restored = await offline.getSchedule('course-1');

    expect(restored.course.code, 'DCC203');
    expect(restored.meetings.single.id, 'meeting-1');
    expect(restored.isLocalCopy, isTrue);
    expect(logger.events, contains('schedule_cache_hit'));
  });

  test('updates the cache after an authoritative schedule save', () async {
    final cache = _MemoryScheduleCache();
    final gateway = CachedScheduleGateway(
      remote: _Gateway(schedule: _schedule()),
      cache: cache,
      currentUserId: () => 'user-1',
      logger: _Logger(),
    );

    await gateway.saveSchedule(
      courseId: 'course-1',
      startsOn: DateTime.utc(2026, 7),
      endsOn: DateTime.utc(2026, 12, 31),
      meetings: _schedule().meetings,
      confirmDestructive: false,
    );

    expect(cache.values, hasLength(1));
  });

  test('online results survive a local cache write failure', () async {
    final cache = _MemoryScheduleCache()..writeError = StateError('disk');
    final logger = _Logger();
    final gateway = CachedScheduleGateway(
      remote: _Gateway(schedule: _schedule()),
      cache: cache,
      currentUserId: () => 'user-1',
      logger: logger,
    );

    final result = await gateway.getSchedule('course-1');

    expect(result.meetings, hasLength(1));
    expect(logger.errorContexts, contains('schedule_cache_write'));
  });

  test('preserves the remote failure without a usable local copy', () async {
    final remoteError = StateError('offline');
    final caches = [
      _MemoryScheduleCache(),
      _MemoryScheduleCache()..readError = StateError('read'),
      _MemoryScheduleCache()..values['user-1/course-1'] = '{invalid',
      _MemoryScheduleCache()
        ..values['user-1/course-1'] = '{invalid'
        ..removeError = StateError('remove'),
    ];

    for (final cache in caches) {
      final gateway = CachedScheduleGateway(
        remote: _Gateway(error: remoteError),
        cache: cache,
        currentUserId: () => 'user-1',
        logger: _Logger(),
      );
      await expectLater(
        gateway.getSchedule('course-1'),
        throwsA(same(remoteError)),
      );
    }
  });

  test('does not expose a saved schedule without its authenticated user', () {
    final error = StateError('offline');
    final gateway = CachedScheduleGateway(
      remote: _Gateway(error: error),
      cache: _MemoryScheduleCache(),
      currentUserId: () => null,
      logger: _Logger(),
    );

    expect(gateway.getSchedule('course-1'), throwsA(same(error)));
  });

  test('shared preferences separates and removes schedule copies', () async {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
    final cache = SharedPreferencesScheduleCache();

    await cache.write('user-1', 'course-1', 'schedule');

    expect(await cache.read('user-1', 'course-1'), 'schedule');
    expect(await cache.read('user-2', 'course-1'), isNull);
    expect(await cache.read('user-1', 'course-2'), isNull);
    await cache.remove('user-1', 'course-1');
    expect(await cache.read('user-1', 'course-1'), isNull);
  });
}

PythonSchedule _schedule() => PythonSchedule(
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
  meetings: [
    PythonMeeting.fromJson(const {
      'id': 'meeting-1',
      'weekday': 1,
      'start_minutes': 480,
      'end_minutes': 580,
      'lesson_count': 2,
      'call_count': 1,
      'created_at': '2026-07-01T12:00:00Z',
      'updated_at': '2026-07-01T12:00:00Z',
    }),
  ],
  changes: PythonScheduleChanges.fromJson(const {
    'meeting_upserts': 0,
    'meeting_deletes': 0,
    'session_upserts': 0,
    'session_deletes': 0,
    'destructive_deletes': 0,
  }),
);

final class _Gateway implements BackendScheduleGateway {
  _Gateway({this.schedule, this.error});

  final PythonSchedule? schedule;
  final Object? error;

  @override
  Future<PythonSchedule> getSchedule(String courseId) async {
    if (error case final value?) throw value;
    return schedule!;
  }

  @override
  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  }) async {
    if (error case final value?) throw value;
    return schedule!;
  }
}

final class _MemoryScheduleCache implements ScheduleCache {
  final values = <String, String>{};
  Object? readError;
  Object? writeError;
  Object? removeError;

  String _key(String userId, String courseId) => '$userId/$courseId';

  @override
  Future<String?> read(String userId, String courseId) async {
    if (readError case final error?) throw error;
    return values[_key(userId, courseId)];
  }

  @override
  Future<void> write(String userId, String courseId, String value) async {
    if (writeError case final error?) throw error;
    values[_key(userId, courseId)] = value;
  }

  @override
  Future<void> remove(String userId, String courseId) async {
    if (removeError case final error?) throw error;
    values.remove(_key(userId, courseId));
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
