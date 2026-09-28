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

  test('summarizes only sessions that count toward attendance', () {
    final summary = CourseAbsenceSummary.from(poo, [
      _session('absent', now, absences: 2),
      _session('present', now, absences: 0),
      _session('pending', now),
      _session(
        'cancelled',
        now,
        absences: 2,
        calendarStatus: SessionCalendarStatus.cancelled,
      ),
      _session('holiday', now, calendarStatus: SessionCalendarStatus.holiday),
      _session('no-call', now, calendarStatus: SessionCalendarStatus.noCall),
    ]);

    expect(summary.sessions.map((item) => item.id), [
      'absent',
      'present',
      'pending',
    ]);
    expect(summary.consumedAbsences, 2);
    expect(summary.eligibleLessons, 6);
    expect(summary.absenceLimit, 1);
    expect(summary.remainingAbsences, 0);
    expect(summary.pendingSessions, 1);
  });

  test('never reports a negative remaining allowance', () {
    final summary = CourseAbsenceSummary.from(calculus, [
      _session('over-limit', now, absences: 2),
    ]);
    expect(summary.absenceLimit, 0);
    expect(summary.remainingAbsences, 0);
  });

  testWidgets('shows remaining absences and each session impact', (
    tester,
  ) async {
    final repository = _Repository({
      'poo': [
        _session('absent', DateTime.utc(2026, 9, 28, 11), absences: 2),
        _session('pending', DateTime.utc(2026, 9, 29, 11)),
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
        _session('calc-1', DateTime.utc(2026, 9, 28, 13)),
        _session('calc-2', DateTime.utc(2026, 9, 29, 13)),
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: AbsenceDashboardPage(
          courses: [poo, calculus],
          repository: repository,
          location: location,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Faltas restantes'), findsOneWidget);
    expect(find.text('0 faltas restantes'), findsOneWidget);
    expect(
      find.text('3 de 2 faltas usadas • 1 sessão pendente'),
      findsOneWidget,
    );
    expect(find.text('1 falta restante'), findsOneWidget);
    expect(
      find.text('0 de 1 faltas usadas • 2 sessões pendentes'),
      findsOneWidget,
    );

    await tester.tap(find.text('DCC203'));
    await tester.pumpAndSettle();
    expect(find.text('28/09/2026 • Ausente'), findsOneWidget);
    expect(
      find.text('2 faltas registradas • máximo de 2 faltas nesta sessão'),
      findsOneWidget,
    );
    expect(find.text('29/09/2026 • Sem registro'), findsOneWidget);
    expect(find.text('Uma ausência consumiria 2 faltas'), findsOneWidget);
    expect(find.text('30/09/2026 • Chegou atrasado'), findsOneWidget);
    expect(
      find.text('1 falta registrada • máximo de 4 faltas nesta sessão'),
      findsOneWidget,
    );
    expect(find.text('01/10/2026'), findsNothing);
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
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível calcular suas faltas.'), findsOneWidget);

    repository.error = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('0 faltas restantes'), findsOneWidget);
  });

  testWidgets('shows the empty state without courses', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: AbsenceDashboardPage(
          courses: const [],
          repository: _Repository({}),
          location: location,
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
  SessionCalendarStatus calendarStatus = SessionCalendarStatus.scheduled,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(Duration(minutes: lessonCount.value * 50)),
  lessonCount: lessonCount,
  callCount: NumeroChamadas.one,
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
