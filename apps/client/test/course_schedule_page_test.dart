import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/course_schedule_page.dart';
import 'package:frequencia_ufmg/features/schedule/session_generator.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final now = DateTime.utc(2026, 9, 27, 12);
  final course = CourseRecord(
    id: 'poo',
    code: 'DCC203',
    name: 'POO',
    workload: 60,
    term: '2026-2',
    createdAt: now,
    updatedAt: now,
  );

  testWidgets('loads the authoritative preview and keeps writes disabled', (
    tester,
  ) async {
    final direct = _FakeMeetingRepository()
      ..listError = StateError('must not read');
    final gateway = _FakeScheduleGateway(
      course: course,
      meetings: [
        MeetingRecord(
          id: 'authoritative',
          weekday: DateTime.tuesday,
          startMinutes: 1140,
          endMinutes: 1240,
          lessonCount: QuantidadeAulas.two,
          callCount: NumeroChamadas.one,
          createdAt: now,
          updatedAt: now,
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: direct,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          scheduleGateway: gateway,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Terça-feira • 19:00–20:40'), findsOneWidget);
    expect(
      find.textContaining('A grade está em validação segura'),
      findsOneWidget,
    );
    expect(
      tester
          .widget<FloatingActionButton>(find.byKey(const Key('add-meeting')))
          .onPressed,
      isNull,
    );
    expect(gateway.getCount, 1);
    expect(gateway.saveCount, 0);
  });

  testWidgets(
    'saves a complete schedule only through the authoritative gateway',
    (tester) async {
      final dated = CourseRecord(
        id: course.id,
        code: course.code,
        name: course.name,
        workload: course.workload,
        term: course.term,
        startsOn: DateTime.utc(2026, 8, 3),
        endsOn: DateTime.utc(2026, 12, 1),
        createdAt: now,
        updatedAt: now,
      );
      final direct = _FakeMeetingRepository();
      final gateway = _FakeScheduleGateway(course: dated);
      await tester.pumpWidget(
        MaterialApp(
          home: CourseSchedulePage(
            course: dated,
            repository: direct,
            sessionRepository: _FakeSessionRepository(),
            logger: _RecordingAppLogger(),
            scheduleGateway: gateway,
            scheduleWritesEnabled: true,
            idGenerator: () => 'monday-8',
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('add-meeting')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
      await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
      await tester.pumpAndSettle();

      expect(gateway.saveCount, 1);
      expect(gateway.meetings.single.id, 'monday-8');
      expect(direct.meetings, isEmpty);
      expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);
    },
  );

  testWidgets('shows an authoritative overlap as a validation error', (
    tester,
  ) async {
    final dated = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 8, 3),
      endsOn: DateTime.utc(2026, 12, 1),
      createdAt: now,
      updatedAt: now,
    );
    final gateway = _FakeScheduleGateway(course: dated)
      ..saveError = const PythonBackendException(
        PythonBackendError.scheduleConflict,
      );
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: dated,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          scheduleGateway: gateway,
          scheduleWritesEnabled: true,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Esse horário se sobrepõe a outra aula cadastrada.'),
      findsOneWidget,
    );
  });

  testWidgets('deletes a meeting through the authoritative gateway', (
    tester,
  ) async {
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final gateway = _FakeScheduleGateway(course: course, meetings: [meeting]);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          scheduleGateway: gateway,
          scheduleWritesEnabled: true,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();

    expect(gateway.meetings, isEmpty);
    expect(find.text('Nenhum horário cadastrado'), findsOneWidget);
  });

  testWidgets('saves a visual period through the authoritative gateway', (
    tester,
  ) async {
    final gateway = _FakeScheduleGateway(course: course);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          scheduleGateway: gateway,
          scheduleWritesEnabled: true,
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('edit-course-period')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-03')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-10')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
    await tester.pumpAndSettle();

    expect(gateway.startsOn, DateTime.utc(2026, 8, 3));
    expect(gateway.endsOn, DateTime.utc(2026, 8, 10));
    expect(find.text('Período salvo e calendário atualizado.'), findsOneWidget);
  });

  testWidgets('asks before an authoritative destructive replacement', (
    tester,
  ) async {
    final dated = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 8, 3),
      endsOn: DateTime.utc(2026, 12, 1),
      createdAt: now,
      updatedAt: now,
    );
    final gateway = _FakeScheduleGateway(course: dated)..destructiveCount = 1;
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: dated,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          scheduleGateway: gateway,
          scheduleWritesEnabled: true,
          idGenerator: () => 'monday-8',
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    Future<void> submit() async {
      await tester.tap(find.byKey(const Key('add-meeting')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
      await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
      await tester.pump(const Duration(milliseconds: 300));
    }

    await submit();
    await tester.tap(find.widgetWithText(TextButton, 'Manter como está'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
    await tester.pumpAndSettle();
    expect(gateway.confirmations, [false]);

    await submit();
    await tester.tap(find.widgetWithText(FilledButton, 'Alterar mesmo assim'));
    await tester.pumpAndSettle();

    expect(gateway.confirmations, [false, false, true]);
    expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);
  });

  testWidgets('creates, edits, lists, and deletes a weekly meeting', (
    tester,
  ) async {
    final repository = _FakeMeetingRepository();
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          now: () => now,
          idGenerator: () => 'meeting-1',
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.meetings.single.id, 'meeting-1');
    expect(repository.meetings.single.weekday, DateTime.monday);
    expect(repository.meetings.single.startMinutes, 480);
    expect(repository.meetings.single.endMinutes, 580);
    expect(repository.meetings.single.lessonCount, QuantidadeAulas.two);
    expect(repository.meetings.single.callCount, NumeroChamadas.one);
    expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);
    expect(find.text('2 aulas • 1 chamada'), findsOneWidget);

    await tester.tap(find.byTooltip('Editar horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meeting-weekday')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Terça-feira').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '10:00');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('4 aulas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meeting-calls')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('2 chamadas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.meetings.single.startMinutes, 600);
    expect(repository.meetings.single.weekday, DateTime.tuesday);
    expect(repository.meetings.single.endMinutes, 800);
    expect(repository.meetings.single.lessonCount, QuantidadeAulas.four);
    expect(repository.meetings.single.callCount, NumeroChamadas.two);
    expect(find.text('Terça-feira • 10:00–13:20'), findsOneWidget);

    await tester.tap(find.byTooltip('Excluir horário de terça-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();

    expect(repository.meetings, isEmpty);
    expect(find.text('Nenhum horário cadastrado'), findsOneWidget);
  });

  testWidgets('validates time, configuration, and duplicate weekly slots', (
    tester,
  ) async {
    final existing = MeetingRecord(
      id: 'existing',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(meetings: [existing]);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          now: () => now,
          idGenerator: () => 'new-meeting',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('meeting-start')), '25:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use um horário válido no formato HH:MM.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Esse horário se sobrepõe a outra aula cadastrada.'),
      findsOneWidget,
    );
    expect(repository.meetings, [existing]);
  });

  testWidgets('recovers from loading and persistence failures', (tester) async {
    final existing = MeetingRecord(
      id: 'existing',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(meetings: [existing])
      ..listError = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível carregar a grade.'), findsOneWidget);

    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);

    repository.saveError = StateError('offline');
    await tester.tap(find.byTooltip('Editar horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível salvar o horário.'), findsOneWidget);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(repository.meetings, [existing]);

    repository.deleteError = StateError('offline');
    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível excluir o horário.'), findsOneWidget);
    expect(repository.meetings, [existing]);
  });

  testWidgets('handles late endings, one lesson, sorting, and default ids', (
    tester,
  ) async {
    final tuesday = MeetingRecord(
      id: 'tuesday',
      weekday: DateTime.tuesday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final mondayLate = MeetingRecord(
      id: 'monday-late',
      weekday: DateTime.monday,
      startMinutes: 600,
      endMinutes: 700,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final mondayEarly = MeetingRecord(
      id: 'monday-early',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(
      meetings: [tuesday, mondayLate, mondayEarly],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final earlyY = tester
        .getTopLeft(find.text('Segunda-feira • 08:00–09:40'))
        .dy;
    final lateY = tester
        .getTopLeft(find.text('Segunda-feira • 10:00–11:40'))
        .dy;
    final tuesdayY = tester
        .getTopLeft(find.text('Terça-feira • 08:00–09:40'))
        .dy;
    expect(earlyY, lessThan(lateY));
    expect(lateY, lessThan(tuesdayY));

    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:99');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use um horário válido no formato HH:MM.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '23:30');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('4 aulas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('O horário termina depois da meia-noite.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '14:00');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('1 aula').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    final created = repository.meetings.singleWhere(
      (meeting) => meeting.startMinutes == 840,
    );
    expect(created.id, isNotEmpty);
    expect(created.lessonCount, QuantidadeAulas.one);
    expect(created.callCount, NumeroChamadas.one);
    expect(created.endMinutes, 890);
  });

  testWidgets('saves a visual period and reconciles sessions automatically', (
    tester,
  ) async {
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final meetingRepository = _FakeMeetingRepository(meetings: [meeting]);
    final sessionRepository = _FakeSessionRepository();
    final courseRepository = _FakeCourseRepository(course);
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          courseRepository: courseRepository,
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: logger,
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Gerar sessões'), findsNothing);
    await tester.tap(find.byKey(const Key('edit-course-period')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-03')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-10')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
    await tester.pumpAndSettle();

    expect(sessionRepository.sessions, hasLength(2));
    expect(courseRepository.saved.startsOn, DateTime.utc(2026, 8, 3));
    expect(courseRepository.saved.endsOn, DateTime.utc(2026, 8, 10));
    expect(find.text('03/08/2026 – 10/08/2026'), findsOneWidget);
    expect(find.text('Período salvo e calendário atualizado.'), findsOneWidget);
    expect(
      logger.events,
      containsAllInOrder([
        'session_generation_started',
        'session_generation_succeeded',
      ]),
    );

    await tester.tap(find.byKey(const Key('edit-course-period')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-17')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-08-24')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
    await tester.pumpAndSettle();
    expect(sessionRepository.sessions, hasLength(2));
    expect(
      sessionRepository.sessions.map((item) => item.id),
      containsAll(['2026-08-17--monday-8', '2026-08-24--monday-8']),
    );
    expect(
      sessionRepository.sessions.map((item) => item.id),
      isNot(contains('2026-08-03--monday-8')),
    );
  });

  testWidgets('cancels the visual period picker without changing data', (
    tester,
  ) async {
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final courseRepository = _FakeCourseRepository(course);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          courseRepository: courseRepository,
          repository: _FakeMeetingRepository(meetings: [meeting]),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('edit-course-period')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(courseRepository.saveCount, 0);
    expect(find.text('Definir'), findsOneWidget);
  });

  testWidgets('protects recorded attendance when the period changes', (
    tester,
  ) async {
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final datedCourse = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 10, 5),
      endsOn: DateTime.utc(2026, 10, 5),
      createdAt: now,
      updatedAt: now,
    );
    final recorded = SessionGenerator(location)
        .reconcile(
          meetings: [meeting],
          existingSessions: const [],
          startDate: datedCourse.startsOn!,
          endDate: datedCourse.endsOn!,
          now: now,
        )
        .upserts
        .single;
    final sessionRepository = _FakeSessionRepository()
      ..sessions.add(
        SessionRecord(
          id: recorded.id,
          startsAt: recorded.startsAt,
          endsAt: recorded.endsAt,
          lessonCount: recorded.lessonCount,
          callCount: recorded.callCount,
          attendanceStatus: SituacaoFrequencia.present,
          absences: 0,
          createdAt: recorded.createdAt,
          updatedAt: recorded.updatedAt,
        ),
      );
    final courseRepository = _FakeCourseRepository(datedCourse);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: datedCourse,
          courseRepository: courseRepository,
          repository: _FakeMeetingRepository(meetings: [meeting]),
          sessionRepository: sessionRepository,
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('edit-course-period')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-10-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('date-2026-10-12')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
    await tester.pumpAndSettle();
    expect(find.text('Há frequências registradas'), findsOneWidget);
    await tester.tap(find.text('Manter como está'));
    await tester.pumpAndSettle();
    expect(courseRepository.saveCount, 0);
    expect(sessionRepository.sessions.single.id, recorded.id);
  });

  testWidgets('updates and removes generated sessions with weekly meetings', (
    tester,
  ) async {
    final datedCourse = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 10, 5),
      endsOn: DateTime.utc(2026, 10, 5),
      createdAt: now,
      updatedAt: now,
    );
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final meetingRepository = _FakeMeetingRepository(meetings: [meeting]);
    final sessionRepository = _FakeSessionRepository()
      ..sessions.addAll(
        SessionGenerator(location)
            .reconcile(
              meetings: [meeting],
              existingSessions: const [],
              startDate: datedCourse.startsOn!,
              endDate: datedCourse.endsOn!,
              now: now,
            )
            .upserts,
      );
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: datedCourse,
          courseRepository: _FakeCourseRepository(datedCourse),
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Editar horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '10:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      sessionRepository.sessions.single.startsAt,
      tz.TZDateTime(location, 2026, 10, 5, 10).toUtc(),
    );

    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();
    expect(sessionRepository.sessions, isEmpty);
  });

  testWidgets('can confirm removal of recorded attendance', (tester) async {
    final datedCourse = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 10, 5),
      endsOn: DateTime.utc(2026, 10, 5),
      createdAt: now,
      updatedAt: now,
    );
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final generated = SessionGenerator(location)
        .reconcile(
          meetings: [meeting],
          existingSessions: const [],
          startDate: datedCourse.startsOn!,
          endDate: datedCourse.endsOn!,
          now: now,
        )
        .upserts
        .single;
    final sessionRepository = _FakeSessionRepository()
      ..sessions.add(
        SessionRecord(
          id: generated.id,
          startsAt: generated.startsAt,
          endsAt: generated.endsAt,
          lessonCount: generated.lessonCount,
          callCount: generated.callCount,
          attendanceStatus: SituacaoFrequencia.present,
          absences: 0,
          createdAt: now,
          updatedAt: now,
        ),
      );
    final meetingRepository = _FakeMeetingRepository(meetings: [meeting]);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: datedCourse,
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('Alterar mesmo assim'));
    await tester.pumpAndSettle();
    expect(meetingRepository.meetings, isEmpty);
    expect(sessionRepository.sessions, isEmpty);
  });

  testWidgets('reports unavailable course persistence and save failures', (
    tester,
  ) async {
    Future<void> chooseOneDay() async {
      await tester.tap(find.byKey(const Key('edit-course-period')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('date-2026-09-28')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('date-2026-09-28')));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
      await tester.pumpAndSettle();
    }

    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await chooseOneDay();
    expect(find.text('Não foi possível salvar o período.'), findsOneWidget);

    final courseRepository = _FakeCourseRepository(course)
      ..saveError = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          courseRepository: courseRepository,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await chooseOneDay();
    expect(
      find.text('Não foi possível salvar o período e atualizar o calendário.'),
      findsOneWidget,
    );
  });

  testWidgets('opens the calendar exceptions for the selected course', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Exceções de calendário');
    await tester.pumpAndSettle();
    expect(find.text('Exceções de calendário'), findsOneWidget);
    expect(find.text('Nenhuma sessão gerada'), findsOneWidget);
  });

  testWidgets('opens manual attendance for the selected course', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Registrar frequência');
    await tester.pumpAndSettle();
    expect(find.text('Frequência • DCC203'), findsOneWidget);
  });

  testWidgets('opens the general calendar filtered by the selected course', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Ver calendário');
    await tester.pumpAndSettle();
    expect(find.text('Calendário operacional'), findsOneWidget);
    expect(
      tester
          .widget<DropdownButtonFormField<String?>>(
            find.byKey(const Key('calendar-course-filter')),
          )
          .initialValue,
      'poo',
    );
  });

  testWidgets('rejects partial overlap with a different course', (
    tester,
  ) async {
    final other = MeetingRecord(
      id: 'calculus',
      weekday: DateTime.monday,
      startMinutes: 450,
      endMinutes: 510,
      lessonCount: QuantidadeAulas.one,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _MultiCourseMeetingRepository({
      'math': [other],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          allCourseIds: const ['poo', 'math'],
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Esse horário se sobrepõe a outra aula cadastrada.'),
      findsOneWidget,
    );
  });

  testWidgets('reports a background calendar synchronization failure', (
    tester,
  ) async {
    final datedCourse = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: DateTime.utc(2026, 8, 3),
      endsOn: DateTime.utc(2026, 8, 3),
      createdAt: now,
      updatedAt: now,
    );
    final sessions = _FakeSessionRepository()
      ..saveError = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: datedCourse,
          repository: _FakeMeetingRepository(),
          sessionRepository: sessions,
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => now,
          idGenerator: () => 'monday-8',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text(
        'Horário salvo, mas não foi possível sincronizar o calendário.',
      ),
      findsOneWidget,
    );
  });
}

Future<void> _chooseScheduleAction(WidgetTester tester, String label) async {
  await tester.tap(find.byTooltip('Ações da disciplina'));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).last);
}

final class _FakeCourseRepository implements CourseRepository {
  _FakeCourseRepository(this.saved);

  CourseRecord saved;
  int saveCount = 0;
  Object? saveError;

  @override
  Future<void> deleteCourse(String courseId) async {}

  @override
  Future<List<CourseRecord>> listCourses() async => [saved];

  @override
  Future<void> saveCourse(CourseRecord course) async {
    if (saveError case final error?) throw error;
    saved = course;
    saveCount++;
  }
}

final class _FakeMeetingRepository implements MeetingRepository {
  _FakeMeetingRepository({List<MeetingRecord>? meetings})
    : meetings = meetings ?? [];

  final List<MeetingRecord> meetings;
  Object? listError;
  Object? saveError;
  Object? deleteError;

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {
    if (deleteError case final error?) throw error;
    meetings.removeWhere((meeting) => meeting.id == meetingId);
  }

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async {
    if (listError case final error?) throw error;
    return List.of(meetings);
  }

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {
    if (saveError case final error?) throw error;
    meetings.removeWhere((item) => item.id == meeting.id);
    meetings.add(meeting);
  }
}

final class _MultiCourseMeetingRepository implements MeetingRepository {
  _MultiCourseMeetingRepository(this.byCourse);

  final Map<String, List<MeetingRecord>> byCourse;

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {}

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async =>
      List.of(byCourse[courseId] ?? const []);

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {
    byCourse.putIfAbsent(courseId, () => []).add(meeting);
  }
}

final class _FakeSessionRepository implements SessionRepository {
  final sessions = <SessionRecord>[];
  Object? listError;
  Object? saveError;

  @override
  Future<void> deleteSession(String courseId, String sessionId) async {
    sessions.removeWhere((session) => session.id == sessionId);
  }

  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    if (listError case final error?) throw error;
    return List.of(sessions);
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {
    if (saveError case final error?) throw error;
    sessions.removeWhere((item) => item.id == session.id);
    sessions.add(session);
  }
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

final class _FakeScheduleGateway implements BackendScheduleGateway {
  _FakeScheduleGateway({required this.course, List<MeetingRecord>? meetings})
    : meetings = meetings ?? [];

  CourseRecord course;
  List<MeetingRecord> meetings;
  int getCount = 0;
  int saveCount = 0;
  int? destructiveCount;
  Object? saveError;
  DateTime? startsOn;
  DateTime? endsOn;
  final confirmations = <bool>[];

  @override
  Future<PythonSchedule> getSchedule(String courseId) async {
    getCount++;
    return _schedule();
  }

  @override
  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  }) async {
    saveCount++;
    if (saveError case final error?) throw error;
    confirmations.add(confirmDestructive);
    if (!confirmDestructive && destructiveCount != null) {
      throw PythonBackendException(
        PythonBackendError.destructiveConflict,
        destructiveSessions: destructiveCount,
      );
    }
    this.startsOn = startsOn;
    this.endsOn = endsOn;
    course = CourseRecord(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: startsOn,
      endsOn: endsOn,
      createdAt: course.createdAt,
      updatedAt: course.updatedAt,
    );
    this.meetings = meetings
        .map(
          (item) => MeetingRecord(
            id: item.id,
            weekday: item.weekday,
            startMinutes: item.startMinutes,
            endMinutes: item.endMinutes,
            lessonCount: QuantidadeAulas.fromValue(item.lessonCount),
            callCount: NumeroChamadas.fromValue(item.callCount),
            createdAt: item.createdAt,
            updatedAt: item.updatedAt,
          ),
        )
        .toList(growable: false);
    return _schedule();
  }

  PythonSchedule _schedule() => PythonSchedule(
    course: PythonCourse(
      id: course.id,
      code: course.code,
      name: course.name,
      workload: course.workload,
      term: course.term,
      startsOn: course.startsOn,
      endsOn: course.endsOn,
      createdAt: course.createdAt,
      updatedAt: course.updatedAt,
    ),
    meetings: meetings
        .map(
          (item) => PythonMeeting(
            id: item.id,
            weekday: item.weekday,
            startMinutes: item.startMinutes,
            endMinutes: item.endMinutes,
            lessonCount: item.lessonCount.value,
            callCount: item.callCount.value,
            createdAt: item.createdAt,
            updatedAt: item.updatedAt,
          ),
        )
        .toList(growable: false),
    changes: const PythonScheduleChanges(
      meetingUpserts: 0,
      meetingDeletes: 0,
      sessionUpserts: 0,
      sessionDeletes: 0,
      destructiveDeletes: 0,
    ),
  );
}
