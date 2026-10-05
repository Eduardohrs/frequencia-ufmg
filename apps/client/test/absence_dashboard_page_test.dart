import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/attendance/absence_dashboard_page.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final now = DateTime.utc(2026, 9, 28, 12);
  final poo = _course('poo', 'DCC203', 60, now);
  final calculus = _course('calc', 'MAT001', 4, now);

  test('separates the academic total from past attendance pendencies', () {
    final summary = CourseAbsenceSummary.from(
      poo,
      [
        _session('absent', DateTime.utc(2026, 9, 26, 11), absences: 2),
        _session('present', DateTime.utc(2026, 9, 27, 11), absences: 0),
        _session('pending', DateTime.utc(2026, 9, 27, 11)),
        _session('future', DateTime.utc(2026, 9, 29, 11)),
        _session(
          'cancelled',
          now,
          absences: 2,
          calendarStatus: SessionCalendarStatus.cancelled,
        ),
        _session('holiday', now, calendarStatus: SessionCalendarStatus.holiday),
        _session('no-call', now, calendarStatus: SessionCalendarStatus.noCall),
      ],
      now: now,
      location: location,
    );

    expect(summary.sessions.map((item) => item.id), [
      'absent',
      'present',
      'pending',
      'no-call',
      'future',
    ]);
    expect(summary.consumedAbsences, 2);
    expect(summary.eligibleLessons, 10);
    expect(summary.absenceLimit, 2);
    expect(summary.remainingAbsences, 0);
    expect(summary.pendingSessions, 1);
    expect(summary.presentLessons, 4);
    expect(summary.unresolvedLessons, 4);
    expect(summary.remainingMeetingsLabel, '0 encontros restantes');
  });

  test('never reports a negative remaining allowance', () {
    final summary = CourseAbsenceSummary.from(
      calculus,
      [_session('over-limit', now, absences: 2)],
      now: now,
      location: location,
    );
    expect(summary.absenceLimit, 0);
    expect(summary.remainingAbsences, 0);
  });

  test('reports whole or half meetings according to roll calls', () {
    final oneCall = CourseAbsenceSummary.from(
      poo,
      [
        for (var index = 0; index < 10; index++)
          _session('one-$index', now.add(Duration(days: index))),
      ],
      now: now,
      location: location,
    );
    final twoCalls = CourseAbsenceSummary.from(
      poo,
      [
        for (var index = 0; index < 10; index++)
          _session(
            'two-$index',
            now.add(Duration(days: index)),
            callCount: NumeroChamadas.two,
          ),
      ],
      now: now,
      location: location,
    );
    final mixed = CourseAbsenceSummary.from(
      poo,
      [
        _session('two-lessons', now),
        _session('four-lessons', now, lessonCount: QuantidadeAulas.four),
      ],
      now: now,
      location: location,
    );

    expect(oneCall.remainingMeetingsLabel, '2 encontros restantes');
    expect(twoCalls.remainingMeetingsLabel, '2,5 encontros restantes');
    expect(mixed.remainingMeetingsLabel, '1 aula de 50 min restante');
  });

  test('detects when the minimum attendance is already guaranteed', () {
    final summary = CourseAbsenceSummary.from(
      poo,
      [
        for (var index = 0; index < 4; index++)
          _session('present-$index', now, absences: 0),
        _session('future', now.add(const Duration(days: 1))),
      ],
      now: now,
      location: location,
    );

    expect(summary.minimumAttendanceGuaranteed, isTrue);
  });

  testWidgets('shows remaining absences and each session impact', (
    tester,
  ) async {
    final repository = _Repository({
      'poo': [
        _session('absent', DateTime.utc(2026, 9, 28, 11), absences: 2),
        _session('pending', DateTime.utc(2026, 9, 27, 11)),
        _session('pending-2', DateTime.utc(2026, 9, 25, 11)),
        _session('future', DateTime.utc(2026, 9, 29, 11)),
        _session(
          'no-call',
          DateTime.utc(2026, 9, 26, 11),
          calendarStatus: SessionCalendarStatus.noCall,
        ),
        _session(
          'makeup',
          DateTime.utc(2026, 9, 30, 11),
          absences: 1,
          lessonCount: QuantidadeAulas.four,
          calendarStatus: SessionCalendarStatus.makeup,
        ),
        _session(
          'holiday',
          DateTime.utc(2026, 10, 1, 11),
          calendarStatus: SessionCalendarStatus.holiday,
        ),
      ],
      'calc': [
        _session(
          'calc-1',
          DateTime.utc(2026, 9, 28, 13),
          absences: 0,
          lessonCount: QuantidadeAulas.one,
        ),
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: AbsenceDashboardPage(
          courses: [poo, calculus],
          repository: repository,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Faltas restantes'), findsOneWidget);
    expect(find.text('0 encontros restantes'), findsOneWidget);
    expect(
      find.text('3 de 3 faltas usadas • 2 sessões anteriores pendentes'),
      findsOneWidget,
    );
    expect(
      find.text('0 de 0 faltas usadas • nenhuma pendência anterior'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('attendance-semicircle-poo')), findsOneWidget);
    expect(
      find.byKey(const Key('minimum-attendance-marker-poo')),
      findsOneWidget,
    );
    expect(find.text('Frequência mínima garantida'), findsOneWidget);

    await tester.tap(find.text('DCC203'));
    await tester.pumpAndSettle();
    expect(find.text('28/09/2026 • Ausente'), findsOneWidget);
    expect(
      find.text('2 faltas registradas • máximo de 2 faltas nesta sessão'),
      findsOneWidget,
    );
    expect(find.text('27/09/2026 • Sem registro'), findsOneWidget);
    expect(find.text('Uma ausência consumiria 2 faltas'), findsNWidgets(3));
    expect(find.text('30/09/2026 • Chegou atrasado'), findsOneWidget);
    expect(
      find.text('1 falta registrada • máximo de 4 faltas nesta sessão'),
      findsOneWidget,
    );
    expect(find.text('01/10/2026'), findsNothing);
    expect(find.text('26/09/2026 • Presença garantida'), findsOneWidget);
    expect(find.text('Aula realizada sem chamada • 0 faltas'), findsOneWidget);
  });

  testWidgets('shows empty state and recovers from a loading failure', (
    tester,
  ) async {
    final repository = _Repository({})..error = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: AbsenceDashboardPage(
          courses: [poo],
          repository: repository,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível calcular suas faltas.'), findsOneWidget);

    repository.error = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('0 encontros restantes'), findsOneWidget);
  });

  testWidgets('shows the empty state without courses', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AbsenceDashboardPage(
          courses: const [],
          repository: _Repository({}),
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
  });
}

CourseRecord _course(String id, String code, int workload, DateTime now) =>
    CourseRecord(
      id: id,
      code: code,
      name: '$code - nome',
      workload: workload,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );

SessionRecord _session(
  String id,
  DateTime startsAt, {
  int? absences,
  QuantidadeAulas lessonCount = QuantidadeAulas.two,
  NumeroChamadas callCount = NumeroChamadas.one,
  SessionCalendarStatus calendarStatus = SessionCalendarStatus.scheduled,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(Duration(minutes: lessonCount.value * 50)),
  lessonCount: lessonCount,
  callCount: callCount,
  attendanceStatus: absences == null
      ? null
      : absences == lessonCount.value
      ? SituacaoFrequencia.absent
      : absences == 0
      ? SituacaoFrequencia.present
      : SituacaoFrequencia.arrivedLate,
  absences: absences,
  calendarStatus: calendarStatus,
  createdAt: startsAt,
  updatedAt: startsAt,
);

final class _Repository implements SessionRepository {
  _Repository(this.sessions);

  final Map<String, List<SessionRecord>> sessions;
  Object? error;

  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    if (error case final value?) throw value;
    return [...sessions[courseId] ?? const []];
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {}

  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}
}
