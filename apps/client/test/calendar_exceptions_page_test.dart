import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/calendar_exceptions_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final now = DateTime.utc(2026, 8, 1, 12);
  const courseId = 'poo';

  testWidgets('marks a session as cancelled or without roll call', (
    tester,
  ) async {
    final first = _session('first', DateTime.utc(2026, 8, 3, 11), now);
    final second = _session('second', DateTime.utc(2026, 8, 5, 11), now);
    final repository = _FakeSessionRepository([first, second]);
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: logger,
          location: location,
          now: () => now,
          idGenerator: () => 'makeup-1',
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Alterar sessão de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelada/feriado'));
    await tester.pumpAndSettle();

    expect(
      repository.byId('first').calendarStatus,
      SessionCalendarStatus.cancelled,
    );
    expect(
      repository.byId('second').calendarStatus,
      SessionCalendarStatus.scheduled,
    );
    expect(find.text('Cancelada/feriado'), findsOneWidget);
    expect(
      logger.events,
      containsAllInOrder([
        'calendar_exception_started',
        'calendar_exception_succeeded',
      ]),
    );

    await tester.tap(find.byTooltip('Alterar sessão de 05/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Aula sem chamada'));
    await tester.pumpAndSettle();
    expect(
      repository.byId('second').calendarStatus,
      SessionCalendarStatus.noCall,
    );
    expect(find.text('Aula sem chamada'), findsOneWidget);

    await tester.tap(find.byTooltip('Entenda os tipos de aula'));
    await tester.pumpAndSettle();
    expect(find.text('Como as aulas entram no cálculo'), findsOneWidget);
    expect(find.textContaining('presença garantida'), findsOneWidget);
    await tester.tap(find.text('Entendi'));
    await tester.pumpAndSettle();
    expect(find.text('Como as aulas entram no cálculo'), findsNothing);
  });

  testWidgets('persists calendar categories through Python when enabled', (
    tester,
  ) async {
    final repository = _FakeSessionRepository([
      _session('first', DateTime.utc(2026, 8, 3, 11), now),
    ]);
    final gateway = _SessionGateway(now);
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: _RecordingAppLogger(),
          location: location,
          now: () => now,
          sessionGateway: gateway,
          sessionWritesEnabled: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Alterar sessão de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Aula sem chamada'));
    await tester.pumpAndSettle();

    expect(gateway.calendarCalls.single, ('poo', 'first', 'no_call'));
    expect(repository.saveCalls, isEmpty);
    expect(
      repository.byId('first').calendarStatus,
      SessionCalendarStatus.scheduled,
    );
    expect(find.text('Aula sem chamada'), findsOneWidget);
  });

  testWidgets('adds and removes an evaluative activity independently', (
    tester,
  ) async {
    final repository = _FakeSessionRepository([
      _session('first', DateTime.utc(2026, 8, 3, 11), now),
    ]);
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: logger,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Editar avaliação de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
    await tester.pumpAndSettle();
    expect(repository.byId('first').assessmentTitle, isNull);

    await tester.tap(find.byTooltip('Editar avaliação de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('assessment-title')),
      'Prova 1',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.byId('first').assessmentTitle, 'Prova 1');
    expect(find.textContaining('Avaliação: Prova 1'), findsOneWidget);
    expect(
      logger.events,
      containsAllInOrder([
        'assessment_update_started',
        'assessment_update_succeeded',
      ]),
    );

    repository.saveError = StateError('offline');
    await tester.tap(find.byTooltip('Editar avaliação de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('assessment-title')),
      'Prova alterada',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível salvar a avaliação.'), findsOneWidget);
    expect(repository.byId('first').assessmentTitle, 'Prova 1');
    repository.saveError = null;

    await tester.tap(find.byTooltip('Editar avaliação de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('assessment-title')), '');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(repository.byId('first').assessmentTitle, isNull);
  });

  testWidgets('restores a calendar exception without losing attendance data', (
    tester,
  ) async {
    final cancelled = _session(
      'first',
      DateTime.utc(2026, 8, 3, 11),
      now,
      status: SessionCalendarStatus.cancelled,
      attendanceStatus: SituacaoFrequencia.present,
      absences: 0,
    );
    final repository = _FakeSessionRepository([cancelled]);
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: _RecordingAppLogger(),
          location: location,
          now: () => now,
          idGenerator: () => 'makeup-1',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Alterar sessão de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Restaurar aula'));
    await tester.pumpAndSettle();

    final restored = repository.byId('first');
    expect(restored.calendarStatus, SessionCalendarStatus.scheduled);
    expect(restored.attendanceStatus, SituacaoFrequencia.present);
    expect(restored.absences, 0);
    expect(restored.createdAt, cancelled.createdAt);
  });

  testWidgets('adds and validates a makeup session', (tester) async {
    final repository = _FakeSessionRepository([]);
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: _RecordingAppLogger(),
          location: location,
          now: () => now,
          idGenerator: () => 'makeup-1',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma sessão gerada'), findsOneWidget);

    await tester.tap(find.byKey(const Key('add-makeup-session')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Adicionar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use uma data válida no formato AAAA-MM-DD.'),
      findsOneWidget,
    );
    expect(
      find.text('Use um horário válido no formato HH:MM.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('makeup-date')), '2026-08-04');
    await tester.enterText(find.byKey(const Key('makeup-start')), '14:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Adicionar'));
    await tester.pumpAndSettle();

    final added = repository.byId('makeup-1');
    expect(added.calendarStatus, SessionCalendarStatus.makeup);
    expect(added.startsAt, DateTime.utc(2026, 8, 4, 17));
    expect(added.endsAt, DateTime.utc(2026, 8, 4, 18, 40));
    expect(find.text('Reposição'), findsOneWidget);

    await tester.tap(find.byTooltip('Alterar sessão de 04/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelada/feriado'));
    await tester.pumpAndSettle();
    expect(
      repository.byId('makeup-1').calendarStatus,
      SessionCalendarStatus.cancelled,
    );
  });

  testWidgets('recovers from load and status update failures', (tester) async {
    final repository = _FakeSessionRepository([
      _session('first', DateTime.utc(2026, 8, 3, 11), now),
    ])..listError = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: CalendarExceptionsPage(
          courseId: courseId,
          repository: repository,
          logger: _RecordingAppLogger(),
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível carregar as sessões.'), findsOneWidget);

    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    repository.saveError = StateError('offline');
    await tester.tap(find.byTooltip('Alterar sessão de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelada/feriado'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível alterar a sessão.'), findsOneWidget);
    expect(
      repository.byId('first').calendarStatus,
      SessionCalendarStatus.scheduled,
    );
  });

  testWidgets(
    'rejects past and failed makeup sessions and edits configuration',
    (tester) async {
      final repository = _FakeSessionRepository([]);
      await tester.pumpWidget(
        MaterialApp(
          home: CalendarExceptionsPage(
            courseId: courseId,
            repository: repository,
            logger: _RecordingAppLogger(),
            location: location,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('add-makeup-session')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const ValueKey('makeup-calls-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('2 chamadas').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('makeup-lessons')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('1 aulas').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('makeup-lessons')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('4 aulas').last);
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('makeup-date')),
        '2026-07-01',
      );
      await tester.enterText(find.byKey(const Key('makeup-start')), '08:00');
      await tester.tap(find.widgetWithText(FilledButton, 'Adicionar'));
      await tester.pumpAndSettle();
      expect(find.text('A reposição precisa estar no futuro.'), findsOneWidget);

      repository.saveError = StateError('offline');
      await tester.enterText(
        find.byKey(const Key('makeup-date')),
        '2099-01-05',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Adicionar'));
      await tester.pumpAndSettle();
      expect(
        find.text('Não foi possível adicionar a reposição.'),
        findsOneWidget,
      );

      repository.saveError = null;
      await tester.tap(find.widgetWithText(FilledButton, 'Adicionar'));
      await tester.pumpAndSettle();
      expect(repository.sessions.single.id, startsWith('makeup-'));
      expect(repository.sessions.single.lessonCount, QuantidadeAulas.four);
    },
  );
}

SessionRecord _session(
  String id,
  DateTime startsAt,
  DateTime now, {
  SessionCalendarStatus status = SessionCalendarStatus.scheduled,
  SituacaoFrequencia? attendanceStatus,
  int? absences,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(const Duration(minutes: 100)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  attendanceStatus: attendanceStatus,
  absences: absences,
  calendarStatus: status,
  createdAt: now,
  updatedAt: now,
);

final class _FakeSessionRepository implements SessionRepository {
  _FakeSessionRepository(List<SessionRecord> sessions)
    : sessions = [...sessions];

  final List<SessionRecord> sessions;
  Object? listError;
  Object? saveError;
  final saveCalls = <SessionRecord>[];

  SessionRecord byId(String id) =>
      sessions.singleWhere((item) => item.id == id);

  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}

  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    if (listError case final error?) throw error;
    return [...sessions];
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {
    if (saveError case final error?) throw error;
    saveCalls.add(session);
    sessions.removeWhere((item) => item.id == session.id);
    sessions.add(session);
  }
}

final class _SessionGateway implements BackendSessionGateway {
  _SessionGateway(this.updatedAt);

  final DateTime updatedAt;
  final calendarCalls = <(String, String, String)>[];

  @override
  Future<PythonCalendarStatusMutation> saveCalendarStatus({
    required String courseId,
    required String sessionId,
    required String calendarStatus,
  }) async {
    calendarCalls.add((courseId, sessionId, calendarStatus));
    return PythonCalendarStatusMutation(
      calendarStatus: calendarStatus,
      updatedAt: updatedAt,
    );
  }

  @override
  Future<PythonAttendanceMutation> saveAttendance({
    required String courseId,
    required String sessionId,
    required String status,
    required int maximumAbsences,
    required bool useDefaultAbsences,
    int? correctedAbsences,
  }) => throw UnimplementedError();
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
