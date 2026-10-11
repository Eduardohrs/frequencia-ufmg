import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/repository_academic_overview.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  test('loads every course session collection in parallel', () async {
    final logger = _Logger();
    final sessions = _Sessions();
    final repository = RepositoryAcademicOverviewRepository(
      courseRepository: _Courses(),
      sessionRepository: sessions,
      logger: logger,
    );

    final pending = repository.loadOverview();
    await Future<void>.delayed(Duration.zero);

    expect(sessions.started, {'course-1', 'course-2'});
    sessions.complete('course-1');
    sessions.complete('course-2');
    final snapshot = await pending;

    expect(snapshot.courses.map((course) => course.id), [
      'course-1',
      'course-2',
    ]);
    expect(snapshot.sessionsByCourse.keys, {'course-1', 'course-2'});
    expect(logger.events, [
      'academic_overview_load_started',
      'academic_overview_load_succeeded',
    ]);
  });

  test('resolves repositories for the current authenticated user', () async {
    final users = <String>[];
    final sessions = _ImmediateSessions();
    final repository = CurrentUserAcademicOverviewRepository(
      currentUserId: () => 'user-42',
      courseRepositoryFor: (userId) {
        users.add('courses:$userId');
        return _Courses();
      },
      sessionRepositoryFor: (userId) {
        users.add('sessions:$userId');
        return sessions;
      },
      logger: _Logger(),
    );

    final snapshot = await repository.loadOverview();

    expect(users, ['courses:user-42', 'sessions:user-42']);
    expect(snapshot.sessionsByCourse['course-1'], hasLength(1));
  });

  test('rejects an overview load without an authenticated user', () {
    final repository = CurrentUserAcademicOverviewRepository(
      currentUserId: () => null,
      courseRepositoryFor: (_) => throw UnimplementedError(),
      sessionRepositoryFor: (_) => throw UnimplementedError(),
      logger: _Logger(),
    );

    expect(repository.loadOverview, throwsStateError);
  });

  test('keeps direct overview reads within the aggregate contract', () async {
    final tooManyCourses = RepositoryAcademicOverviewRepository(
      courseRepository: _Courses(
        List.generate(51, (index) => _course('course-$index')),
      ),
      sessionRepository: _ImmediateSessions(),
      logger: _Logger(),
    );
    final tooManySessions = RepositoryAcademicOverviewRepository(
      courseRepository: _Courses([_course('course-1')]),
      sessionRepository: _LargeSessionRepository(),
      logger: _Logger(),
    );

    await expectLater(tooManyCourses.loadOverview(), throwsStateError);
    await expectLater(tooManySessions.loadOverview(), throwsStateError);
  });
}

CourseRecord _course(String id) => CourseRecord(
  id: id,
  code: id.toUpperCase(),
  name: id,
  workload: 1,
  term: '2026-2',
  createdAt: DateTime.utc(2026, 7),
  updatedAt: DateTime.utc(2026, 7),
);

SessionRecord _session(String id) => SessionRecord(
  id: id,
  startsAt: DateTime.utc(2026, 8, 3, 11),
  endsAt: DateTime.utc(2026, 8, 3, 12, 40),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  createdAt: DateTime.utc(2026, 7),
  updatedAt: DateTime.utc(2026, 7),
);

final class _Courses implements CourseRepository {
  _Courses([List<CourseRecord>? courses])
    : courses = courses ?? [_course('course-1'), _course('course-2')];

  final List<CourseRecord> courses;

  @override
  Future<List<CourseRecord>> listCourses() async => courses;

  @override
  Future<void> saveCourse(CourseRecord course) => throw UnimplementedError();

  @override
  Future<void> deleteCourse(String courseId) => throw UnimplementedError();
}

final class _Sessions implements SessionRepository {
  final started = <String>{};
  final _completers = <String, Completer<List<SessionRecord>>>{};

  void complete(String courseId) =>
      _completers[courseId]!.complete([_session('session-$courseId')]);

  @override
  Future<List<SessionRecord>> listSessions(String courseId) {
    started.add(courseId);
    return (_completers[courseId] ??= Completer<List<SessionRecord>>()).future;
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) =>
      throw UnimplementedError();

  @override
  Future<void> deleteSession(String courseId, String sessionId) =>
      throw UnimplementedError();
}

final class _ImmediateSessions implements SessionRepository {
  @override
  Future<List<SessionRecord>> listSessions(String courseId) async => [
    _session('session-$courseId'),
  ];

  @override
  Future<void> saveSession(String courseId, SessionRecord session) =>
      throw UnimplementedError();

  @override
  Future<void> deleteSession(String courseId, String sessionId) =>
      throw UnimplementedError();
}

final class _LargeSessionRepository implements SessionRepository {
  @override
  Future<List<SessionRecord>> listSessions(String courseId) async =>
      List.generate(501, (index) => _session('session-$index'));

  @override
  Future<void> saveSession(String courseId, SessionRecord session) =>
      throw UnimplementedError();

  @override
  Future<void> deleteSession(String courseId, String sessionId) =>
      throw UnimplementedError();
}

final class _Logger implements AppLogger {
  final events = <String>[];

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
  }) async {}
}
