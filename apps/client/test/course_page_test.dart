import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/document_store.dart';
import 'package:frequencia_ufmg/features/courses/course_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  final user = AuthUser(
    id: 'user-1',
    email: 'eduardo@ufmg.br',
    displayName: 'Eduardo',
  );
  final now = DateTime.utc(2026, 9, 27, 12);

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
    await tester.enterText(find.byKey(const Key('course-term')), '2026-2');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.id, 'course-1');
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

  testWidgets('validates fields and keeps the form open', (tester) async {
    final repository = _FakeCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.text('Informe o código.'), findsOneWidget);
    expect(find.text('Informe o nome.'), findsOneWidget);
    expect(find.text('Use um número maior que zero.'), findsOneWidget);
    expect(find.text('Use o formato AAAA-S, como 2026-2.'), findsOneWidget);
    expect(repository.courses, isEmpty);

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
      ..saveError = StateError('offline')
      ..deleteError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Editar DCC203'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível salvar a disciplina.'), findsOneWidget);

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
          user: user,
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
          user: user,
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
    await tester.enterText(find.byKey(const Key('course-term')), '2026-2');
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
    await tester.enterText(find.byKey(const Key('course-term')), '2026-2');
    await tester.tap(find.text('Salvar'));
    await tester.pump();

    final reachedFirestoreBeforeAnalytics = store.savedPaths.isNotEmpty;
    logger.release();
    await tester.pumpAndSettle();

    expect(reachedFirestoreBeforeAnalytics, isTrue);
    expect(find.text('DCC203'), findsOneWidget);
  });
}

Widget _app(CourseRepository repository, AuthUser user, DateTime now) =>
    MaterialApp(
      home: CoursePage(
        repository: repository,
        user: user,
        onSignOut: () async {},
        now: () => now,
        idGenerator: () => 'course-1',
      ),
    );

final class _FakeCourseRepository implements CourseRepository {
  _FakeCourseRepository({List<CourseRecord>? courses})
    : courses = courses ?? [];

  final List<CourseRecord> courses;
  Object? listError;
  Object? saveError;
  Object? deleteError;

  @override
  Future<void> deleteCourse(String courseId) async {
    if (deleteError case final error?) throw error;
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
