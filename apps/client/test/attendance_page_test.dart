import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/attendance/attendance_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final now = DateTime.utc(2026, 8, 1, 12);

  testWidgets('registers and corrects every manual attendance result', (
    tester,
  ) async {
    final repository = _FakeRepository([
      _session('regular', now),
      _session(
        'cancelled',
        now.add(const Duration(days: 1)),
        calendar: SessionCalendarStatus.cancelled,
      ),
      _session(
        'holiday',
        now.add(const Duration(days: 2)),
        calendar: SessionCalendarStatus.holiday,
      ),
    ]);
    final logger = _Logger();
    await tester.pumpWidget(_app(repository, logger, location, now));
    await tester.pumpAndSettle();
    expect(find.text('Cancelada/feriado • sem frequência'), findsNWidgets(2));

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attendance-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chegou atrasado').last);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('attendance-absences')), findsNothing);
    expect(
      find.text('As faltas serão calculadas automaticamente.'),
      findsOneWidget,
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      repository.byId('regular').attendanceStatus,
      SituacaoFrequencia.arrivedLate,
    );
    expect(repository.byId('regular').absences, 1);
    expect(
      logger.events,
      containsAllInOrder([
        'manual_attendance_started',
        'manual_attendance_succeeded',
      ]),
    );

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attendance-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Pendente').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      repository.byId('regular').attendanceStatus,
      SituacaoFrequencia.pending,
    );
    expect(repository.byId('regular').absences, isNull);
    expect(find.text('Pendente • faltas pendentes'), findsOneWidget);
  });

  testWidgets('registers attendance for a session from a previous month', (
    tester,
  ) async {
    final repository = _FakeRepository([
      _session('august', DateTime.utc(2026, 8, 3, 11)),
    ]);
    final september = DateTime.utc(2026, 9, 28, 12);

    await tester.pumpWidget(_app(repository, _Logger(), location, september));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Registrar frequência de 03/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      repository.byId('august').attendanceStatus,
      SituacaoFrequencia.present,
    );
  });

  testWidgets('validates absences and reports save failure', (tester) async {
    final repository = _FakeRepository([
      _session(
        'regular',
        now,
        attendanceStatus: SituacaoFrequencia.present,
        absences: 0,
      ),
    ]);
    await tester.pumpWidget(_app(repository, _Logger(), location, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('attendance-absences')), '3');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Use um valor entre 0 e 2.'), findsOneWidget);

    repository.saveError = StateError('offline');
    await tester.enterText(find.byKey(const Key('attendance-absences')), '0');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível salvar a frequência.'), findsOneWidget);
    await tester.tap(find.text('Cancelar'));
  });

  testWidgets('recovers from loading failure and shows an empty state', (
    tester,
  ) async {
    final repository = _FakeRepository([])..listError = StateError('offline');
    await tester.pumpWidget(_app(repository, _Logger(), location, now));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível carregar as sessões.'), findsOneWidget);
    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma sessão gerada'), findsOneWidget);
  });
}

Widget _app(
  _FakeRepository repository,
  AppLogger logger,
  tz.Location location,
  DateTime now,
) => MaterialApp(
  home: AttendancePage(
    courseId: 'poo',
    repository: repository,
    logger: logger,
    location: location,
    now: () => now,
  ),
);

SessionRecord _session(
  String id,
  DateTime startsAt, {
  SessionCalendarStatus calendar = SessionCalendarStatus.scheduled,
  SituacaoFrequencia? attendanceStatus,
  int? absences,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(const Duration(minutes: 100)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.two,
  calendarStatus: calendar,
  attendanceStatus: attendanceStatus,
  absences: absences,
  createdAt: startsAt,
  updatedAt: startsAt,
);

final class _FakeRepository implements SessionRepository {
  _FakeRepository(this.sessions);
  final List<SessionRecord> sessions;
  Object? listError;
  Object? saveError;
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
    sessions.removeWhere((item) => item.id == session.id);
    sessions.add(session);
  }
}

final class _Logger implements AppLogger {
  final events = <String>[];
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async =>
      events.add(name);
  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {}
}
