import 'helpers/calendar_controls.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
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

  testWidgets(
    'compact month opens a readable day instead of abbreviated codes',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final named = [
        for (final entry in [(courses[0], 'POO'), (courses[1], 'Cálculo 3')])
          CourseRecord.fromFirestore(entry.$1.id, {
            ...entry.$1.toFirestore(),
            'nickname': entry.$2,
          }),
      ];
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            navigationState: CalendarNavigationState()
              ..range = CalendarRange.month,
            courses: named,
            repository: _Repository({
              'poo': [_session('a', DateTime.utc(2026, 9, 16, 11))],
              'calc': [_session('b', DateTime.utc(2026, 9, 16, 13))],
            }),
            location: location,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      final lastDay = find.byKey(const ValueKey('calendar-day-2026-10-11'));
      await tester.scrollUntilVisible(
        lastDay,
        150,
        scrollable: find.byType(Scrollable).last,
      );
      expect(lastDay, findsOneWidget);
      final count = find.byKey(const Key('calendar-count-2026-09-16'));
      await tester.scrollUntilVisible(
        count,
        -150,
        scrollable: find.byType(Scrollable).last,
      );
      await tester.tap(count);
      await tester.pumpAndSettle();
      expect(find.text('POO • 16/09/2026'), findsOneWidget);
      expect(find.text('Cálculo 3 • 16/09/2026'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  for (final fails in [false, true]) {
    testWidgets(
      'activities route completion and failure preserve calendar recovery ($fails)',
      (tester) async {
        var opened = false;
        final store = _CalendarLogStore();
        await tester.pumpWidget(
          MaterialApp(
            home: GeneralCalendarPage(
              navigationState: CalendarNavigationState()
                ..range = CalendarRange.month,
              courses: courses,
              repository: _Repository({}),
              location: location,
              now: () => now,
              initialCourseId: 'poo',
              logger: FirestoreAppLogger(
                store: store,
                currentUserId: () => 'owner',
                platform: 'web',
              ),
              onOpenActivities: (course, {String? activityTitle}) async {
                expect(course.id, 'poo');
                if (fails) {
                  throw StateError('route unavailable');
                }
                opened = true;
              },
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('calendar-open-activities')));
        await tester.pumpAndSettle();
        expect(opened, !fails);
        if (fails) {
          final failure = store.records.lastWhere(
            (e) => e['operation'] == 'calendar_activities_navigation',
          );
          final details = failure['errorDetails'].toString();
          expect(details, contains('activities_navigation'));
          expect(details, contains('poo'));
          expect(failure['correlationId'], isNotEmpty);
        }
        if (fails) {
          expect(
            find.text('Não foi possível abrir as atividades. Tente novamente.'),
            findsOneWidget,
          );
        }
        expect(find.text('Agenda'), findsOneWidget);
      },
    );
  }
  testWidgets('missing Home deep link has an explicit recovery message', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          navigationState: CalendarNavigationState()
            ..range = CalendarRange.month,
          courses: courses,
          repository: _Repository({}),
          location: location,
          now: () => now,
          initialCourseId: 'poo',
          initialEntryId: 'deleted',
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Esta data não está mais disponível.'), findsOneWidget);
    expect(find.text('Agenda'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'no-call timetable stays visible with a label and online history stays hidden',
    (tester) async {
      final course = CourseRecord(
        id: 'no-call',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        attendancePolicy: CourseAttendancePolicy.noCall,
        createdAt: now,
        updatedAt: now,
      );
      final online = CourseRecord(
        id: 'online',
        code: 'MAT001',
        name: 'Online',
        workload: 60,
        term: '2026-2',
        modality: CourseModality.online,
        attendancePolicy: CourseAttendancePolicy.noCall,
        createdAt: now,
        updatedAt: now,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            navigationState: CalendarNavigationState()
              ..range = CalendarRange.month,
            courses: [course, online],
            repository: _Repository({}),
            location: location,
            now: () => now,
            initialSessionsByCourse: {
              course.id: [_session('class', DateTime.utc(2026, 9, 16, 11))],
              online.id: [_session('hidden', DateTime.utc(2026, 9, 16, 12))],
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const ValueKey('calendar-day-2026-09-16')),
        100,
        scrollable: find.byType(Scrollable).last,
      );
      expect(find.text('POO · Sem chamada'), findsOneWidget);
      expect(find.text('MAT001'), findsNothing);
      await calendarDisplay(tester, 'Lista');
      await tester.pumpAndSettle();
      expect(find.textContaining('Sem chamada'), findsWidgets);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('shows month and list views and filters by course', (
    tester,
  ) async {
    final repository = _Repository({
      'poo': [
        _session(
          'poo-1',
          DateTime.utc(2026, 9, 16, 11),
          assessmentTitle: 'Prova 1',
        ),
        _session('poo-2', DateTime.utc(2026, 9, 16, 13)),
        _session(
          'poo-3',
          DateTime.utc(2026, 9, 16, 15),
          status: SessionCalendarStatus.makeup,
        ),
        _session(
          'poo-no-call',
          DateTime.utc(2026, 9, 18, 11),
          status: SessionCalendarStatus.noCall,
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
          navigationState: CalendarNavigationState()
            ..range = CalendarRange.month,
          courses: courses,
          repository: repository,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('month-calendar-grid')), findsOneWidget);
    await tester.scrollUntilVisible(
      find.byKey(const ValueKey('calendar-day-2026-09-16')),
      100,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('DCC203'), findsNWidgets(2));
    expect(find.text('DCC203 · Sem chamada'), findsOneWidget);
    expect(find.text('MAT001'), findsNothing);
    expect(find.text('+1'), findsOneWidget);
    expect(find.byIcon(Icons.assignment_outlined), findsOneWidget);
    await tester.tap(find.byTooltip('Próximo período'));
    await tester.pumpAndSettle();
    expect(find.text('Outubro 2026'), findsOneWidget);
    await tester.tap(find.byTooltip('Período anterior'));
    await tester.pumpAndSettle();

    await calendarDisplay(tester, 'Lista');
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('calendar-course-mark-poo')), findsWidgets);
    expect(find.text('DCC203 • 16/09/2026'), findsNWidgets(3));
    expect(find.text('MAT001 • 17/09/2026'), findsNothing);
    await tester.scrollUntilVisible(
      find.text('DCC203 • 18/09/2026'),
      100,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('DCC203 • 18/09/2026'), findsOneWidget);
    expect(find.textContaining('Aula sem chamada'), findsWidgets);
    await tester.scrollUntilVisible(
      find.text('12:00 – 13:40 • Reposição'),
      -100,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('12:00 – 13:40 • Reposição'), findsOneWidget);

    await openCalendarFilters(tester);
    await tester.tap(find.byKey(const Key('calendar-course-filter')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('DCC203').last);
    await tester.pumpAndSettle();
    await applyCalendarFilters(tester);
    await tester.drag(find.byType(ListView), const Offset(0, 600));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('DCC203 • 16/09/2026').first,
      -100,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.text('DCC203 • 16/09/2026'), findsNWidgets(3));
    expect(find.text('MAT001 • 17/09/2026'), findsNothing);
  });

  testWidgets('starts filtered and recovers from load failure', (tester) async {
    final repository = _Repository({})..error = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          navigationState: CalendarNavigationState()
            ..range = CalendarRange.month,
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
    await calendarDisplay(tester, 'Lista');
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma sessão encontrada'), findsOneWidget);
  });

  testWidgets('reflows the global calendar with enlarged text', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: const TextScaler.linear(2)),
          child: child!,
        ),
        home: GeneralCalendarPage(
          navigationState: CalendarNavigationState()
            ..range = CalendarRange.month,
          courses: courses,
          repository: _Repository({}),
          location: location,
          now: () => now,
          initialSessionsByCourse: const {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openCalendarFilters(tester);
    expect(find.byKey(const Key('calendar-course-filter')), findsOneWidget);
    await tester.tap(find.byTooltip('Fechar filtros'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('month-calendar-grid')), findsOneWidget);
    await Scrollable.ensureVisible(
      tester.element(find.byTooltip('Período anterior')),
      alignment: .5,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Período anterior'));
    await tester.pump();
    await Scrollable.ensureVisible(
      tester.element(find.byTooltip('Próximo período')),
      alignment: .5,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Próximo período'));
    await tester.pump();
    expect(find.text('Setembro 2026'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'lesson detail separates type from attendance and changes status in place (CW07/CW13)',
    (tester) async {
      String? changedCourse, changedSession;
      SessionCalendarStatus? changedStatus;
      final session = SessionRecord(
        id: 'a',
        startsAt: DateTime.utc(2026, 9, 16, 11),
        endsAt: DateTime.utc(2026, 9, 16, 12, 40),
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.one,
        attendanceStatus: SituacaoFrequencia.absent,
        absences: 2,
        calendarStatus: SessionCalendarStatus.scheduled,
        createdAt: DateTime.utc(2026, 9, 16, 11),
        updatedAt: DateTime.utc(2026, 9, 16, 11),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            navigationState: CalendarNavigationState()
              ..range = CalendarRange.month,
            courses: courses,
            repository: _Repository({
              'poo': [session],
            }),
            location: location,
            now: () => now,
            onChangeSessionStatus: (courseId, sessionId, status) async {
              changedCourse = courseId;
              changedSession = sessionId;
              changedStatus = status;
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await calendarDisplay(tester, 'Lista');
      await tester.pumpAndSettle();
      await tester.tap(find.text('08:00 – 09:40 • Programada'));
      await tester.pumpAndSettle();
      expect(find.text('Tipo: Programada'), findsOneWidget);
      expect(find.text('Frequência: Ausente • 2 faltas'), findsOneWidget);
      await tester.tap(find.byKey(const Key('calendar-entry-mark-cancelled')));
      await tester.pumpAndSettle();
      expect(changedCourse, 'poo');
      expect(changedSession, 'a');
      expect(changedStatus, SessionCalendarStatus.cancelled);
      expect(find.text('Status da aula atualizado.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'lesson detail offers no-call and restore actions and reports change failures (CW13)',
    (tester) async {
      final repository = _Repository({
        'poo': [
          _session('a', DateTime.utc(2026, 9, 16, 11)),
          _session('late', DateTime.utc(2026, 9, 17, 13)),
        ],
      })..persistSaves = true;
      final statuses = <SessionCalendarStatus>[];
      Future<void> openFirstEntry(String subtitle) async {
        await calendarDisplay(tester, 'Lista');
        await tester.pumpAndSettle();
        await tester.tap(find.text(subtitle));
        await tester.pumpAndSettle();
      }

      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            navigationState: CalendarNavigationState()
              ..range = CalendarRange.month,
            courses: courses,
            repository: repository,
            location: location,
            now: () => now,
            onChangeSessionStatus: (courseId, sessionId, status) async {
              statuses.add(status);
              final current = repository.sessions['poo']!.firstWhere(
                (s) => s.id == sessionId,
              );
              await repository.saveSession(
                courseId,
                SessionRecord(
                  id: current.id,
                  startsAt: current.startsAt,
                  endsAt: current.endsAt,
                  lessonCount: current.lessonCount,
                  callCount: current.callCount,
                  attendanceStatus: current.attendanceStatus,
                  absences: current.absences,
                  calendarStatus: status,
                  assessmentTitle: current.assessmentTitle,
                  createdAt: current.createdAt,
                  updatedAt: current.updatedAt,
                ),
              );
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await openFirstEntry('08:00 – 09:40 • Programada');
      await tester.tap(find.byKey(const Key('calendar-entry-mark-no-call')));
      await tester.pumpAndSettle();
      expect(statuses, [SessionCalendarStatus.noCall]);
      expect(find.text('Status da aula atualizado.'), findsOneWidget);

      // reabrindo, a aula sem chamada oferece restaurar
      await openFirstEntry('08:00 – 09:40 • Aula sem chamada');
      expect(find.byKey(const Key('calendar-entry-restore')), findsOneWidget);
      await tester.tap(find.byKey(const Key('calendar-entry-restore')));
      await tester.pumpAndSettle();
      expect(statuses, [
        SessionCalendarStatus.noCall,
        SessionCalendarStatus.scheduled,
      ]);

    },
  );

  testWidgets(
    'lesson status change failure shows an actionable message (CW13)',
    (tester) async {
      final repository = _Repository({
        'poo': [_session('a', DateTime.utc(2026, 9, 16, 11))],
      });
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            navigationState: CalendarNavigationState()
              ..range = CalendarRange.month,
            courses: courses,
            repository: repository,
            location: location,
            now: () => now,
            logger: FirestoreAppLogger(
              store: _CalendarLogStore(),
              currentUserId: () => 'owner',
              platform: 'web',
            ),
            onChangeSessionStatus: (courseId, sessionId, status) async {
              throw StateError('write denied');
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await calendarDisplay(tester, 'Lista');
      await tester.pumpAndSettle();
      await tester.tap(find.text('08:00 – 09:40 • Programada'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('calendar-entry-mark-cancelled')));
      await tester.pumpAndSettle();
      expect(
        find.text('Não foi possível atualizar o status da aula.'),
        findsOneWidget,
      );
    },
  );

  testWidgets('lesson detail renders the remaining attendance labels (CW07)', (
    tester,
  ) async {
    SessionRecord withStatus(String id, int hour, SituacaoFrequencia status) =>
        SessionRecord(
          id: id,
          startsAt: DateTime.utc(2026, 9, 16, hour),
          endsAt:
              DateTime.utc(2026, 9, 16, hour).add(const Duration(minutes: 100)),
          lessonCount: QuantidadeAulas.two,
          callCount: NumeroChamadas.one,
          attendanceStatus: status,
          absences: 1,
          calendarStatus: SessionCalendarStatus.scheduled,
          createdAt: DateTime.utc(2026, 9, 16, hour),
          updatedAt: DateTime.utc(2026, 9, 16, hour),
        );
    final repository = _Repository({
      'poo': [
        withStatus('late', 11, SituacaoFrequencia.arrivedLate),
        withStatus('early', 13, SituacaoFrequencia.leftEarly),
        withStatus('pending', 15, SituacaoFrequencia.pending),
        withStatus('present', 17, SituacaoFrequencia.present),
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          navigationState: CalendarNavigationState()
            ..range = CalendarRange.month,
          courses: courses,
          repository: repository,
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await calendarDisplay(tester, 'Lista');
    await tester.pumpAndSettle();
    final cases = [
      ('08:00', 'Frequência: Chegou atrasado • 1 falta'),
      ('10:00', 'Frequência: Saiu mais cedo • 1 falta'),
      ('12:00', 'Frequência: A confirmar • 1 falta'),
      ('14:00', 'Frequência: Presente • 1 falta'),
    ];
    for (final (time, expected) in cases) {
      await tester.tap(find.textContaining(time).first);
      await tester.pumpAndSettle();
      expect(find.text(expected), findsOneWidget, reason: expected);
      await tester.tap(find.text('Fechar'));
      await tester.pumpAndSettle();
    }
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
  String? assessmentTitle,
}) => SessionRecord(
  id: id,
  startsAt: startsAt,
  endsAt: startsAt.add(const Duration(minutes: 100)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  calendarStatus: status,
  assessmentTitle: assessmentTitle,
  createdAt: startsAt,
  updatedAt: startsAt,
);

final class _Repository implements SessionRepository {
  _Repository(this.sessions);
  final Map<String, List<SessionRecord>> sessions;
  Object? error;
  bool persistSaves = false;
  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}
  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    if (error case final value?) throw value;
    return [...sessions[courseId] ?? const []];
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {
    if (!persistSaves) return;
    final list = sessions[courseId] ??= [];
    list.removeWhere((item) => item.id == session.id);
    list.add(session);
  }
}

class _CalendarLogStore implements OperationalLogStore {
  final records = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> data) async {
    records.add(data);
  }
}
