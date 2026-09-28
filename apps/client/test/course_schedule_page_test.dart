import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
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

  testWidgets('generates only missing future sessions for a date range', (
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
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: logger,
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('generation-start-date')),
      '2026-08-03',
    );
    await tester.enterText(
      find.byKey(const Key('generation-end-date')),
      '2026-08-10',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();

    expect(sessionRepository.sessions, hasLength(2));
    expect(find.text('2 sessões criadas.'), findsOneWidget);
    expect(
      logger.events,
      containsAllInOrder([
        'session_generation_started',
        'session_generation_succeeded',
      ]),
    );

    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('generation-start-date')),
      '2026-08-03',
    );
    await tester.enterText(
      find.byKey(const Key('generation-end-date')),
      '2026-08-10',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();
    expect(sessionRepository.sessions, hasLength(2));
    expect(find.text('Nenhuma sessão nova para criar.'), findsOneWidget);
  });

  testWidgets('validates and cancels the generation date range', (
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
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(meetings: [meeting]),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use uma data válida no formato AAAA-MM-DD.'),
      findsNWidgets(2),
    );

    await tester.enterText(
      find.byKey(const Key('generation-start-date')),
      '2026-08-10',
    );
    await tester.enterText(
      find.byKey(const Key('generation-end-date')),
      '2026-08-03',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();
    expect(
      find.text('A data final deve ser igual ou posterior.'),
      findsOneWidget,
    );
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(find.text('Gerar sessões'), findsNothing);
  });

  testWidgets('reports empty schedules and generation failures', (
    tester,
  ) async {
    final meetingRepository = _FakeMeetingRepository();
    final sessionRepository = _FakeSessionRepository();
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: logger,
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    expect(
      find.text('Cadastre pelo menos um horário antes de gerar sessões.'),
      findsOneWidget,
    );

    meetingRepository.meetings.add(
      MeetingRecord(
        id: 'monday-8',
        weekday: DateTime.monday,
        startMinutes: 480,
        endMinutes: 580,
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.one,
        createdAt: now,
        updatedAt: now,
      ),
    );
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: meetingRepository,
          sessionRepository: sessionRepository,
          logger: logger,
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('generation-start-date')),
      '2026-08-03',
    );
    await tester.enterText(
      find.byKey(const Key('generation-end-date')),
      '2026-08-03',
    );
    sessionRepository.listError = StateError('offline');
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível gerar as sessões.'), findsOneWidget);
    expect(logger.events, contains('session_generation_failed'));
  });

  testWidgets('reports a single generated session', (tester) async {
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
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: _FakeMeetingRepository(meetings: [meeting]),
          sessionRepository: _FakeSessionRepository(),
          logger: _RecordingAppLogger(),
          generator: SessionGenerator(location),
          now: () => DateTime.utc(2026, 8, 1, 12),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _chooseScheduleAction(tester, 'Gerar sessões');
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('generation-start-date')),
      '2026-08-03',
    );
    await tester.enterText(
      find.byKey(const Key('generation-end-date')),
      '2026-08-03',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Gerar'));
    await tester.pumpAndSettle();
    expect(find.text('1 sessão criada.'), findsOneWidget);
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
    expect(find.text('Frequência por aula'), findsOneWidget);
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
    expect(find.text('Calendário acadêmico'), findsOneWidget);
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
}

Future<void> _chooseScheduleAction(WidgetTester tester, String label) async {
  await tester.tap(find.byTooltip('Ações da disciplina'));
  await tester.pumpAndSettle();
  await tester.tap(find.text(label).last);
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
