import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/document_store.dart';
import 'package:frequencia_ufmg/features/courses/course_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:timezone/data/latest.dart' as tz_data;

void main() {
  tz_data.initializeTimeZones();
  final user = AuthUser(
    id: 'user-1',
    email: 'eduardo@ufmg.br',
    displayName: 'Eduardo',
  );
  final now = DateTime.utc(2026, 9, 27, 12);

  test('derives the academic term from the calendar half-year', () {
    expect(academicTermFor(DateTime(2026, 1, 1)), '2026-1');
    expect(academicTermFor(DateTime(2026, 6, 30)), '2026-1');
    expect(academicTermFor(DateTime(2026, 7, 1)), '2026-2');
    expect(academicTermFor(DateTime(2026, 12, 31)), '2026-2');
  });

  testWidgets('shows loading, empty state, and reloads after an error', (
    tester,
  ) async {
    final repository = _FakeCourseRepository()
      ..listError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível carregar suas disciplinas.'),
      findsOneWidget,
    );
    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();

    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
    expect(find.text('Adicionar disciplina'), findsNWidgets(2));
  });

  testWidgets('creates, edits, and deletes a course', (tester) async {
    final repository = _FakeCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
    await tester.enterText(
      find.byKey(const Key('course-name')),
      'Programação Orientada a Objetos',
    );
    await tester.enterText(find.byKey(const Key('course-workload')), '60');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.id, 'course-1');
    expect(repository.courses.single.term, '2026-2');
    expect(repository.courses.single.startsOn, DateTime.utc(2026, 7));
    expect(repository.courses.single.endsOn, DateTime.utc(2026, 12, 31));
    expect(repository.courses.single.createdAt, now);
    expect(find.text('DCC203'), findsOneWidget);
    expect(find.text('Programação Orientada a Objetos'), findsOneWidget);
    expect(find.text('60 horas-aula • 2026-2'), findsOneWidget);

    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-name')), 'POO');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.name, 'POO');
    expect(repository.courses.single.createdAt, now);
    expect(repository.courses.single.updatedAt, now);
    expect(find.text('POO'), findsOneWidget);

    await tester.tap(find.byTooltip('Excluir DCC203'));
    await tester.pumpAndSettle();
    expect(find.text('Excluir disciplina?'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
    await tester.pumpAndSettle();
    expect(repository.courses, hasLength(1));

    await tester.tap(find.byTooltip('Excluir DCC203'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();

    expect(repository.courses, isEmpty);
    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
  });

  testWidgets('creates a distinct course when another course already exists', (
    tester,
  ) async {
    final existing = CourseRecord(
      id: 'existing-course',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [existing]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: logger,
          onSignOut: () async {},
          now: () => now,
          idGenerator: () => 'new-course',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _fillNewCourse(tester, code: 'DCC204', name: 'Algoritmos');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, hasLength(2));
    expect(repository.courses.map((course) => course.id), {
      'existing-course',
      'new-course',
    });
    expect(
      logger.events,
      containsAllInOrder([
        'course_create_editor_opened',
        'course_create_started',
        'course_create_succeeded',
      ]),
    );
  });

  testWidgets('rejects duplicate course codes ignoring letter case', (
    tester,
  ) async {
    final existing = CourseRecord(
      id: 'existing-course',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [existing]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester, code: 'dcc203', name: 'Outra disciplina');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, [existing]);
    expect(
      find.text('Já existe uma disciplina com o código DCC203.'),
      findsOneWidget,
    );
    expect(logger.events, contains('course_create_duplicate_code'));
  });

  testWidgets('hides the automatic term on creation and allows editing it', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-term')), findsNothing);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-term')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('course-term')), '2027-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.term, '2027-1');
  });

  testWidgets('rejects editing a course outside current or next term', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-term')), '2026-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Escolha o período atual (2026-2) ou o próximo (2027-1).'),
      findsOneWidget,
    );
    expect(repository.courses.single.term, '2026-2');
  });

  testWidgets('preserves a custom date range while editing metadata', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      startsOn: DateTime.utc(2026, 8, 3),
      endsOn: DateTime.utc(2026, 11, 30),
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-name')), 'POO editada');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.startsOn, DateTime.utc(2026, 8, 3));
    expect(repository.courses.single.endsOn, DateTime.utc(2026, 11, 30));
  });

  testWidgets('moves untouched default dates when the term changes', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      startsOn: DateTime.utc(2026, 7),
      endsOn: DateTime.utc(2026, 12, 31),
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-term')), '2027-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.startsOn, DateTime.utc(2027));
    expect(repository.courses.single.endsOn, DateTime.utc(2027, 6, 30));
  });

  testWidgets('deletes expired previous courses on the first load', (
    tester,
  ) async {
    final expired = CourseRecord(
      id: 'old-course',
      code: 'DCC100',
      name: 'Antiga',
      workload: 60,
      term: '2026-1',
      startsOn: DateTime.utc(2026),
      endsOn: DateTime.utc(2026, 6, 30),
      createdAt: DateTime.utc(2026),
      updatedAt: DateTime.utc(2026),
    );
    final current = CourseRecord(
      id: 'current-course',
      code: 'DCC203',
      name: 'Atual',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [expired, current]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();

    expect(repository.deletedIds, ['old-course']);
    expect(find.text('DCC100'), findsNothing);
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('keeps an expired course visible when automatic cleanup fails', (
    tester,
  ) async {
    final expired = CourseRecord(
      id: 'old-course',
      code: 'DCC100',
      name: 'Antiga',
      workload: 60,
      term: '2026-1',
      startsOn: DateTime.utc(2026),
      endsOn: DateTime.utc(2026, 6, 30),
      createdAt: DateTime.utc(2026),
      updatedAt: DateTime.utc(2026),
    );
    final repository = _FakeCourseRepository(courses: [expired])
      ..deleteError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();

    expect(find.text('DCC100'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('opens the selected course weekly schedule', (tester) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);
    final meetingRepository = _FakeMeetingRepository();

    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: repository,
          meetingRepository: meetingRepository,
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Horários DCC203'));
    await tester.pumpAndSettle();

    expect(find.text('Grade • DCC203'), findsOneWidget);
    expect(meetingRepository.listedCourseIds, ['course-1']);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('opens and closes the side navigation and general calendar', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    tester.state<ScaffoldState>(find.byType(Scaffold)).openDrawer();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('nav-courses')));
    await tester.pumpAndSettle();
    expect(find.byType(Drawer), findsNothing);

    tester.state<ScaffoldState>(find.byType(Scaffold)).openDrawer();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('nav-absence-dashboard')));
    await tester.pumpAndSettle();
    expect(find.text('Faltas restantes'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    tester.state<ScaffoldState>(find.byType(Scaffold)).openDrawer();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('nav-general-calendar')));
    await tester.pumpAndSettle();
    expect(find.text('Calendário acadêmico'), findsOneWidget);
  });

  testWidgets('rejects changing a course to another existing code', (
    tester,
  ) async {
    final first = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final second = CourseRecord(
      id: 'course-2',
      code: 'DCC204',
      name: 'Algoritmos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [first, second]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC204'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'dcc203');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, [first, second]);
    expect(
      find.text('Já existe uma disciplina com o código DCC203.'),
      findsOneWidget,
    );
    expect(logger.events, contains('course_update_duplicate_code'));
  });

  testWidgets('validates fields and keeps the form open', (tester) async {
    final repository = _FakeCourseRepository();
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.text('Informe o código.'), findsOneWidget);
    expect(find.text('Informe o nome.'), findsOneWidget);
    expect(find.text('Use um número maior que zero.'), findsOneWidget);
    expect(repository.courses, isEmpty);
    expect(logger.events, contains('course_create_validation_failed'));

    await tester.enterText(find.byKey(const Key('course-code')), 'x' * 33);
    await tester.enterText(find.byKey(const Key('course-name')), 'x' * 161);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Use no máximo 32 caracteres.'), findsOneWidget);
    expect(find.text('Use no máximo 160 caracteres.'), findsOneWidget);

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-code')), findsNothing);
  });

  testWidgets('reports save and delete failures without losing data', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'poo',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final otherCourse = CourseRecord(
      id: 'algorithms',
      code: 'DCC204',
      name: 'Algoritmos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course, otherCourse])
      ..saveError = FirebaseException(
        plugin: 'cloud_firestore',
        code: 'permission-denied',
      )
      ..deleteError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Código: permission-denied'), findsOneWidget);

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Excluir DCC203'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível excluir a disciplina.'), findsOneWidget);
    expect(repository.courses, [course, otherCourse]);
  });

  testWidgets('exposes account details and logout action', (tester) async {
    final repository = _FakeCourseRepository();
    var logoutCalls = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async => logoutCalls++,
          now: () => now,
          idGenerator: () => 'course-1',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Olá, Eduardo'), findsOneWidget);
    expect(find.text('eduardo@ufmg.br'), findsOneWidget);
    await tester.tap(find.byTooltip('Sair'));
    await tester.pumpAndSettle();
    expect(logoutCalls, 1);
  });

  testWidgets('fits a phone viewport and generates an identifier by default', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();
    await tester.binding.setSurfaceSize(const Size(320, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Adicionar'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'DCC204');
    await tester.enterText(find.byKey(const Key('course-name')), 'Algoritmos');
    await tester.enterText(find.byKey(const Key('course-workload')), '60');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.id, isNotEmpty);
    expect(repository.courses.single.createdAt.isUtc, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('saving reaches Firestore when analytics delivery stalls', (
    tester,
  ) async {
    final store = _RecordingDocumentStore();
    final logger = _SelectivelyBlockingLogger('firestore_course_save_started');
    final repository = FirestoreCourseRepository(
      userId: user.id,
      store: store,
      logger: logger,
    );

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
    await tester.enterText(find.byKey(const Key('course-name')), 'POO');
    await tester.enterText(find.byKey(const Key('course-workload')), '60');
    await tester.tap(find.text('Salvar'));
    await tester.pump();

    final reachedFirestoreBeforeAnalytics = store.savedPaths.isNotEmpty;
    logger.release();
    await tester.pumpAndSettle();

    expect(reachedFirestoreBeforeAnalytics, isTrue);
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('stops saving when course creation throws unexpectedly', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();

    await tester.pumpWidget(
      MaterialApp(
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
          idGenerator: () => throw StateError('identifier unavailable'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('Não foi possível salvar a disciplina.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Salvar'), findsOneWidget);
  });

  testWidgets('closes the editor after saving without waiting for a reload', (
    tester,
  ) async {
    final repository = _ReloadBlockingCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(repository.savedCourse?.code, 'DCC203');
    expect(find.byKey(const Key('course-code')), findsNothing);
    expect(find.text('DCC203'), findsOneWidget);
  });
}

Future<void> _fillNewCourse(
  WidgetTester tester, {
  String code = 'DCC203',
  String name = 'POO',
}) async {
  await tester.tap(find.byKey(const Key('add-course')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('course-code')), code);
  await tester.enterText(find.byKey(const Key('course-name')), name);
  await tester.enterText(find.byKey(const Key('course-workload')), '60');
}

Widget _app(
  CourseRepository repository,
  AuthUser user,
  DateTime now, {
  AppLogger? logger,
}) => MaterialApp(
  home: CoursePage(
    repository: repository,
    meetingRepository: _FakeMeetingRepository(),
    sessionRepository: _FakeSessionRepository(),
    user: user,
    logger: logger ?? _RecordingAppLogger(),
    onSignOut: () async {},
    now: () => now,
    idGenerator: () => 'course-1',
  ),
);

final class _FakeCourseRepository implements CourseRepository {
  _FakeCourseRepository({List<CourseRecord>? courses})
    : courses = courses ?? [];

  final List<CourseRecord> courses;
  final deletedIds = <String>[];
  Object? listError;
  Object? saveError;
  Object? deleteError;

  @override
  Future<void> deleteCourse(String courseId) async {
    if (deleteError case final error?) throw error;
    deletedIds.add(courseId);
    courses.removeWhere((course) => course.id == courseId);
  }

  @override
  Future<List<CourseRecord>> listCourses() async {
    if (listError case final error?) throw error;
    return List.of(courses);
  }

  @override
  Future<void> saveCourse(CourseRecord course) async {
    if (saveError case final error?) throw error;
    courses.removeWhere((item) => item.id == course.id);
    courses.add(course);
  }
}

final class _FakeMeetingRepository implements MeetingRepository {
  final listedCourseIds = <String>[];

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {}

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async {
    listedCourseIds.add(courseId);
    return [];
  }

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {}
}

final class _FakeSessionRepository implements SessionRepository {
  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}

  @override
  Future<List<SessionRecord>> listSessions(String courseId) async => [];

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {}
}

final class _RecordingDocumentStore implements DocumentStore {
  final savedPaths = <String>[];
  final documents = <StoredDocument>[];

  @override
  Future<void> deleteAll(Iterable<String> documentPaths) async {}

  @override
  Future<List<StoredDocument>> list(String collectionPath) async =>
      List.of(documents);

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) async {
    savedPaths.add(documentPath);
    documents
      ..clear()
      ..add(StoredDocument(id: documentPath.split('/').last, data: data));
  }
}

final class _ReloadBlockingCourseRepository implements CourseRepository {
  CourseRecord? savedCourse;
  var _listCalls = 0;

  @override
  Future<void> deleteCourse(String courseId) async {}

  @override
  Future<List<CourseRecord>> listCourses() {
    _listCalls++;
    if (_listCalls == 1) return Future.value([]);
    return Completer<List<CourseRecord>>().future;
  }

  @override
  Future<void> saveCourse(CourseRecord course) async {
    savedCourse = course;
  }
}

final class _SelectivelyBlockingLogger implements AppLogger {
  _SelectivelyBlockingLogger(this.blockedEvent);

  final String blockedEvent;
  final Completer<void> _delivery = Completer<void>();

  void release() => _delivery.complete();

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (name == blockedEvent) await _delivery.future;
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

final class _RecordingAppLogger implements AppLogger {
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
