import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
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

  testWidgets('groups sessions by urgency and highlights an alert target', (
    tester,
  ) async {
    final repository = _FakeRepository([
      _session(
        'history',
        DateTime.utc(2026, 7, 29, 12),
        attendanceStatus: SituacaoFrequencia.present,
        absences: 0,
      ),
      _session('pending-old', DateTime.utc(2026, 7, 30, 12)),
      _session('pending-recent', DateTime.utc(2026, 7, 31, 12)),
      _session('today', now),
      _session('future', DateTime.utc(2026, 8, 2, 12)),
    ]);

    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        courseCode: 'DCC203',
        initialSessionId: 'pending-recent',
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Frequência • DCC203'), findsOneWidget);
    expect(find.text('Pendências anteriores'), findsOneWidget);
    expect(find.text('Hoje'), findsOneWidget);
    expect(find.text('Próximas aulas'), findsOneWidget);
    expect(find.text('Histórico'), findsOneWidget);
    expect(find.text('Selecionada pelo alerta'), findsOneWidget);
    expect(find.text('Pendente de registro'), findsNWidgets(2));
    expect(
      tester
          .getTopLeft(
            find.byKey(const Key('attendance-session-pending-recent')),
          )
          .dy,
      lessThan(
        tester
            .getTopLeft(find.byKey(const Key('attendance-session-pending-old')))
            .dy,
      ),
    );
    expect(
      tester.getTopLeft(find.text('Pendências anteriores')).dy,
      lessThan(tester.getTopLeft(find.text('Hoje')).dy),
    );
  });

  testWidgets('keeps the highlighted pending session readable on a phone', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final repository = _FakeRepository([
      _session('pending', DateTime.utc(2026, 7, 31, 12)),
    ]);

    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        courseCode: 'DCC203',
        initialSessionId: 'pending',
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Selecionada pelo alerta'), findsOneWidget);
    expect(find.text('Pendente de registro'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('uses Python as authority for a new attendance record', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('python', now)]);
    final evaluator = _Evaluator(absences: 1);
    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        attendanceEvaluator: evaluator,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attendance-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chegou atrasado').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(evaluator.calls, [
      (lessons: 2, calls: 2, status: 'chegou_atrasado'),
    ]);
    expect(repository.byId('python').absences, 1);
  });

  testWidgets('persists initial attendance and corrections through Python', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('python', now)]);
    final gateway = _SessionGateway(now);
    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        sessionGateway: gateway,
        sessionWritesEnabled: true,
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(gateway.attendanceCalls.single.useDefaultAbsences, isTrue);
    expect(gateway.attendanceCalls.single.correctedAbsences, isNull);
    expect(repository.saveCalls, isEmpty);
    expect(repository.byId('python').attendanceStatus, isNull);
    expect(find.text('Presente • 0 faltas'), findsOneWidget);

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('attendance-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Saiu mais cedo').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('attendance-absences')), '1');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(gateway.attendanceCalls.last.useDefaultAbsences, isFalse);
    expect(gateway.attendanceCalls.last.correctedAbsences, 1);
    expect(find.text('Saiu mais cedo • 1 faltas'), findsOneWidget);
  });

  testWidgets('queues attendance in Firestore when Android loses the backend', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('offline', now)]);
    final logger = _Logger();
    final gateway = _SessionGateway(
      now,
      failure: const PythonBackendException(PythonBackendError.unavailable),
    );
    await tester.pumpWidget(
      _app(
        repository,
        logger,
        location,
        now,
        sessionGateway: gateway,
        sessionWritesEnabled: true,
        androidOfflineQueueEnabled: true,
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      repository.saveCalls.single.attendanceStatus,
      SituacaoFrequencia.present,
    );
    expect(repository.saveCalls.single.absences, 0);
    expect(find.text('Presente • 0 faltas'), findsOneWidget);
    expect(
      find.text(
        'Salvo no aparelho. A sincronização continuará automaticamente.',
      ),
      findsOneWidget,
    );
    expect(logger.events, contains('android_offline_attendance_queued'));
  });

  testWidgets('never bypasses Python for an authentication rejection', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('rejected', now)]);
    final gateway = _SessionGateway(
      now,
      failure: const PythonBackendException(PythonBackendError.unauthorized),
    );
    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        sessionGateway: gateway,
        sessionWritesEnabled: true,
        androidOfflineQueueEnabled: true,
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.saveCalls, isEmpty);
    expect(find.text('Não foi possível salvar a frequência.'), findsOneWidget);
  });

  testWidgets('observes a rejected offline attendance delivery', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('offline', now)])
      ..saveError = StateError('delivery rejected');
    final logger = _Logger();
    await tester.pumpWidget(
      _app(
        repository,
        logger,
        location,
        now,
        sessionGateway: _SessionGateway(
          now,
          failure: const PythonBackendException(PythonBackendError.timeout),
        ),
        sessionWritesEnabled: true,
        androidOfflineQueueEnabled: true,
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      logger.errorContexts,
      contains('android_offline_attendance_delivery'),
    );
  });

  testWidgets('does not save when the Python authority is unavailable', (
    tester,
  ) async {
    final repository = _FakeRepository([_session('python', now)]);
    await tester.pumpWidget(
      _app(
        repository,
        _Logger(),
        location,
        now,
        attendanceEvaluator: _Evaluator(absences: 2, status: 'ausente'),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Registrar frequência de 01/08/2026'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível calcular as faltas. Tente novamente.'),
      findsOneWidget,
    );
    expect(repository.byId('python').attendanceStatus, isNull);
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
  DateTime now, {
  BackendAttendanceEvaluator? attendanceEvaluator,
  BackendSessionGateway? sessionGateway,
  bool sessionWritesEnabled = false,
  bool androidOfflineQueueEnabled = false,
  String? courseCode,
  String? initialSessionId,
}) => MaterialApp(
  home: AttendancePage(
    courseId: 'poo',
    courseCode: courseCode,
    initialSessionId: initialSessionId,
    repository: repository,
    logger: logger,
    location: location,
    now: () => now,
    attendanceEvaluator: attendanceEvaluator,
    sessionGateway: sessionGateway,
    sessionWritesEnabled: sessionWritesEnabled,
    androidOfflineQueueEnabled: androidOfflineQueueEnabled,
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

final class _FakeRepository
    implements SessionRepository, OfflineSessionMutationQueue {
  _FakeRepository(this.sessions);
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

  @override
  Future<void> patchAttendance(
    String courseId,
    String sessionId, {
    required SituacaoFrequencia status,
    required int? absences,
    required DateTime updatedAt,
  }) => saveSession(
    courseId,
    _copySession(
      byId(sessionId),
      status: status,
      absences: absences,
      updatedAt: updatedAt,
    ),
  );

  @override
  Future<void> patchCalendarStatus(
    String courseId,
    String sessionId, {
    required SessionCalendarStatus status,
    required DateTime updatedAt,
  }) => throw UnimplementedError();
}

SessionRecord _copySession(
  SessionRecord source, {
  required SituacaoFrequencia status,
  required int? absences,
  required DateTime updatedAt,
}) => SessionRecord(
  id: source.id,
  startsAt: source.startsAt,
  endsAt: source.endsAt,
  lessonCount: source.lessonCount,
  callCount: source.callCount,
  firstPing: source.firstPing,
  secondPing: source.secondPing,
  attendanceStatus: status,
  absences: absences,
  calendarStatus: source.calendarStatus,
  assessmentTitle: source.assessmentTitle,
  createdAt: source.createdAt,
  updatedAt: updatedAt,
);

final class _SessionGateway implements BackendSessionGateway {
  _SessionGateway(this.updatedAt, {this.failure});

  final DateTime updatedAt;
  final Object? failure;
  final attendanceCalls =
      <
        ({
          String courseId,
          String sessionId,
          String status,
          int maximumAbsences,
          bool useDefaultAbsences,
          int? correctedAbsences,
        })
      >[];

  @override
  Future<PythonAttendanceMutation> saveAttendance({
    required String courseId,
    required String sessionId,
    required String status,
    required int maximumAbsences,
    required bool useDefaultAbsences,
    int? correctedAbsences,
  }) async {
    if (failure case final error?) throw error;
    attendanceCalls.add((
      courseId: courseId,
      sessionId: sessionId,
      status: status,
      maximumAbsences: maximumAbsences,
      useDefaultAbsences: useDefaultAbsences,
      correctedAbsences: correctedAbsences,
    ));
    return PythonAttendanceMutation(
      status: status,
      absences: useDefaultAbsences ? 0 : correctedAbsences,
      updatedAt: updatedAt,
    );
  }

  @override
  Future<PythonCalendarStatusMutation> saveCalendarStatus({
    required String courseId,
    required String sessionId,
    required String calendarStatus,
  }) => throw UnimplementedError();
}

final class _Logger implements AppLogger {
  final events = <String>[];
  final errorContexts = <String>[];
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
  }) async => errorContexts.add(context);
}

final class _Evaluator implements BackendAttendanceEvaluator {
  _Evaluator({this.absences, this.status});

  final int? absences;
  final String? status;
  final calls = <({int lessons, int calls, String status})>[];

  @override
  Future<PythonAttendanceDecision> evaluateAttendanceStatus({
    required int lessons,
    required int calls,
    required String status,
  }) async {
    this.calls.add((lessons: lessons, calls: calls, status: status));
    return PythonAttendanceDecision(
      status: this.status ?? status,
      absences: absences,
    );
  }
}
