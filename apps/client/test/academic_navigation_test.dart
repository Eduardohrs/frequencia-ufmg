import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/general_calendar_page.dart';
import 'package:frequencia_ufmg/features/attendance/absence_dashboard_page.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

final now = DateTime.utc(2026, 9, 15, 12);
CourseRecord course(String id, {bool online = false}) => CourseRecord(
  id: id,
  code: id,
  name: 'Disciplina $id',
  workload: 60,
  term: '2026-2',
  createdAt: now,
  updatedAt: now,
  modality: online ? CourseModality.online : CourseModality.inPerson,
);
SessionRecord session(String id, {int? absences, String? title}) =>
    SessionRecord(
      id: id,
      startsAt: now,
      endsAt: now.add(const Duration(minutes: 100)),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      absences: absences,
      assessmentTitle: title,
      attendanceStatus: absences == null
          ? null
          : absences == 0
          ? SituacaoFrequencia.present
          : SituacaoFrequencia.absent,
      createdAt: now,
      updatedAt: now,
    );
PythonMoodleDate deadline(String id, String kind) => PythonMoodleDate(
  id: id,
  courseId: 'POO',
  courseCode: 'POO',
  title: id,
  dueAt: now,
  kind: kind,
);

class Repo implements SessionRepository {
  final data = <String, List<SessionRecord>>{};
  Future<List<SessionRecord>>? pending;
  bool fail = false;
  @override
  Future<List<SessionRecord>> listSessions(String id) async {
    if (fail) throw StateError('read failure');
    return pending ?? data[id] ?? [];
  }

  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}
  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {}
}

class Logs implements OperationalLogStore {
  final rows = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async {
    rows.add(document);
  }

  List<Map<String, dynamic>> details(String event) => [
    for (final row in rows)
      if (row['event'] == event)
        jsonDecode(row['details']! as String) as Map<String, dynamic>,
  ];
}

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  testWidgets(
    'calendar item, type filter and restored navigation retain context and persisted telemetry',
    (tester) async {
      final repo = Repo()
        ..data['POO'] = [
          session('lesson'),
          session('exam', title: 'Prova presencial'),
        ];
      final logs = Logs();
      final logger = FirestoreAppLogger(
        store: logs,
        currentUserId: () => 'owner',
        platform: 'web',
      );
      final state = CalendarNavigationState()..display = CalendarDisplay.list;
      final opened = <String>[];
      Widget app() => MaterialApp(
        home: GeneralCalendarPage(
          courses: [course('POO')],
          repository: repo,
          location: location,
          now: () => now,
          logger: logger,
          navigationState: state,
          datesByCourse: {
            'POO': [
              deadline('Entrega', 'assignment'),
              deadline('Prova remota', 'assessment'),
            ],
          },
          onOpenCourse: (value) async {
            opened.add(value.id);
          },
        ),
      );
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      Future<void> filter(String label) async {
        await tester.tap(find.byKey(const Key('calendar-type-filter')));
        await tester.pumpAndSettle();
        await tester.tap(find.text(label).last);
        await tester.pumpAndSettle();
      }

      await filter('Entregas e prazos');
      expect(find.textContaining('Prazo: Entrega'), findsOneWidget);
      expect(find.textContaining('Avaliação: Prova presencial'), findsNothing);
      await tester.tap(find.textContaining('Prazo: Entrega'));
      await tester.pumpAndSettle();
      expect(find.text('Entrega'), findsOneWidget);
      await tester.tap(find.text('Abrir disciplina'));
      await tester.pumpAndSettle();
      expect(opened, ['POO']);
      await filter('Avaliações');
      expect(
        find.textContaining('Avaliação: Prova presencial'),
        findsOneWidget,
      );
      expect(find.textContaining('Avaliação: Prova remota'), findsOneWidget);
      await filter('Aulas');
      expect(find.textContaining('Avaliação:'), findsNothing);
      await filter('Todos');
      await tester.tap(
        find.descendant(
          of: find.byType(SegmentedButton<CalendarDisplay>),
          matching: find.text('Calendário'),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Próximo'));
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      expect(find.text('Outubro 2026'), findsOneWidget);
      expect(
        logs
            .details('calendar_view_changed')
            .any((row) => row['action'] == 'type_filter'),
        isTrue,
      );
      expect(
        logs
            .details('calendar_course_navigation_finished')
            .single['applied_to_view'],
        true,
      );
    },
  );
  testWidgets(
    'calendar day exposes every entry and navigation failure stays observable',
    (tester) async {
      final logs = Logs();
      final repo = Repo()
        ..data['POO'] = [session('1'), session('2'), session('3')];
      await tester.binding.setSurfaceSize(const Size(1000, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            courses: [course('POO')],
            repository: repo,
            location: location,
            now: () => now,
            logger: FirestoreAppLogger(
              store: logs,
              currentUserId: () => 'owner',
              platform: 'web',
            ),
            onOpenCourse: (_) async => throw StateError('navigation failure'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('POO').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Fechar'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('+1'));
      await tester.pumpAndSettle();
      expect(find.text('POO • 15/09/2026'), findsNWidgets(3));
      await tester.tap(find.text('POO • 15/09/2026').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abrir disciplina'));
      await tester.pumpAndSettle();
      expect(
        logs.rows.any(
          (row) => row['errorCode'] == 'calendar_navigation_failed',
        ),
        true,
      );
      await tester.tap(find.byTooltip('Fechar dia'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('1').first);
      await tester.pumpAndSettle();
      expect(find.text('Nenhum item neste dia.'), findsOneWidget);
      await tester.tap(find.byTooltip('Fechar dia'));
      await tester.pumpAndSettle();
    },
  );
  testWidgets(
    'calendar ignores stale completions and logs disposed reads and failures',
    (tester) async {
      final logs = Logs();
      final pending = Completer<List<SessionRecord>>();
      final repo = Repo()..pending = pending.future;
      final updates = ValueNotifier<AcademicOverviewSnapshot?>(null);
      final logger = FirestoreAppLogger(
        store: logs,
        currentUserId: () => 'owner',
        platform: 'web',
      );
      final state = CalendarNavigationState()..courseId = 'deleted';
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            courses: [course('POO')],
            repository: repo,
            location: location,
            now: () => now,
            overviewUpdates: updates,
            logger: logger,
            navigationState: state,
          ),
        ),
      );
      await tester.pump();
      updates.value = AcademicOverviewSnapshot(
        courses: [course('POO')],
        sessionsByCourse: {'POO': []},
      );
      await tester.pumpAndSettle();
      pending.complete([session('stale')]);
      await tester.pumpAndSettle();
      expect(
        logs.details('calendar_read_succeeded').last['applied_to_view'],
        false,
      );
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      repo.pending = null;
      repo.fail = true;
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            courses: [course('POO')],
            repository: repo,
            location: location,
            now: () => now,
            logger: logger,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        logs.rows.any((row) => row['errorCode'] == 'calendar_read_failed'),
        true,
      );
      updates.dispose();
    },
  );
  testWidgets(
    'absence dashboard prioritizes risk and opens course without losing summary',
    (tester) async {
      final repo = Repo()
        ..data['A'] = [for (var i = 0; i < 4; i++) session('$i', absences: 0)]
        ..data['Z'] = [
          for (var i = 0; i < 4; i++) session('$i', absences: i == 0 ? 2 : 0),
        ];
      final logs = Logs();
      final opened = <String>[];
      final logger = FirestoreAppLogger(
        store: logs,
        currentUserId: () => 'owner',
        platform: 'web',
      );
      await tester.pumpWidget(
        MaterialApp(
          home: AbsenceDashboardPage(
            courses: [course('A'), course('Z')],
            repository: repo,
            location: location,
            now: () => now,
            logger: logger,
            onOpenCourse: (value) async {
              opened.add(value.id);
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        tester.getTopLeft(find.text('Z')).dy,
        lessThan(tester.getTopLeft(find.text('A')).dy),
      );
      await tester.tap(find.text('Z'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Abrir disciplina').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Abrir disciplina').first);
      await tester.pumpAndSettle();
      expect(opened, ['Z']);
      expect(
        logs.details('absence_course_open_finished').single['applied_to_view'],
        true,
      );
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      final online = course('Online', online: true);
      await tester.pumpWidget(
        MaterialApp(
          home: AbsenceDashboardPage(
            courses: [online],
            repository: repo,
            location: location,
            now: () => now,
            logger: logger,
            onOpenCourse: (_) async => throw StateError('navigation'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Online • Disciplina Online'));
      await tester.pumpAndSettle();
      expect(
        logs.rows.any((row) => row['errorCode'] == 'absence_navigation_failed'),
        true,
      );
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      repo.fail = true;
      await tester.pumpWidget(
        MaterialApp(
          home: AbsenceDashboardPage(
            courses: [course('A')],
            repository: repo,
            location: location,
            now: () => now,
            logger: logger,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        logs.rows.any(
          (row) => row['errorCode'] == 'absence_overview_read_failed',
        ),
        true,
      );
    },
  );
  test(
    'absence priorities distinguish exceeded limit, no timetable and pending ties',
    () {
      CourseAbsenceSummary summary(String id, List<SessionRecord> sessions) =>
          CourseAbsenceSummary.from(
            course(id),
            sessions,
            now: now,
            location: location,
          );
      final exceeded = summary('Z', [session('1', absences: 2)]);
      final limit = summary('Y', [session('1', absences: 0)]);
      final safe = summary('B', [
        for (var i = 0; i < 8; i++) session('$i', absences: 0),
      ]);
      final empty = summary('A', []);
      final values = [safe, limit, empty, exceeded]
        ..sort(compareAbsencePriority);
      expect(values.map((value) => value.course.id), ['Z', 'Y', 'B', 'A']);
      expect(
        compareAbsencePriority(summary('A', []), summary('B', [])),
        lessThan(0),
      );
    },
  );
}
