import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/general_calendar_page.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final now = DateTime.utc(2026, 9, 15, 12);
  final courses = [
    _course('poo', 'DCC203', now),
    _course('calc', 'MAT001', now),
  ];

  testWidgets('shows month and list views and filters by course', (
    tester,
  ) async {
    final repository = _Repository({
      'poo': [
        _session('poo-1', DateTime.utc(2026, 9, 16, 11)),
        _session('poo-2', DateTime.utc(2026, 9, 16, 13)),
        _session(
          'poo-3',
          DateTime.utc(2026, 9, 16, 15),
          status: SessionCalendarStatus.makeup,
        ),
      ],
      'calc': [
        _session(
          'calc-1',
          DateTime.utc(2026, 9, 17, 13),
          status: SessionCalendarStatus.holiday,
        ),
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          courses: courses,
          repository: repository,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('month-calendar-grid')), findsOneWidget);
    expect(find.text('DCC203'), findsNWidgets(2));
    expect(find.text('MAT001'), findsOneWidget);
    expect(find.text('+1'), findsOneWidget);
    await tester.tap(find.text('Próximo'));
    await tester.pumpAndSettle();
    expect(find.text('Outubro 2026'), findsOneWidget);
    await tester.tap(find.text('Anterior'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Lista'));
    await tester.pumpAndSettle();
    expect(find.text('DCC203 • 16/09/2026'), findsNWidgets(3));
    expect(find.text('MAT001 • 17/09/2026'), findsOneWidget);
    expect(find.text('10:00 • Cancelada/feriado'), findsOneWidget);
    expect(find.text('12:00 • Reposição'), findsOneWidget);

    await tester.tap(find.byKey(const Key('calendar-course-filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('DCC203').last);
    await tester.pumpAndSettle();
    expect(find.text('DCC203 • 16/09/2026'), findsNWidgets(3));
    expect(find.text('MAT001 • 17/09/2026'), findsNothing);
  });

  testWidgets('starts filtered and recovers from load failure', (tester) async {
    final repository = _Repository({})..error = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          courses: courses,
          repository: repository,
          location: location,
          initialCourseId: 'poo',
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível carregar o calendário.'),
      findsOneWidget,
    );
    repository.error = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Lista'));
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma sessão encontrada'), findsOneWidget);
  });
}

CourseRecord _course(String id, String code, DateTime now) => CourseRecord(
  id: id,
  code: code,
  name: code,
  workload: 60,
  term: '2026-2',
  createdAt: now,
  updatedAt: now,
);

SessionRecord _session(
  String id,
  DateTime startsAt, {
  SessionCalendarStatus status = SessionCalendarStatus.scheduled,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(const Duration(minutes: 100)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  calendarStatus: status,
  createdAt: startsAt,
  updatedAt: startsAt,
);

final class _Repository implements SessionRepository {
  _Repository(this.sessions);
  final Map<String, List<SessionRecord>> sessions;
  Object? error;
  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}
  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    if (error case final value?) throw value;
    return [...sessions[courseId] ?? const []];
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {}
}
