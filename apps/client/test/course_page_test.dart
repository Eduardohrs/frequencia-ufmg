import 'fixtures/product_experience_fixture.dart' as experience;
import 'package:frequencia_ufmg/features/navigation/product_navigation.dart';
import 'helpers/calendar_controls.dart';
import 'package:frequencia_ufmg/design/course_visuals.dart';
import 'automatic_checkpoint_scheduler_test.dart' show Harness;
import 'first_checkpoint_test.dart' as checkpoint_fixture;
import 'package:frequencia_ufmg/features/ufmg/academic_sync_host.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:frequencia_ufmg/data/first_checkpoint.dart';
import 'package:frequencia_ufmg/features/courses/course_hub_page.dart';
import 'dart:async';
import 'dart:convert';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/backend/academic_sync_progress.dart';
import 'fixtures/academic_sync_fixture.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'fixtures/attendance_permission_fixture.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/document_store.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/data/ufmg_sync_schedule.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/courses/course_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:timezone/data/latest.dart' as tz_data;

void main() {
  tz_data.initializeTimeZones();
  setUp(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel(
            'br.ufmg.frequencia.frequencia_ufmg/attendance_permissions',
          ),
          (_) async => {
            ...readyPermissionSnapshot,
            'battery_unrestricted': true,
            'exact_alarms': true,
          },
        );
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          FirstCheckpointGateway.channel,
          (_) async => null,
        );
  });
  final user = AuthUser(
    id: 'user-1',
    email: 'eduardo@ufmg.br',
    displayName: 'Eduardo',
  );
  final now = DateTime.utc(2026, 9, 27, 12);

  for (final fails in [false, true]) {
    testWidgets(
      'personal label telemetry survives serialization (failure=$fails)',
      (tester) async {
        final store = _HubLogStore();
        final logger = FirestoreAppLogger(
          store: store,
          currentUserId: () => user.id,
          platform: 'web',
        );
        final repo = _FakeCourseRepository(
          courses: [
            CourseRecord(
              id: 'course-1',
              code: 'DCC203',
              name: 'Programação Orientada a Objetos',
              workload: 60,
              term: '2026-2',
              createdAt: now,
              updatedAt: now,
            ),
          ],
        );
        await tester.pumpWidget(
          CourseVisualHost(child: _app(repo, user, now, logger: logger)),
        );
        await tester.pumpAndSettle();
        await _selectCourseAction(tester, 'DCC203', 'Editar');
        await tester.ensureVisible(find.byKey(const Key('course-nickname')));
        await tester.enterText(
          find.byKey(const Key('course-nickname')),
          'POO pessoal',
        );
        if (fails) repo.saveError = StateError('write denied');
        await tester.tap(find.text('Salvar'));
        await tester.pumpAndSettle();
        final start = store.documents.singleWhere(
          (row) => row['event'] == 'course_identity_save_started',
        );
        final end = store.documents.singleWhere(
          (row) => fails
              ? row['operation'] == 'course_identity_save'
              : row['event'] == 'course_identity_save_succeeded',
        );
        final details =
            jsonDecode(end[fails ? 'errorDetails' : 'details']! as String)
                as Map<String, dynamic>;
        expect(end['correlationId'], start['correlationId']);
        expect(end['durationMs'], isA<int>());
        expect(details['stage'], 'repository_write');
        expect(details['course_id'], 'course-1');
        expect(details['course_name'], 'Programação Orientada a Objetos');
        expect(jsonEncode(details), isNot(contains('password')));
        expect(repo.courses.single.nickname, fails ? null : 'POO pessoal');
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
  testWidgets(
    'personal label edits from hub, rejects overflow, persists and reports failure',
    (tester) async {
      final stamp = now;
      final repo = _FakeCourseRepository(
        courses: [
          CourseRecord(
            id: 'course-1',
            code: 'DCC203',
            name: 'Programação Orientada a Objetos',
            workload: 60,
            term: '2026-2',
            createdAt: stamp,
            updatedAt: stamp,
          ),
        ],
      );
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(_app(repo, user, now, logger: logger));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('course-card-course-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('course-hub-edit-name')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('course-nickname')));
      await tester.enterText(
        find.byKey(const Key('course-nickname')),
        'x' * 49,
      );
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.text('Use no máximo 48 caracteres.'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('course-nickname')),
        'Minha POO',
      );
      repo.saveError = StateError('write denied');
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(
        find.text('Não foi possível salvar a disciplina.'),
        findsOneWidget,
      );
      expect(repo.courses.single.nickname, isNull);
      expect(logger.errorContexts, contains('course_identity_save'));
      repo.saveError = null;
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(repo.courses.single.nickname, 'Minha POO');
      expect(repo.courses.single.name, 'Programação Orientada a Objetos');
      expect(find.text('Minha POO'), findsOneWidget);
      final started = logger.eventFields['course_identity_save_started']!;
      final ended = logger.eventFields['course_identity_save_succeeded']!;
      expect(ended['operation_id'], started['operation_id']);
      expect(ended['course_id'], 'course-1');
      expect(ended['duration_ms'], isA<int>());
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Minha POO'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpWidget(_app(repo, user, now));
      await tester.pumpAndSettle();
      expect(find.text('Minha POO'), findsOneWidget);
      await _selectCourseAction(tester, 'DCC203', 'Editar');
      await tester.ensureVisible(find.byKey(const Key('course-nickname')));
      await tester.enterText(find.byKey(const Key('course-nickname')), '');
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(repo.courses.single.nickname, isNull);
      expect(find.text('Programação Orientada a Objetos'), findsOneWidget);
    },
  );

  testWidgets(
    'Home date opens the exact event, retains course name and returns',
    (tester) async {
      final course = CourseRecord(
        id: 'course-1',
        code: 'DCC203',
        name: 'Programação Orientada a Objetos',
        nickname: 'POO prática',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final repo = _FakeCourseRepository(courses: [course]);
      final session = SessionRecord(
        id: 'exam',
        startsAt: now.add(const Duration(days: 1)),
        endsAt: now.add(const Duration(days: 1, hours: 2)),
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.one,
        assessmentTitle: 'Entrega específica está marcado(a) para esta data',
        createdAt: now,
        updatedAt: now,
      );
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: repo,
            ufmgSessionGateway: _WorkspaceGateway(),
            overviewReadsEnabled: true,
            overviewRepository: _FakeOverviewRepository(
              AcademicOverviewSnapshot(
                courses: [course],
                sessionsByCourse: {
                  'course-1': [session],
                },
              ),
            ),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository({
              'course-1': [session],
            }),
            user: user,
            logger: logger,
            onSignOut: () async {},
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Entrega específica'), findsOneWidget);
      await tester.tap(find.byKey(const Key('upcoming-course-1-exam')));
      await tester.pumpAndSettle();
      expect(find.text('Fechar'), findsOneWidget);
      expect(
        find.text('Entrega específica está marcado(a) para esta data'),
        findsOneWidget,
      );
      expect(find.text('POO prática'), findsWidgets);
      expect(logger.events, contains('calendar_entry_opened'));
      await tester.tap(find.text('Fechar'));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('upcoming-course-1-exam')), findsOneWidget);
    },
  );

  for (final fromHub in [false, true]) {
    testWidgets(
      'agenda and activities preserve discipline, view and month (hub=$fromHub)',
      (tester) async {
        final course = CourseRecord(
          id: 'course-1',
          code: 'DCC203',
          name: 'Programação Orientada a Objetos',
          nickname: 'POO',
          workload: 60,
          term: '2026-2',
          createdAt: now,
          updatedAt: now,
        );
        final gateway = _WorkspaceGateway();
        final logger = _RecordingAppLogger();
        final sessions = _FakeSessionRepository({
          'course-1': [
            SessionRecord(
              id: 'delivery',
              startsAt: DateTime.utc(2026, 10, 19, 22),
              endsAt: DateTime.utc(2026, 10, 20),
              lessonCount: QuantidadeAulas.two,
              callCount: NumeroChamadas.one,
              assessmentTitle: 'Entrega da disciplina',
              createdAt: now,
              updatedAt: now,
            ),
          ],
        });
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              repository: _FakeCourseRepository(courses: [course]),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: sessions,
              user: user,
              logger: logger,
              onSignOut: () async {},
              now: () => now,
              ufmgSessionGateway: gateway,
            ),
          ),
        );
        await tester.pumpAndSettle();
        if (fromHub) {
          await tester.tap(find.byKey(const Key('course-card-course-1')));
          await tester.pumpAndSettle();
          await tester.ensureVisible(
            find.byKey(const Key('course-hub-open-calendar')),
          );
          await tester.tap(find.byKey(const Key('course-hub-open-calendar')));
        } else {
          await tester.tap(find.byKey(const Key('nav-general-calendar')));
        }
        await tester.pumpAndSettle();
        if (!fromHub) {
          await openCalendarFilters(tester);
          await tester.tap(find.byKey(const Key('calendar-course-filter')));
          await tester.pumpAndSettle();
          await tester.tap(find.text('POO').last);
          await tester.pumpAndSettle();
          await applyCalendarFilters(tester);
        }
        await openCalendarFilters(tester);
        await tester.tap(find.byKey(const ValueKey('calendar-range-week')));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Mês').last);
        await tester.pumpAndSettle();
        await applyCalendarFilters(tester);
        await tester.tap(find.byTooltip('Próximo período'));
        await tester.pumpAndSettle();
        expect(find.text('Outubro 2026'), findsOneWidget);
        if (fromHub) {
          await calendarDisplay(tester, 'Lista');
          await tester.pumpAndSettle();
          await tester.tap(
            find.textContaining('Avaliação: Entrega da disciplina'),
          );
          await tester.pumpAndSettle();
          await tester.tap(find.text('Ver atividades e plano'));
        } else {
          await tester.tap(find.byKey(const Key('calendar-open-activities')));
        }
        await tester.pumpAndSettle();
        expect(gateway.requested, 'course-1');
        expect(
          find.byKey(const Key('workspace-open-calendar')),
          findsOneWidget,
        );
        await tester.tap(find.byKey(const Key('workspace-open-calendar')));
        await tester.pumpAndSettle();
        expect(logger.events, contains('calendar_activities_open_succeeded'));
        if (fromHub) {
          expect(find.byKey(const Key('month-calendar-grid')), findsNothing);
          await calendarDisplay(tester, 'Agenda');
          await tester.pumpAndSettle();
        }
        expect(find.text('Outubro 2026'), findsOneWidget);
        expect(find.text('POO'), findsWidgets);
      },
    );
  }

  testWidgets('settings keeps files in courses without asking UFMG status', (
    tester,
  ) async {
    final gateway = _UFMGGateway();
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
          ufmgSessionGateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile-menu')));
    await tester.pumpAndSettle();
    expect(find.text('Arquivos no aparelho'), findsNothing);
    expect(find.text('Arquivos no dispositivo'), findsNothing);
    expect(gateway.statusCalls, 0);
  });
  for (final injected in [false, true]) {
    testWidgets(
      'loading saved sessions automatically schedules without opening diagnostics (injected=$injected)',
      (tester) async {
        final h = Harness();
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              FirstCheckpointGateway.channel,
              (call) => h.scheduler.perform(
                call.method,
                Map<String, Object?>.from(call.arguments as Map),
              ),
            );
        final snapshot = AcademicOverviewSnapshot(
          courses: [checkpoint_fixture.course()],
          sessionsByCourse: {
            'poo': [checkpoint_fixture.session('automatic')],
          },
        );
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              repository: _FakeCourseRepository(),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository(),
              user: user,
              logger: h.logger,
              onSignOut: () async {},
              overviewRepository: _FakeOverviewRepository(snapshot),
              overviewReadsEnabled: true,
              automaticCheckpointScheduler: injected ? h.scheduler : null,
              attendancePermissions: h.permissions,
              now: () => checkpoint_fixture.now,
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(h.reports, hasLength(2));
        expect(find.text('Presença automática'), findsNothing);
        tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
        tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        );
        await tester.pumpAndSettle();
        expect(h.calls.where((c) => c.$1 == 'schedule'), hasLength(2));
        expect(h.logger.errors, isEmpty);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
  testWidgets(
    'hub late sessions and catalog retain terminal telemetry after disposal',
    (tester) async {
      final course = CourseRecord(
        id: 'poo',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final sessions = Completer<List<SessionRecord>>();
      final catalog = Completer<PythonMoodleContentDiscovery>();
      final store = _HubLogStore();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CourseHubPage(
            course: course,
            allCourses: [course],
            courseRepository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository()
              ..pending = sessions.future,
            ufmgSessionGateway: _UFMGGateway()..pendingCatalog = catalog.future,
            logger: FirestoreAppLogger(
              store: store,
              currentUserId: () => 'owner',
              platform: 'web',
            ),
            now: () => now,
          ),
        ),
      );
      await tester.pump();
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      sessions.complete([]);
      catalog.complete(
        const PythonMoodleContentDiscovery(
          courses: [],
          candidateTotal: 0,
          metaturmaCandidateTotal: 0,
        ),
      );
      await tester.pumpAndSettle();
      for (final event in [
        'course_hub_read_succeeded',
        'course_hub_catalog_succeeded',
      ]) {
        expect(
          store.documents
              .where((row) => row['event'] == event)
              .any(
                (row) =>
                    (jsonDecode(row['details']! as String)
                        as Map)['applied_to_view'] ==
                    false,
              ),
          true,
        );
      }
    },
  );
  testWidgets(
    'hub upcoming row opens the correct calendar week with course filter',
    (tester) async {
      final course = CourseRecord(
        id: 'poo',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CourseHubPage(
            course: course,
            allCourses: [course],
            courseRepository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            logger: _RecordingAppLogger(),
            now: () => now,
            datesByCourse: {
              'poo': [
                PythonMoodleDate(
                  id: 'event',
                  courseId: 'poo',
                  courseCode: 'DCC203',
                  title: 'Entrega futura',
                  dueAt: DateTime.utc(2026, 10, 5, 12),
                  kind: 'assignment',
                ),
              ],
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Entrega futura'));
      await tester.tap(find.text('Entrega futura'));
      await tester.pumpAndSettle();
      expect(find.text('05/10/2026 – 11/10/2026'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Entrega futura'), findsOneWidget);
    },
  );
  testWidgets(
    'course hub opens the owned activity workspace through both gateway configurations',
    (tester) async {
      final course = CourseRecord(
        id: 'poo',
        code: 'ELE631',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      for (final explicit in [true, false]) {
        final gateway = _WorkspaceGateway();
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            key: UniqueKey(),
            home: CourseHubPage(
              course: course,
              allCourses: [course],
              courseRepository: _FakeCourseRepository(courses: [course]),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository({'poo': []}),
              logger: _RecordingAppLogger(),
              now: () => now,
              workspaceGateway: explicit ? gateway : null,
              ufmgSessionGateway: explicit ? null : gateway,
            ),
          ),
        );
        await tester.pumpAndSettle();
        final action = find.byKey(const Key('course-hub-workspace'));
        await tester.ensureVisible(action);
        await tester.tap(action);
        await tester.pumpAndSettle();
        expect(
          find.text('Nenhuma atividade disponível nesta disciplina.'),
          findsOneWidget,
        );
        expect(gateway.requested, 'poo');
        if (!explicit) {
          await tester.tap(find.text('Sincronizar Moodle'));
          await tester.pumpAndSettle();
          expect(find.byKey(const Key('ufmg-username')), findsOneWidget);
          await tester.pageBack();
          await tester.pumpAndSettle();
        }
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('course-hub-workspace')), findsOneWidget);
      }
    },
  );
  testWidgets(
    'hub refreshes metadata and sessions on schedule return, retaining data on failure',
    (tester) async {
      CourseRecord makeCourse(String name) => CourseRecord(
        id: 'poo',
        code: 'DCC203',
        name: name,
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final repository = _FakeCourseRepository(courses: [makeCourse('POO')]);
      final meetings = _FakeMeetingRepository();
      final sessions = _FakeSessionRepository({'poo': []});
      final updates = ValueNotifier<AcademicOverviewSnapshot?>(
        AcademicOverviewSnapshot(
          courses: repository.courses,
          sessionsByCourse: const {'poo': []},
        ),
      );
      addTearDown(updates.dispose);
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CourseHubPage(
            course: repository.courses.single,
            allCourses: repository.courses,
            courseRepository: repository,
            meetingRepository: meetings,
            sessionRepository: sessions,
            overviewUpdates: updates,
            initialSessionsByCourse: const {'poo': []},
            logger: logger,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('course-hub-open-schedule')),
      );
      await tester.tap(find.byKey(const Key('course-hub-open-schedule')));
      await tester.pumpAndSettle();
      repository.courses[0] = makeCourse('POO atualizada');
      sessions.sessions['poo'] = [
        SessionRecord(
          id: 'new',
          startsAt: now.add(const Duration(days: 1)),
          endsAt: now.add(const Duration(days: 1, hours: 2)),
          lessonCount: QuantidadeAulas.two,
          callCount: NumeroChamadas.one,
          assessmentTitle: 'Prova nova',
          createdAt: now,
          updatedAt: now,
        ),
      ];
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('POO atualizada'), findsOneWidget);
      expect(find.text('Prova nova'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const Key('course-hub-open-calendar')),
      );
      await tester.tap(find.byKey(const Key('course-hub-open-calendar')));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Próximo período'));
      await tester.pumpAndSettle();
      await calendarDisplay(tester, 'Lista');
      await tester.pumpAndSettle();
      expect(find.textContaining('Prova nova'), findsOneWidget);
      await tester.pageBack();
      await tester.pumpAndSettle();
      sessions.listError = StateError('offline');
      meetings.listError = StateError('offline');
      repository.listError = StateError('offline');
      await tester.ensureVisible(
        find.byKey(const Key('course-hub-open-schedule')),
      );
      await tester.tap(find.byKey(const Key('course-hub-open-schedule')));
      await tester.pumpAndSettle();
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(find.text('Prova nova'), findsOneWidget);
      expect(find.byKey(const Key('course-hub-retry')), findsOneWidget);
      sessions.listError = null;
      meetings.listError = null;
      repository.listError = null;
      await tester.ensureVisible(find.byKey(const Key('course-hub-retry')));
      await tester.tap(find.byKey(const Key('course-hub-retry')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('course-hub-retry')), findsNothing);
      expect(
        logger.errorContexts,
        containsAll(['course_hub_sessions_failed', 'course_hub_course_failed']),
      );
    },
  );

  testWidgets('hub distinguishes catalog failure from empty and retries', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'poo',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final gateway = _UFMGGateway()
      ..catalogError = StateError('catalog unavailable');
    final logStore = _HubLogStore();
    final logger = FirestoreAppLogger(
      store: logStore,
      currentUserId: () => 'owner',
      platform: 'web',
    );
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CourseHubPage(
          course: course,
          allCourses: [course],
          courseRepository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          logger: logger,
          now: () => now,
          ufmgSessionGateway: gateway,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível atualizar os materiais.'),
      findsOneWidget,
    );
    expect(
      find.text('Nenhum material sincronizado para esta disciplina.'),
      findsNothing,
    );
    final failed = logStore.documents.singleWhere(
      (d) => d['operation'] == 'course_hub_catalog_failed',
    );
    final details =
        jsonDecode(failed['errorDetails']! as String) as Map<String, dynamic>;
    expect(details['stage'], 'catalog');
    expect(details['course_id'], 'poo');
    expect(details['cause_type'], 'StateError');
    expect(failed['correlationId'], isNotEmpty);
    gateway.catalogError = null;
    await tester.ensureVisible(
      find.byKey(const Key('course-hub-retry-materials')),
    );
    await tester.tap(find.byKey(const Key('course-hub-retry-materials')));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível atualizar os materiais.'), findsNothing);
    expect(
      find.text('Nenhum material sincronizado para esta disciplina.'),
      findsOneWidget,
    );
  });

  testWidgets(
    'open hub and calendar update after sync, preserving partial results and local time',
    (tester) async {
      final course = CourseRecord(
        id: 'poo',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final updates = ValueNotifier<AcademicOverviewSnapshot?>(null);
      addTearDown(updates.dispose);
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CourseHubPage(
            course: course,
            allCourses: [course],
            courseRepository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            initialSessionsByCourse: const {'poo': []},
            logger: logger,
            now: () => now,
            overviewUpdates: updates,
          ),
        ),
      );
      await tester.pumpAndSettle();
      updates.value = AcademicOverviewSnapshot(
        courses: [course],
        sessionsByCourse: {'poo': []},
        unavailableDateCourses: {'poo'},
        datesByCourse: {
          'poo': [
            PythonMoodleDate(
              id: 'moodle-1',
              courseId: 'poo',
              courseCode: 'DCC203',
              title: 'Entrega meia-noite',
              kind: 'assignment',
              dueAt: DateTime.utc(2026, 9, 28, 1),
            ),
          ],
        },
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Entrega meia-noite'));
      expect(find.text('Entrega meia-noite'), findsOneWidget);
      expect(find.textContaining('Datas não atualizadas'), findsOneWidget);
      await tester.ensureVisible(
        find.byKey(const Key('course-hub-open-calendar')),
      );
      await tester.tap(find.byKey(const Key('course-hub-open-calendar')));
      await tester.pumpAndSettle();
      await calendarDisplay(tester, 'Lista');
      await tester.pumpAndSettle();
      expect(find.text('POO • 27/09/2026'), findsOneWidget);
      expect(find.textContaining('22:00 • Prazo'), findsOneWidget);
      expect(find.textContaining('Algumas datas'), findsOneWidget);
      updates.value = AcademicOverviewSnapshot(
        courses: [course],
        sessionsByCourse: {'poo': []},
        datesByCourse: const {},
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('Entrega meia-noite'), findsNothing);
      expect(find.textContaining('Algumas datas'), findsNothing);
      await tester.pageBack();
      await tester.pumpAndSettle();
      updates.value = AcademicOverviewSnapshot(
        courses: [course],
        sessionsByCourse: const {},
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('Nenhuma avaliação'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  for (final width in [390.0, 1200.0]) {
    testWidgets(
      'imported standalone deadlines reach home, course and calendar at $width',
      (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 1000));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final course = CourseRecord(
          id: 'online',
          code: 'DCC203',
          name: 'POO',
          workload: 60,
          term: '2026-2',
          modality: CourseModality.online,
          attendancePolicy: CourseAttendancePolicy.noCall,
          createdAt: now,
          updatedAt: now,
        );
        final logger = _RecordingAppLogger();
        final dates = [
          PythonMoodleDate(
            id: 'moodle-1',
            courseId: 'online',
            courseCode: 'DCC203',
            title: 'Entrega Parte 2',
            dueAt: now.add(const Duration(hours: 2)),
            kind: 'assignment',
          ),
        ];
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              repository: _FakeCourseRepository(),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository(),
              user: user,
              logger: logger,
              onSignOut: () async {},
              now: () => now,
              overviewReadsEnabled: true,
              overviewRepository: _FakeOverviewRepository(
                AcademicOverviewSnapshot(
                  courses: [course],
                  sessionsByCourse: const {},
                  datesByCourse: {'online': dates},
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Entrega Parte 2'), findsOneWidget);
        if (width < 900) {
          expect(
            tester.getTopLeft(find.text('Próximas datas')).dy,
            lessThan(tester.getTopLeft(find.text('Minhas disciplinas')).dy),
          );
        }
        expect(logger.events, contains('agenda_presented'));
        await tester.ensureVisible(find.byKey(const Key('course-card-online')));
        await tester.tap(find.byKey(const Key('course-card-online')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Entrega Parte 2'));
        expect(find.text('Entrega Parte 2'), findsOneWidget);
        await tester.ensureVisible(
          find.byKey(const Key('course-hub-open-calendar')),
        );
        await tester.tap(find.byKey(const Key('course-hub-open-calendar')));
        await tester.pumpAndSettle();
        await calendarDisplay(tester, 'Lista');
        await tester.pumpAndSettle();
        expect(find.textContaining('Entrega Parte 2'), findsOneWidget);
        expect(find.textContaining('Prazo'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }

  for (final injected in [true, false]) {
    testWidgets(
      'profile opens the permission screen without touching attendance (injected=$injected)',
      (tester) async {
        const channel = MethodChannel(
          'br.ufmg.frequencia.frequencia_ufmg/attendance_permissions',
        );
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              channel,
              (_) async => readyPermissionSnapshot,
            );
        addTearDown(
          () => TestDefaultBinaryMessengerBinding
              .instance
              .defaultBinaryMessenger
              .setMockMethodCallHandler(channel, null),
        );
        final logger = _RecordingAppLogger();
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              repository: _FakeCourseRepository(),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository(),
              user: user,
              logger: logger,
              onSignOut: () async {},
              now: () => now,
              attendancePermissions: injected ? _PermissionGateway() : null,
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('profile-menu')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('profile-permissions')), findsNothing);
        expect(find.text('Ajustes'), findsWidgets);
        await tester.pageBack();
        await tester.pumpAndSettle();
        expect(find.text('Minhas disciplinas'), findsOneWidget);
      },
    );
  }

  for (var failure = 0; failure < 3; failure++) {
    testWidgets(
      'first checkpoint route and logout cleanup (failure=$failure)',
      (tester) async {
        SharedPreferencesAsyncPlatform.instance =
            InMemorySharedPreferencesAsync.empty();
        final calls = <String>[];
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(FirstCheckpointGateway.channel, (
              call,
            ) async {
              calls.add(call.method);
              if (call.method == 'deactivate' && failure > 0) {
                throw PlatformException(code: 'storage_failed');
              }
              return call.method == 'deactivate' ? null : [];
            });
        addTearDown(
          () => TestDefaultBinaryMessengerBinding
              .instance
              .defaultBinaryMessenger
              .setMockMethodCallHandler(FirstCheckpointGateway.channel, null),
        );
        final logger = _RecordingAppLogger()..failRecording = failure == 2;
        var signedOut = false;
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              attendancePermissions: _PermissionGateway(),
              repository: _FakeCourseRepository(),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository(),
              user: user,
              logger: logger,
              onSignOut: () async {
                signedOut = true;
              },
              now: () => now,
            ),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const Key('profile-menu')));
        await tester.pumpAndSettle();
        expect(find.text('Histórico de capturas'), findsNothing);
        await tester.ensureVisible(find.text('Sair da conta'));
        await tester.tap(find.text('Sair da conta'));
        await tester.pumpAndSettle();
        expect(calls, contains('deactivate'));
        expect(signedOut, isTrue);
        if (failure > 0) {
          expect(
            logger.errorContexts,
            contains('first_checkpoint_logout_cleanup'),
          );
        }
      },
    );
  }

  testWidgets(
    'notification opens pings after loading and resume without duplicate routes',
    (tester) async {
      SharedPreferencesAsyncPlatform.instance =
          InMemorySharedPreferencesAsync.empty();
      final updates = StreamController<Map<String, Object?>>.broadcast();
      addTearDown(updates.close);
      final courses = _FakeCourseRepository()
        ..pending = Completer<List<CourseRecord>>();
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        (_) async => [],
      );
      addTearDown(
        () => messenger.setMockMethodCallHandler(
          FirstCheckpointGateway.channel,
          null,
        ),
      );
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: courses,
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            attendancePermissions: _PermissionGateway(),
            user: user,
            logger: _RecordingAppLogger(),
            onSignOut: () async {},
            now: () => now,
            checkpointDeliveryUpdates: updates.stream,
          ),
        ),
      );
      updates.add({
        'action': 'open_checkpoints',
        'account_id': 'foreign',
        'open_revision': 1,
      });
      updates.add({
        'action': 'open_checkpoints',
        'account_id': user.id,
        'open_revision': 'bad',
      });
      updates.add({
        'action': 'open_checkpoints',
        'account_id': user.id,
        'open_revision': 1,
      });
      await tester.pump();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsNothing,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      courses.pending!.complete([]);
      courses.pending = null;
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsNothing,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsOneWidget,
      );
      updates.add({
        'action': 'open_checkpoints',
        'account_id': user.id,
        'open_revision': 2,
      });
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsOneWidget,
      );
      await tester.pageBack();
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsNothing,
      );
      updates.add({
        'action': 'open_checkpoints',
        'account_id': user.id,
        'open_revision': 2,
      });
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Ajustes'),
        ),
        findsNothing,
      );
      updates.add({
        'action': 'open_checkpoints',
        'account_id': user.id,
        'open_revision': 3,
      });
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('notification navigation failure records its exact stage', (
    tester,
  ) async {
    final updates = StreamController<Map<String, Object?>>.broadcast();
    addTearDown(updates.close);
    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      MaterialApp(
        builder: (_, _) => Overlay(
          initialEntries: [
            OverlayEntry(
              builder: (_) => CoursePage(
                repository: _FakeCourseRepository(),
                meetingRepository: _FakeMeetingRepository(),
                sessionRepository: _FakeSessionRepository(),
                attendancePermissions: _PermissionGateway(),
                user: user,
                logger: logger,
                onSignOut: () async {},
                now: () => now,
                checkpointDeliveryUpdates: updates.stream,
              ),
            ),
          ],
        ),
      ),
    );
    await tester.pumpAndSettle();
    updates.add({
      'action': 'open_checkpoints',
      'account_id': user.id,
      'open_revision': 1,
    });
    await tester.pumpAndSettle();
    expect(
      logger.errorContexts,
      contains('checkpoint_notification_navigation'),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'checkpoint confirmations refresh once and defer while backgrounded',
    (tester) async {
      final updates = StreamController<Map<String, Object?>>.broadcast();
      addTearDown(updates.close);
      final courses = _FakeCourseRepository();
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: courses,
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            user: user,
            logger: logger,
            onSignOut: () async {},
            now: () => now,
            checkpointDeliveryUpdates: updates.stream,
          ),
        ),
      );
      await tester.pumpAndSettle();
      final original = courses.listCalls;
      updates.add({'account_id': 'other', 'revision': 1});
      updates.add({'account_id': user.id, 'revision': 0});
      updates.add({'account_id': user.id, 'revision': 'bad'});
      await tester.pumpAndSettle();
      expect(courses.listCalls, original);
      updates.add({'account_id': user.id, 'revision': 1});
      await tester.pumpAndSettle();
      expect(courses.listCalls, original + 1);
      updates.add({'account_id': user.id, 'revision': 1});
      await tester.pumpAndSettle();
      expect(courses.listCalls, original + 1);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      updates.add({'account_id': user.id, 'revision': 2});
      await tester.pumpAndSettle();
      expect(courses.listCalls, original + 1);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(courses.listCalls, original + 2);
      updates.addError(StateError('native stream failed'));
      await tester.pumpAndSettle();
      expect(logger.errorContexts, contains('checkpoint_delivery_updates'));
      expect(logger.events, contains('checkpoint_delivery_ui_refresh'));
      logger.failDeliveryLog = true;
      updates.add({'account_id': user.id, 'revision': 3});
      await tester.pumpAndSettle();
      expect(courses.listCalls, original + 3);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test('derives the academic term from the calendar half-year', () {
    expect(academicTermFor(DateTime(2026, 1, 1)), '2026-1');
    expect(academicTermFor(DateTime(2026, 6, 30)), '2026-1');
    expect(academicTermFor(DateTime(2026, 7, 1)), '2026-2');
    expect(academicTermFor(DateTime(2026, 12, 31)), '2026-2');
  });

  testWidgets("recovering yesterday's result does not postpone a due refresh", (
    tester,
  ) async {
    final gateway = _RecoveredUFMGGateway();
    gateway.progress.response.complete(syncResult(partial: true));
    final schedule = _FakeUFMGSyncSchedule(due: true);
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          ufmgSessionGateway: gateway,
          academicSyncSchedule: schedule,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(gateway.progress.calls, 2);
    expect(schedule.deadlines.length, 2);
    await tester.pumpWidget(const SizedBox());
    await gateway.progress.updates.close();
  });

  for (final scenario in [
    'success',
    'not_due',
    'expired',
    'not_connected',
    'job_failure',
    'schedule_failure',
    'schedule_read_failure',
  ]) {
    testWidgets('automatic academic synchronization: $scenario', (
      tester,
    ) async {
      final gateway = _ProgressUFMGGateway(
        connected: !['expired', 'not_connected'].contains(scenario),
        reauthenticationRequired: scenario == 'expired',
      );
      final schedule = _FakeUFMGSyncSchedule(
        due: scenario != 'not_due',
        failRecording: scenario == 'schedule_failure',
        failReading: scenario == 'schedule_read_failure',
      );
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            user: user,
            logger: logger,
            onSignOut: () async {},
            ufmgSessionGateway: gateway,
            academicSyncSchedule: schedule,
            now: () => now,
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));
      final shouldStart = [
        'success',
        'job_failure',
        'schedule_failure',
      ].contains(scenario);
      expect(gateway.progress.calls, shouldStart ? 1 : 0);
      if (shouldStart) {
        expect(find.text('Minhas disciplinas'), findsOneWidget);
        if (scenario == 'job_failure') {
          gateway.progress.response.completeError(
            StateError('worker unavailable'),
          );
        } else {
          gateway.progress.response.complete(syncResult(partial: true));
        }
      }
      await tester.pumpAndSettle();
      if (scenario == 'not_due') {
        expect(logger.events, contains('academic_auto_sync_skipped'));
      }
      if (scenario == 'expired') {
        expect(find.textContaining('Reconecte à UFMG'), findsOneWidget);
      }
      if (scenario == 'job_failure') {
        expect(logger.errorContexts, contains('academic_auto_sync'));
        expect(
          schedule.deadlines.last,
          now.toUtc().add(const Duration(minutes: 15)),
        );
      }
      if (scenario == 'success') {
        expect(
          schedule.deadlines.last,
          now.toUtc().add(const Duration(hours: 6)),
        );
      }
      if (scenario == 'schedule_failure') {
        expect(logger.errorContexts, contains('academic_auto_schedule_write'));
      }
      await tester.pumpWidget(const SizedBox());
      await gateway.progress.updates.close();
    });
  }

  for (final width in [390.0, 1200.0]) {
    for (final navigation in [false, true]) {
      testWidgets(
        'sync indicator leaves floating actions reachable width=$width navigation=$navigation',
        (tester) async {
          tester.view.devicePixelRatio = 1;
          tester.view.physicalSize = Size(width, 844);
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final gateway = _ProgressUFMGGateway();
          await tester.pumpWidget(
            _NavigationApp(
              builder: (context, child) => AcademicSyncHost(child: child!),
              home: CoursePage(
                repository: _FakeCourseRepository(),
                meetingRepository: _FakeMeetingRepository(),
                sessionRepository: _FakeSessionRepository(),
                user: user,
                logger: _RecordingAppLogger(),
                onSignOut: () async {},
                ufmgSessionGateway: gateway,
                academicSyncSchedule: _FakeUFMGSyncSchedule(due: true),
                now: () => now,
              ),
            ),
          );
          await tester.pump(const Duration(milliseconds: 100));
          await tester.pumpAndSettle();
          expect(
            find.byKey(const Key('academic-sync-indicator')),
            findsOneWidget,
          );
          var taps = 0;
          unawaited(
            Navigator.of(tester.element(find.byType(CoursePage))).push<void>(
              MaterialPageRoute(
                builder: (_) => Scaffold(
                  appBar: AppBar(title: const Text('Prazos')),
                  bottomNavigationBar: navigation
                      ? NavigationBar(
                          destinations: const [
                            NavigationDestination(
                              icon: Icon(Icons.home),
                              label: 'Início',
                            ),
                            NavigationDestination(
                              icon: Icon(Icons.calendar_month),
                              label: 'Calendário',
                            ),
                          ],
                        )
                      : null,
                  floatingActionButton: FloatingActionButton.extended(
                    key: const Key('test-deadline-action'),
                    onPressed: () => taps++,
                    label: const Text('Adicionar prazo'),
                  ),
                  body: ListView(
                    children: [
                      const SizedBox(height: 400),
                      TextButton(
                        key: const Key('test-inline-action'),
                        onPressed: () => taps++,
                        child: const Text('Editar registro'),
                      ),
                      const SizedBox(height: 900),
                    ],
                  ),
                ),
              ),
            ),
          );
          await tester.pumpAndSettle();
          for (final completed in [false, true]) {
            if (completed) {
              gateway.progress.response.complete(syncResult(partial: true));
              await tester.pumpAndSettle();
            }
            final indicator = tester.getRect(
              find.byKey(const Key('academic-sync-indicator')),
            );
            final action = tester.getRect(
              find.byKey(const Key('test-deadline-action')),
            );
            expect(indicator.overlaps(action), isFalse);
            expect(
              indicator.overlaps(tester.getRect(find.byType(ListView))),
              isFalse,
            );
            await tester.tap(find.byKey(const Key('test-deadline-action')));
            await tester.pump();
            expect(taps, completed ? 3 : 1);
            final inline = find.byKey(const Key('test-inline-action'));
            await tester.ensureVisible(inline);
            await tester.pumpAndSettle();
            expect(indicator.overlaps(tester.getRect(inline)), isFalse);
            await tester.tap(inline);
            await tester.pump();
            expect(taps, completed ? 4 : 2);
          }
          await tester.tap(find.byTooltip('Ocultar sincronização'));
          await tester.pumpAndSettle();
          expect(
            find.byKey(const Key('academic-sync-indicator')),
            findsNothing,
          );
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox());
          await gateway.progress.updates.close();
        },
      );
    }
  }

  testWidgets(
    'sync survives leaving the connection page and remains visible above the calendar',
    (tester) async {
      final gateway = _ProgressUFMGGateway();
      final logger = _RecordingAppLogger();
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            user: user,
            logger: logger,
            onSignOut: () async {},
            ufmgSessionGateway: gateway,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('profile-menu')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('settings-academic-account')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ufmg-manage-connection')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ufmg-force-refresh')));
      await tester.tap(find.byKey(const Key('ufmg-force-refresh')));
      await tester.pump();
      await tester.ensureVisible(find.byKey(const Key('ufmg-sync-all')));
      await tester.tap(find.byKey(const Key('ufmg-sync-all')));
      await tester.pump();
      expect(gateway.progress.lastForce, isTrue);
      await tester.pump(const Duration(milliseconds: 100));
      expect(gateway.progress.calls, 1);
      expect(find.byKey(const Key('academic-sync-indicator')), findsOneWidget);
      Navigator.of(tester.element(find.text('Conta acadêmica UFMG'))).pop();
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('nav-general-calendar')));
      await tester.pumpAndSettle();
      gateway.progress.updates.add(
        AcademicSyncProgress(
          operationId: gateway.progress.operationId!,
          completed: 1,
          status: 'running',
        ),
      );
      await tester.pump();
      expect(find.text('Datas e materiais'), findsOneWidget);
      expect(find.text('Calendário'), findsWidgets);
      gateway.progress.response.complete(syncResult(partial: true));
      await tester.pumpAndSettle();
      expect(gateway.progress.calls, 1);
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Ver resultado'));
      await tester.pumpAndSettle();
      expect(find.text('Revisar última sincronização'), findsOneWidget);
      await tester.ensureVisible(find.text('Revisar última sincronização'));
      await tester.tap(find.text('Revisar última sincronização'));
      await tester.pumpAndSettle();
      expect(gateway.progress.calls, 1);
      await tester.tap(find.text('Entendi'));
      await tester.pumpAndSettle();
      gateway.failDates = true;
      await tester.ensureVisible(find.text('Revisar última sincronização'));
      await tester.tap(find.text('Revisar última sincronização'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('não foi possível carregar a revisão'),
        findsNothing,
      );
      expect(gateway.progress.calls, 1);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      await gateway.progress.updates.close();
    },
  );

  testWidgets(
    'online courses have no attendance pendency or timetable action in the hub',
    (tester) async {
      final course = CourseRecord(
        id: 'online',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        modality: CourseModality.online,
        attendancePolicy: CourseAttendancePolicy.noCall,
        createdAt: now,
        updatedAt: now,
      );
      final repository = _FakeCourseRepository(courses: [course]);
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: repository,
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository({
              'online': [
                _session('pending', now.subtract(const Duration(days: 3))),
              ],
            }),
            user: user,
            logger: _RecordingAppLogger(),
            onSignOut: () async {},
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('past-attendance-pending-alert')),
        findsNothing,
      );
      await tester.ensureVisible(find.byKey(const Key('course-card-online')));
      await tester.tap(find.byKey(const Key('course-card-online')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Frequência: não se aplica'), findsOneWidget);
      expect(find.byKey(const Key('course-hub-open-attendance')), findsNothing);
      expect(find.byKey(const Key('course-hub-schedule')), findsNothing);
      expect(find.byKey(const Key('course-hub-agenda')), findsOneWidget);
    },
  );

  testWidgets('shows loading, empty state, and reloads after an error', (
    tester,
  ) async {
    final repository = _FakeCourseRepository()
      ..listError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível carregar suas disciplinas.'),
      findsOneWidget,
    );
    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();

    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
    expect(find.text('Adicionar disciplina'), findsNWidgets(2));
  });

  testWidgets('creates, edits, and deletes a course', (tester) async {
    final repository = _FakeCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
    await tester.enterText(
      find.byKey(const Key('course-name')),
      'Programação Orientada a Objetos',
    );
    expect(find.byKey(const Key('course-workload')), findsNothing);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.id, 'course-1');
    expect(repository.courses.single.term, '2026-2');
    expect(repository.courses.single.startsOn, DateTime.utc(2026, 7));
    expect(repository.courses.single.endsOn, DateTime.utc(2026, 12, 31));
    expect(repository.courses.single.createdAt, now);
    expect(find.text('DCC203'), findsOneWidget);
    expect(find.text('Programação Orientada a Objetos'), findsOneWidget);
    expect(find.text('2026-2'), findsOneWidget);
    expect(find.byKey(const Key('course-mark-course-1')), findsOneWidget);

    await _selectCourseAction(tester, 'DCC203', 'Editar');
    await tester.enterText(find.byKey(const Key('course-name')), 'POO');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.name, 'POO');
    expect(repository.courses.single.createdAt, now);
    expect(repository.courses.single.updatedAt, now);
    expect(find.text('POO'), findsOneWidget);

    await _selectCourseAction(tester, 'DCC203', 'Excluir');
    expect(find.text('Excluir disciplina?'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
    await tester.pumpAndSettle();
    expect(repository.courses, hasLength(1));

    await _selectCourseAction(tester, 'DCC203', 'Excluir');
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();

    expect(repository.courses, isEmpty);
    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
  });

  testWidgets('creates a distinct course when another course already exists', (
    tester,
  ) async {
    final existing = CourseRecord(
      id: 'existing-course',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [existing]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: logger,
          onSignOut: () async {},
          now: () => now,
          idGenerator: () => 'new-course',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _fillNewCourse(tester, code: 'DCC204', name: 'Algoritmos');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, hasLength(2));
    expect(repository.courses.map((course) => course.id), {
      'existing-course',
      'new-course',
    });
    expect(
      logger.events,
      containsAllInOrder([
        'course_create_editor_opened',
        'course_create_started',
        'course_create_succeeded',
      ]),
    );
  });

  testWidgets('rejects duplicate course codes ignoring letter case', (
    tester,
  ) async {
    final existing = CourseRecord(
      id: 'existing-course',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [existing]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester, code: 'dcc203', name: 'Outra disciplina');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, [existing]);
    expect(
      find.text('Já existe uma disciplina com o código DCC203.'),
      findsOneWidget,
    );
    expect(logger.events, contains('course_create_duplicate_code'));
  });

  testWidgets('hides the automatic term on creation and allows editing it', (
    tester,
  ) async {
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-term')), findsNothing);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    await _selectCourseAction(tester, 'DCC203', 'Editar');
    expect(find.byKey(const Key('course-term')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('course-term')), '2027-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.term, '2027-1');
  });

  testWidgets('rejects editing a course outside current or next term', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC203', 'Editar');
    await tester.enterText(find.byKey(const Key('course-term')), '2026-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(
      find.text('Escolha o período atual (2026-2) ou o próximo (2027-1).'),
      findsOneWidget,
    );
    expect(repository.courses.single.term, '2026-2');
  });

  testWidgets('preserves a custom date range while editing metadata', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      startsOn: DateTime.utc(2026, 8, 3),
      endsOn: DateTime.utc(2026, 11, 30),
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC203', 'Editar');
    await tester.enterText(find.byKey(const Key('course-name')), 'POO editada');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.startsOn, DateTime.utc(2026, 8, 3));
    expect(repository.courses.single.endsOn, DateTime.utc(2026, 11, 30));
  });

  testWidgets('moves untouched default dates when the term changes', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      startsOn: DateTime.utc(2026, 7),
      endsOn: DateTime.utc(2026, 12, 31),
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC203', 'Editar');
    await tester.enterText(find.byKey(const Key('course-term')), '2027-1');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.startsOn, DateTime.utc(2027));
    expect(repository.courses.single.endsOn, DateTime.utc(2027, 6, 30));
  });

  testWidgets(
    'expiration diagnostics persist course and term on success and failure',
    (tester) async {
      for (final fails in [false, true]) {
        final expired = CourseRecord(
          id: 'expired',
          code: 'DCC100',
          name: 'Antiga',
          workload: 60,
          term: '2026-1',
          createdAt: DateTime.utc(2026),
          updatedAt: now,
        );
        final repository = _FakeCourseRepository(courses: [expired]);
        if (fails) repository.deleteError = StateError('store unavailable');
        final store = _HubLogStore();
        final logger = FirestoreAppLogger(
          store: store,
          currentUserId: () => 'owner',
          platform: 'web',
        );
        await tester.pumpWidget(_app(repository, user, now, logger: logger));
        await tester.pumpAndSettle();
        final row = store.documents.singleWhere(
          (d) => fails
              ? d['operation'] == 'course_expiration_delete'
              : d['event'] == 'course_expiration_delete_succeeded',
        );
        final details =
            jsonDecode(row[fails ? 'errorDetails' : 'details']! as String)
                as Map<String, dynamic>;
        expect(details['course_id'], 'expired');
        expect(details['term'], '2026-1');
        expect(details['stage'], 'expiration_delete');
        expect(row['durationMs'], isA<int>());
        expect(row['correlationId'], isNotEmpty);
        expect(repository.courses, fails ? hasLength(1) : isEmpty);
        await tester.pumpWidget(const SizedBox());
        await tester.pumpAndSettle();
      }
    },
  );

  testWidgets('deletes expired previous courses on the first load', (
    tester,
  ) async {
    final expired = CourseRecord(
      id: 'old-course',
      code: 'DCC100',
      name: 'Antiga',
      workload: 60,
      term: '2026-1',
      startsOn: DateTime.utc(2026),
      endsOn: DateTime.utc(2026, 6, 30),
      createdAt: DateTime.utc(2026),
      updatedAt: DateTime.utc(2026),
    );
    final current = CourseRecord(
      id: 'current-course',
      code: 'DCC203',
      name: 'Atual',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [expired, current]);

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();

    expect(repository.deletedIds, ['old-course']);
    expect(find.text('DCC100'), findsNothing);
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('keeps an expired course visible when automatic cleanup fails', (
    tester,
  ) async {
    final expired = CourseRecord(
      id: 'old-course',
      code: 'DCC100',
      name: 'Antiga',
      workload: 60,
      term: '2026-1',
      startsOn: DateTime.utc(2026),
      endsOn: DateTime.utc(2026, 6, 30),
      createdAt: DateTime.utc(2026),
      updatedAt: DateTime.utc(2026),
    );
    final repository = _FakeCourseRepository(courses: [expired])
      ..deleteError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();

    expect(find.text('DCC100'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('opens a course hub with academic sections and focused routes', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course]);
    final meetingRepository = _FakeMeetingRepository(
      meetings: {
        'course-1': [
          MeetingRecord(
            id: 'meeting-1',
            weekday: DateTime.monday,
            startMinutes: 19 * 60,
            endMinutes: 20 * 60 + 40,
            lessonCount: QuantidadeAulas.two,
            callCount: NumeroChamadas.one,
            createdAt: now,
            updatedAt: now,
          ),
          MeetingRecord(
            id: 'meeting-2',
            weekday: DateTime.monday,
            startMinutes: 21 * 60,
            endMinutes: 22 * 60 + 40,
            lessonCount: QuantidadeAulas.two,
            callCount: NumeroChamadas.one,
            createdAt: now,
            updatedAt: now,
          ),
        ],
      },
    );
    final sessions = _FakeSessionRepository({
      'course-1': [
        SessionRecord(
          id: 'session-1',
          startsAt: DateTime.utc(2026, 10, 19, 22),
          endsAt: DateTime.utc(2026, 10, 19, 23, 40),
          lessonCount: QuantidadeAulas.two,
          callCount: NumeroChamadas.one,
          absences: 0,
          assessmentTitle: 'Trabalho prático',
          createdAt: now,
          updatedAt: now,
        ),
      ],
    });
    final ufmgGateway = _UFMGGateway(
      materialCatalog: PythonMoodleContentDiscovery(
        courses: [
          PythonMoodleCourseContent(
            courseId: 'catalog-course',
            courseCode: 'DCC203',
            term: '2026-2',
            moodleCourseId: '3701',
            status: PythonMoodleContentStatus.found,
            candidates: [
              PythonMoodleContentCandidate(
                sourceId: '101',
                moodleCourseId: '3701',
                kind: 'page',
                title: 'Plano de ensino',
                url: Uri.parse(
                  'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
                ),
                relevance: 'teaching_plan',
                origin: PythonMoodleContentOrigin.canonical,
              ),
            ],
          ),
        ],
        candidateTotal: 1,
        metaturmaCandidateTotal: 0,
      ),
    );

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: meetingRepository,
          sessionRepository: sessions,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
          ufmgSessionGateway: ufmgGateway,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('course-card-course-1')));
    await tester.pumpAndSettle();

    expect(find.text('DCC203'), findsOneWidget);
    expect(find.text('POO'), findsOneWidget);
    expect(find.byKey(const Key('course-hub-identity')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-course-mark')), findsOneWidget);
    expect(
      find.byKey(const Key('course-hub-frequency-summary')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('course-hub-section-grid')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-frequency')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-agenda')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-open-schedule')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-materials')), findsOneWidget);
    expect(sessions.listedCourseIds, contains('course-1'));
    expect(find.textContaining('Trabalho prático'), findsOneWidget);
    expect(find.textContaining('Segunda'), findsNothing);
    expect(find.text('1 material disponível'), findsOneWidget);
    expect(meetingRepository.listedCourseIds, isEmpty);

    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-calendar')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-calendar')));
    await tester.pumpAndSettle();
    expect(find.text('Agenda'), findsOneWidget);
    expect(find.text('POO'), findsWidgets);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-attendance')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-attendance')));
    await tester.pumpAndSettle();
    expect(find.text('Frequência • POO'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-schedule')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-schedule')));
    await tester.pumpAndSettle();
    expect(find.text('Grade • POO'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('DCC203'), findsOneWidget);

    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-materials')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-materials')));
    await tester.pumpAndSettle();
    expect(find.text('Materiais • POO'), findsOneWidget);
    await tester.tap(find.byKey(const Key('moodle-content-catalog-course')));
    await tester.pumpAndSettle();
    expect(find.text('Plano de ensino'), findsOneWidget);
    ufmgGateway.catalogError = StateError('transient catalog read');
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('1 material disponível'), findsOneWidget);
    expect(
      find.text('Não foi possível atualizar os materiais.'),
      findsOneWidget,
    );
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-card-course-1')), findsOneWidget);
  });

  testWidgets('uses compact navigation for calendar and absence snapshot', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byKey(const Key('nav-home')), findsOneWidget);
    await tester.tap(find.byKey(const Key('nav-absence-dashboard')));
    await tester.pumpAndSettle();
    expect(find.text('Faltas restantes'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('nav-general-calendar')));
    await tester.pumpAndSettle();
    expect(find.text('Agenda'), findsOneWidget);
  });

  testWidgets('shows the compact pending action and segmented absence bar', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 900));
    final course = CourseRecord(
      id: 'course-compact',
      code: 'ELE028',
      name: 'Laboratório de Circuitos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final recorded = SessionRecord(
      id: 'recorded',
      startsAt: DateTime.utc(2026, 9, 20, 22),
      endsAt: DateTime.utc(2026, 9, 20, 23, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      absences: 2,
      createdAt: now,
      updatedAt: now,
    );
    final pending = _session('pending', DateTime.utc(2026, 9, 26, 22));

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository({
            course.id: [recorded, pending],
          }),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('course-card-course-compact')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('course-hub-pending-action')), findsOneWidget);
    expect(find.byKey(const Key('course-hub-frequency-track')), findsOneWidget);
    expect(
      find.byKey(const Key('course-hub-frequency-limit-marker')),
      findsOneWidget,
    );
    expect(find.text('Resolver agora'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.binding.setSurfaceSize(const Size(900, 900));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-hub-pending-action')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('does not offer to resolve non-attendance sessions', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-inactive',
      code: 'ELE028',
      name: 'Laboratório de Circuitos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final sessions = _FakeSessionRepository({
      course.id: [
        _session(
          'cancelled',
          DateTime.utc(2026, 9, 24, 12),
          status: SessionCalendarStatus.cancelled,
        ),
        _session(
          'holiday',
          DateTime.utc(2026, 9, 25, 12),
          status: SessionCalendarStatus.holiday,
        ),
        _session(
          'no-call',
          DateTime.utc(2026, 9, 26, 12),
          status: SessionCalendarStatus.noCall,
        ),
      ],
    });

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: sessions,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const Key('past-attendance-pending-alert')),
      findsNothing,
    );
    await tester.tap(find.byKey(const Key('course-card-course-inactive')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-hub-pending-action')), findsNothing);
    expect(find.text('Resolver agora'), findsNothing);
    expect(find.byKey(const Key('course-hub-open-attendance')), findsOneWidget);
  });

  testWidgets('keeps independent hub sections useful after partial failures', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final meetings = _FakeMeetingRepository()
      ..listError = StateError('meeting offline');
    final sessions = _FakeSessionRepository()
      ..listError = StateError('session offline');
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: meetings,
          sessionRepository: sessions,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('course-card-course-1')));
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível carregar a frequência agora.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('course-hub-open-schedule')), findsOneWidget);
    expect(
      find.text('Nenhum material sincronizado para esta disciplina.'),
      findsOneWidget,
    );
    final materialsButton = tester.widget<TextButton>(
      find.byKey(const Key('course-hub-open-materials')),
    );
    expect(materialsButton.onPressed, isNull);
  });

  testWidgets('loads and reuses one Python overview snapshot', (tester) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final sessionRepository = _FakeSessionRepository();
    final courseRepository = _FakeCourseRepository();
    final overview = _FakeOverviewRepository(
      AcademicOverviewSnapshot(
        courses: [course],
        sessionsByCourse: {
          'course-1': [_session('past', DateTime.utc(2026, 9, 26, 12))],
        },
      ),
    );

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: courseRepository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: sessionRepository,
          overviewRepository: overview,
          overviewReadsEnabled: true,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('1 aula anterior está sem frequência'), findsOneWidget);
    expect(overview.loadCalls, 1);
    expect(courseRepository.listCalls, 0);
    expect(sessionRepository.listedCourseIds, isEmpty);

    await tester.tap(find.byKey(const Key('nav-absence-dashboard')));
    await tester.pumpAndSettle();

    expect(find.text('Faltas restantes'), findsOneWidget);
    expect(sessionRepository.listedCourseIds, isEmpty);
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(overview.loadCalls, 2);

    await tester.tap(find.byKey(const Key('nav-general-calendar')));
    await tester.pumpAndSettle();

    expect(find.text('Agenda'), findsOneWidget);
    expect(sessionRepository.listedCourseIds, isEmpty);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('course-card-course-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-hub-frequency')), findsOneWidget);
    expect(sessionRepository.listedCourseIds, isEmpty);
    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-attendance')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-attendance')));
    await tester.pumpAndSettle();
    final beforeRefresh = overview.loadCalls;
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(overview.loadCalls, beforeRefresh + 1);
    expect(sessionRepository.listedCourseIds, isEmpty);
    overview.error = StateError('backend unavailable');
    courseRepository.listError = StateError('fallback unavailable');
    await tester.ensureVisible(
      find.byKey(const Key('course-hub-open-attendance')),
    );
    await tester.tap(find.byKey(const Key('course-hub-open-attendance')));
    await tester.pumpAndSettle();
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-hub-retry')), findsOneWidget);
    overview.error = null;
    courseRepository.listError = null;
    await tester.ensureVisible(find.byKey(const Key('course-hub-retry')));
    await tester.tap(find.byKey(const Key('course-hub-retry')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-hub-retry')), findsNothing);
  });

  testWidgets('shows the next assessment dates from the overview snapshot', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final course = CourseRecord(
      id: 'course-dates',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final sessions = [
      _session('plain', now.add(const Duration(days: 1))),
      _session(
        'cancelled',
        now.add(const Duration(days: 2)),
        status: SessionCalendarStatus.cancelled,
        assessmentTitle: 'Ignorada',
      ),
      _session(
        'holiday',
        now.add(const Duration(days: 3)),
        status: SessionCalendarStatus.holiday,
        assessmentTitle: 'Também ignorada',
      ),
      for (var day = 4; day <= 7; day++)
        _session(
          'assessment-$day',
          now.add(Duration(days: day)),
          assessmentTitle: 'Avaliação $day',
        ),
    ];
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          overviewRepository: _FakeOverviewRepository(
            AcademicOverviewSnapshot(
              courses: [course],
              sessionsByCourse: {'course-dates': sessions},
            ),
          ),
          overviewReadsEnabled: true,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      tester.getTopLeft(find.text('Próximas datas')).dy,
      lessThan(tester.getTopLeft(find.text('Minhas disciplinas')).dy),
    );

    expect(find.text('Avaliação 4'), findsOneWidget);
    expect(find.text('Avaliação 5'), findsOneWidget);
    expect(find.text('Avaliação 6'), findsOneWidget);
    expect(find.text('Avaliação 7'), findsNothing);
    expect(find.text('Ignorada'), findsNothing);
    await tester.tap(find.text('Ver calendário'));
    await tester.pumpAndSettle();
    expect(find.text('Agenda'), findsOneWidget);
  });

  testWidgets('warns when disciplines come from the saved offline copy', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final savedSession = _session(
      'saved-session',
      now.subtract(const Duration(days: 1)),
    );
    final directSessions = _FakeSessionRepository()
      ..listError = StateError('offline');

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: directSessions,
          overviewRepository: _FakeOverviewRepository(
            AcademicOverviewSnapshot(
              courses: [course],
              sessionsByCourse: {
                'course-1': [savedSession],
              },
              isLocalCopy: true,
            ),
          ),
          overviewReadsEnabled: true,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('offline-copy-banner')), findsOneWidget);
    expect(find.text('Modo offline'), findsOneWidget);
    expect(
      find.text('Exibindo a última cópia salva neste aparelho.'),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('past-attendance-pending-alert')));
    await tester.pumpAndSettle();
    expect(find.text('Frequência • POO'), findsOneWidget);
    expect(directSessions.listedCourseIds, isEmpty);
  });

  testWidgets(
    'shows the saved overview before a slow authoritative refresh finishes',
    (tester) async {
      final cachedCourse = CourseRecord(
        id: 'course-1',
        code: 'DCC203',
        name: 'POO salva',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final refreshedCourse = CourseRecord(
        id: 'course-1',
        code: 'DCC203',
        name: 'POO atualizada',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final refresh = Completer<AcademicOverviewSnapshot>();
      final logger = _RecordingAppLogger();
      final overview = _LocalFirstOverviewRepository(
        cached: AcademicOverviewSnapshot(
          courses: [cachedCourse],
          sessionsByCourse: const {'course-1': []},
          isLocalCopy: true,
        ),
        refreshed: refresh.future,
      );

      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) =>
              CourseVisualHost(child: AcademicSyncHost(child: child!)),
          home: CoursePage(
            repository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            overviewRepository: overview,
            overviewReadsEnabled: true,
            user: user,
            logger: logger,
            onSignOut: () async {},
            now: () => now,
          ),
        ),
      );
      await tester.pump();

      expect(find.text('POO salva'), findsOneWidget);
      expect(find.byKey(const Key('offline-copy-banner')), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      refresh.complete(
        AcademicOverviewSnapshot(
          courses: [refreshedCourse],
          sessionsByCourse: const {'course-1': []},
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('POO atualizada'), findsOneWidget);
      expect(find.byKey(const Key('offline-copy-banner')), findsNothing);
      expect(overview.cachedCalls, 1);
      expect(overview.loadCalls, 1);
      expect(logger.events, contains('academic_overview_cache_presented'));
    },
  );

  testWidgets('uses the direct repository when overview rollout is disabled', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final courseRepository = _FakeCourseRepository(courses: [course]);
    final overview = _FakeOverviewRepository(
      AcademicOverviewSnapshot(courses: const [], sessionsByCourse: const {}),
    );

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: courseRepository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          overviewRepository: overview,
          overviewReadsEnabled: false,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('DCC203'), findsOneWidget);
    expect(courseRepository.listCalls, 1);
    expect(overview.loadCalls, 0);
  });

  testWidgets(
    'falls back to direct courses when Python overview is unavailable',
    (tester) async {
      final course = CourseRecord(
        id: 'course-1',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        createdAt: now,
        updatedAt: now,
      );
      final courseRepository = _FakeCourseRepository(courses: [course]);
      final sessionRepository = _FakeSessionRepository({
        'course-1': [_session('session-1', DateTime.utc(2026, 9, 28, 12))],
      });
      final logger = _RecordingAppLogger();

      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: courseRepository,
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: sessionRepository,
            overviewRepository: _FailingOverviewRepository(),
            overviewReadsEnabled: true,
            user: user,
            logger: logger,
            onSignOut: () async {},
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('DCC203'), findsOneWidget);
      expect(
        find.text('Não foi possível carregar suas disciplinas.'),
        findsNothing,
      );
      expect(courseRepository.listCalls, 1);
      expect(logger.events, contains('academic_overview_fallback_succeeded'));
      sessionRepository.listedCourseIds.clear();

      await tester.tap(find.byKey(const Key('nav-general-calendar')));
      await tester.pumpAndSettle();

      expect(sessionRepository.listedCourseIds, contains('course-1'));
    },
  );

  testWidgets('alerts about unresolved attendance from an earlier day', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final sessions = _FakeSessionRepository({
      'course-1': [
        _session('past', DateTime.utc(2026, 9, 26, 12)),
        _session('today', now),
        _session(
          'no-call',
          DateTime.utc(2026, 9, 26, 14),
          status: SessionCalendarStatus.noCall,
        ),
      ],
    });
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: sessions,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const Key('past-attendance-pending-alert')),
      findsOneWidget,
    );
    expect(find.text('1 aula anterior está sem frequência'), findsOneWidget);
    expect(find.text('Mais recente: POO • 26/09/2026'), findsOneWidget);
    await tester.tap(find.byKey(const Key('past-attendance-pending-alert')));
    await tester.pumpAndSettle();
    expect(find.text('Frequência • POO'), findsOneWidget);
    expect(find.text('Pendências anteriores'), findsOneWidget);
    expect(find.text('Selecionada pelo alerta'), findsOneWidget);
    sessions.sessions['course-1'] = const [];
    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('past-attendance-pending-alert')),
      findsNothing,
    );
  });

  testWidgets('shows plural pending alert and tolerates pending-load failure', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final sessions = _FakeSessionRepository({
      'course-1': [
        _session('past-1', DateTime.utc(2026, 9, 25, 12)),
        _session('past-2', DateTime.utc(2026, 9, 26, 12)),
      ],
    });
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: sessions,
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.text('2 aulas anteriores estão sem frequência'),
      findsOneWidget,
    );

    final logger = _RecordingAppLogger();
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(courses: [course]),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository()
            ..listError = StateError('offline'),
          key: UniqueKey(),
          user: user,
          logger: logger,
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(logger.errorContexts, ['past_attendance_pending_load']);
  });

  testWidgets('rejects changing a course to another existing code', (
    tester,
  ) async {
    final first = CourseRecord(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final second = CourseRecord(
      id: 'course-2',
      code: 'DCC204',
      name: 'Algoritmos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [first, second]);
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC204', 'Editar');
    await tester.enterText(find.byKey(const Key('course-code')), 'dcc203');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses, [first, second]);
    expect(
      find.text('Já existe uma disciplina com o código DCC203.'),
      findsOneWidget,
    );
    expect(logger.events, contains('course_update_duplicate_code'));
  });

  testWidgets('validates fields and keeps the form open', (tester) async {
    final repository = _FakeCourseRepository();
    final logger = _RecordingAppLogger();

    await tester.pumpWidget(_app(repository, user, now, logger: logger));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.text('Informe o código.'), findsOneWidget);
    expect(find.text('Informe o nome.'), findsOneWidget);
    expect(repository.courses, isEmpty);
    expect(logger.events, contains('course_create_validation_failed'));

    await tester.enterText(find.byKey(const Key('course-code')), 'x' * 33);
    await tester.enterText(find.byKey(const Key('course-name')), 'x' * 161);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Use no máximo 32 caracteres.'), findsOneWidget);
    expect(find.text('Use no máximo 160 caracteres.'), findsOneWidget);

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('course-code')), findsNothing);
  });

  testWidgets('reports save and delete failures without losing data', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'poo',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final otherCourse = CourseRecord(
      id: 'algorithms',
      code: 'DCC204',
      name: 'Algoritmos',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeCourseRepository(courses: [course, otherCourse])
      ..saveError = FirebaseException(
        plugin: 'cloud_firestore',
        code: 'permission-denied',
      )
      ..deleteError = StateError('offline');

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC203', 'Editar');
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Código: permission-denied'), findsOneWidget);

    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    await _selectCourseAction(tester, 'DCC203', 'Excluir');
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível excluir a disciplina.'), findsOneWidget);
    expect(repository.courses, [course, otherCourse]);
  });

  testWidgets('exposes account details and logout action', (tester) async {
    final repository = _FakeCourseRepository();
    var logoutCalls = 0;

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async => logoutCalls++,
          now: () => now,
          idGenerator: () => 'course-1',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Olá, Eduardo'), findsOneWidget);
    await tester.tap(find.byKey(const Key('profile-menu')));
    await tester.pumpAndSettle();
    expect(find.text('eduardo@ufmg.br'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile-menu')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Sair da conta'));
    await tester.tap(find.text('Sair da conta'));
    await tester.pumpAndSettle();
    expect(logoutCalls, 1);
  });

  testWidgets('fits a phone viewport and generates an identifier by default', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();
    await tester.binding.setSurfaceSize(const Size(320, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Adicionar'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'DCC204');
    await tester.enterText(find.byKey(const Key('course-name')), 'Algoritmos');
    expect(find.byKey(const Key('course-workload')), findsNothing);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(repository.courses.single.id, isNotEmpty);
    expect(repository.courses.single.createdAt.isUtc, isTrue);
    expect(tester.takeException(), isNull);
  });

  testWidgets('saving reaches Firestore when analytics delivery stalls', (
    tester,
  ) async {
    final store = _RecordingDocumentStore();
    final logger = _SelectivelyBlockingLogger('firestore_course_save_started');
    final repository = FirestoreCourseRepository(
      userId: user.id,
      store: store,
      logger: logger,
    );

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-course')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
    await tester.enterText(find.byKey(const Key('course-name')), 'POO');
    expect(find.byKey(const Key('course-workload')), findsNothing);
    await tester.tap(find.text('Salvar'));
    await tester.pump();
    final reachedFirestoreBeforeAnalytics = store.savedPaths.isNotEmpty;
    logger.release();
    await tester.pumpAndSettle();

    expect(reachedFirestoreBeforeAnalytics, isTrue);
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('stops saving when course creation throws unexpectedly', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
          idGenerator: () => throw StateError('identifier unavailable'),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.text('Não foi possível salvar a disciplina.'), findsOneWidget);
    expect(find.widgetWithText(FilledButton, 'Salvar'), findsOneWidget);
  });

  testWidgets('closes the editor after saving without waiting for a reload', (
    tester,
  ) async {
    final repository = _ReloadBlockingCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(repository.savedCourse?.code, 'DCC203');
    expect(find.byKey(const Key('course-code')), findsNothing);
    expect(find.text('DCC203'), findsOneWidget);
  });

  testWidgets('shows a new course while its remote save is still pending', (
    tester,
  ) async {
    final repository = _BlockingSaveCourseRepository();

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byKey(const Key('course-code')), findsNothing);
    expect(find.text('DCC203'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    repository.complete();
    await tester.pumpAndSettle();
    expect(find.byType(CircularProgressIndicator), findsNothing);
  });

  testWidgets('removes an optimistic course when its remote save fails', (
    tester,
  ) async {
    final repository = _FakeCourseRepository()
      ..saveError = FirebaseException(
        plugin: 'cloud_firestore',
        code: 'permission-denied',
      );

    await tester.pumpWidget(_app(repository, user, now));
    await tester.pumpAndSettle();
    await _fillNewCourse(tester);
    await tester.tap(find.text('Salvar'));
    await tester.pumpAndSettle();

    expect(find.text('DCC203'), findsNothing);
    expect(find.textContaining('Código: permission-denied'), findsOneWidget);
  });

  testWidgets('opens the academic UFMG account from the profile menu', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          ufmgSessionGateway: _UFMGGateway(),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile-menu')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('settings-academic-account')), findsOneWidget);
    await tester.tap(find.byKey(const Key('settings-academic-account')));
    await tester.pumpAndSettle();

    expect(find.text('Conta acadêmica UFMG'), findsOneWidget);
    expect(find.byKey(const Key('ufmg-username')), findsOneWidget);
    Navigator.of(tester.element(find.byKey(const Key('ufmg-username')))).pop();
    await tester.pumpAndSettle();
    expect(repository.listCalls, 2);
  });

  for (final persistent in [false, true]) {
    testWidgets(
      'returns synchronized academic sources to their app sections persistent=$persistent',
      (tester) async {
        final Widget Function({Widget? home, TransitionBuilder? builder})
        shell = persistent ? _NavigationApp.new : MaterialApp.new;
        final gateway = _UFMGGateway(
          status: const PythonUFMGSessionStatus(
            connected: true,
            reauthenticationRequired: false,
          ),
        );
        await tester.pumpWidget(
          shell(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              repository: _FakeCourseRepository(),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: _FakeSessionRepository(),
              user: user,
              logger: _RecordingAppLogger(),
              onSignOut: () async {},
              ufmgSessionGateway: gateway,
              now: () => now,
            ),
          ),
        );
        await tester.pumpAndSettle();

        Future<void> openAccount() async {
          await tester.tap(find.byKey(const Key('profile-menu')));
          await tester.pumpAndSettle();
          await tester.tap(find.byKey(const Key('settings-academic-account')));
          await tester.pumpAndSettle();
        }

        await openAccount();
        await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const Key('ufmg-open-courses')));
        await tester.tap(find.byKey(const Key('ufmg-open-courses')));
        await tester.pumpAndSettle();
        expect(find.byKey(const Key('profile-menu')), findsOneWidget);
        expect(find.text('Conta acadêmica UFMG'), findsNothing);

        await openAccount();
        await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byKey(const Key('ufmg-open-calendar')));
        await tester.tap(find.byKey(const Key('ufmg-open-calendar')));
        await tester.pumpAndSettle();
        expect(find.text('Agenda'), findsOneWidget);
      },
    );
  }
  testWidgets('uses a navigation rail when the available width is large', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1200, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.byKey(const Key('nav-home')), findsOneWidget);
    expect(find.byKey(const Key('nav-general-calendar')), findsOneWidget);
    expect(find.byKey(const Key('nav-absence-dashboard')), findsOneWidget);
  });

  testWidgets('keeps the primary shell usable across supported breakpoints', (
    tester,
  ) async {
    final course = CourseRecord(
      id: 'responsive-course',
      code: 'DCC203',
      name: 'Programação Orientada a Objetos com nome extenso',
      workload: 60,
      term: '2026-2',
      createdAt: now,
      updatedAt: now,
    );
    for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
      await tester.binding.setSurfaceSize(Size(width, 900));
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(2)),
            child: child!,
          ),
          home: CoursePage(
            repository: _FakeCourseRepository(courses: [course]),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            user: user,
            logger: _RecordingAppLogger(),
            onSignOut: () async {},
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('nav-home')), findsOneWidget);
      expect(find.byKey(const Key('nav-general-calendar')), findsOneWidget);
      expect(find.byKey(const Key('nav-absence-dashboard')), findsOneWidget);
      expect(
        find.byType(width >= 840 ? NavigationRail : NavigationBar),
        findsOneWidget,
      );
      await tester.drag(find.byType(ListView).first, const Offset(0, -600));
      await tester.pumpAndSettle();
      final courseCard = find.byKey(const Key('course-card-responsive-course'));
      expect(tester.getCenter(courseCard).dy, lessThan(900));
      await tester.tap(courseCard);
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('course-hub-materials')));
      expect(find.byKey(const Key('course-hub-frequency')), findsOneWidget);
      expect(find.byKey(const Key('course-hub-agenda')), findsOneWidget);
      expect(find.byKey(const Key('course-hub-open-schedule')), findsOneWidget);
      expect(find.byKey(const Key('course-hub-materials')), findsOneWidget);
      expect(tester.takeException(), isNull, reason: 'width $width');
      await tester.pageBack();
      await tester.pumpAndSettle();
    }
  });

  testWidgets('activates the primary course action from the keyboard', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_FakeCourseRepository(), user, now));
    await tester.pumpAndSettle();

    final addCourse = find.byKey(const Key('add-course'));
    final addElement = tester.element(addCourse);
    var reachedAction = false;
    for (var index = 0; index < 12 && !reachedAction; index++) {
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pump();
      final focused = FocusManager.instance.primaryFocus?.context;
      if (identical(focused, addElement)) reachedAction = true;
      focused?.visitAncestorElements((ancestor) {
        if (identical(ancestor, addElement)) {
          reachedAction = true;
          return false;
        }
        return true;
      });
    }
    expect(reachedAction, isTrue);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();

    expect(find.text('Nova disciplina'), findsOneWidget);
    expect(find.byKey(const Key('course-code')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('runs a due UFMG synchronization after the dashboard loads', (
    tester,
  ) async {
    final repository = _FakeCourseRepository();
    final gateway = _UFMGGateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
      createdCourses: 1,
    );
    final syncSchedule = _FakeUFMGSyncSchedule(due: true);
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: repository,
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          ufmgSessionGateway: gateway,
          ufmgSyncSchedule: syncSchedule,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(gateway.statusCalls, 1);
    expect(gateway.syncCalls, 1);
    expect(syncSchedule.recordedUsers, ['user-1']);
    expect(repository.listCalls, 2);
  });

  testWidgets('does not contact UFMG before the next scheduled check', (
    tester,
  ) async {
    final gateway = _UFMGGateway();
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          ufmgSessionGateway: gateway,
          ufmgSyncSchedule: _FakeUFMGSyncSchedule(due: false),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(gateway.statusCalls, 0);
    expect(gateway.syncCalls, 0);
  });

  testWidgets('warns when an automatic synchronization needs reconnection', (
    tester,
  ) async {
    final gateway = _UFMGGateway(
      status: const PythonUFMGSessionStatus(
        connected: false,
        reauthenticationRequired: true,
      ),
    );
    await tester.pumpWidget(
      _NavigationApp(
        builder: (context, child) => AcademicSyncHost(child: child!),
        home: CoursePage(
          repository: _FakeCourseRepository(),
          meetingRepository: _FakeMeetingRepository(),
          sessionRepository: _FakeSessionRepository(),
          user: user,
          logger: _RecordingAppLogger(),
          onSignOut: () async {},
          ufmgSessionGateway: gateway,
          ufmgSyncSchedule: _FakeUFMGSyncSchedule(due: true),
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Reconecte à UFMG para atualizar'),
      findsOneWidget,
    );
    expect(gateway.syncCalls, 0);
  });

  testWidgets('keeps local data available when automatic sync fails', (
    tester,
  ) async {
    final failures = <(Object, String)>[
      (
        const PythonBackendException(
          PythonBackendError.ufmgReauthenticationRequired,
        ),
        'Reconecte à UFMG para atualizar',
      ),
      (
        StateError('temporary outage'),
        'Não foi possível sincronizar com a UFMG agora',
      ),
    ];

    for (final failure in failures) {
      final gateway = _UFMGGateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
        syncError: failure.$1,
      );
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            repository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            user: user,
            logger: _RecordingAppLogger(),
            onSignOut: () async {},
            ufmgSessionGateway: gateway,
            ufmgSyncSchedule: _FakeUFMGSyncSchedule(due: true),
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.textContaining(failure.$2), findsOneWidget);
      expect(
        find.text('Não foi possível carregar suas disciplinas.'),
        findsNothing,
      );
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets(
    'guided alarm permission invokes the existing native bridge then rechecks',
    (tester) async {
      final permissions = experience.ExperiencePermissions();
      permissions.flags['exact_alarms'] = false;
      final calls = <String>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(FirstCheckpointGateway.channel, (
            call,
          ) async {
            calls.add(call.method);
            if (call.method == 'request_alarm_permission') {
              permissions.flags['exact_alarms'] = true;
            }
            return [];
          });
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            user: user,
            logger: _RecordingAppLogger(),
            onSignOut: () async {},
            repository: _FakeCourseRepository(),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            attendancePermissions: permissions,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('nav-settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Presença nas aulas'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continuar'));
      await tester.pumpAndSettle();
      expect(calls, contains('request_alarm_permission'));
      expect(find.text('Tudo pronto'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
  for (final failure in [false, true]) {
    testWidgets(
      'result notification opens the owned lesson and reports navigation stage failure=$failure',
      (tester) async {
        final h = experience.ExperienceHarness();
        addTearDown(h.dispose);
        final course = experience.experienceCourse;
        final session = experience.experienceSession();
        h.reports = [
          experience.experienceReceipt(session),
          {
            ...experience.experienceReceipt(session),
            'moment': 'second',
            'delivery_updated_at_ms':
                experience.experienceNow.millisecondsSinceEpoch,
          },
        ];
        final events = StreamController<Map<String, Object?>>.broadcast();
        addTearDown(events.close);
        final repo = _FakeSessionRepository({
          course.id: [session],
        });
        final log = _RecordingAppLogger();
        await tester.pumpWidget(
          _NavigationApp(
            builder: (context, child) => AcademicSyncHost(child: child!),
            home: CoursePage(
              user: const AuthUser(id: 'owner', email: 'x@ufmg.br'),
              logger: log,
              onSignOut: () async {},
              repository: _FakeCourseRepository(courses: [course]),
              meetingRepository: _FakeMeetingRepository(),
              sessionRepository: repo,
              attendanceExperience: h.controller,
              checkpointDeliveryUpdates: events.stream,
              now: () => experience.experienceNow,
            ),
          ),
        );
        await tester.pumpAndSettle();
        if (failure) repo.listError = StateError('sessions unavailable');
        events.add({
          'action': 'open_checkpoints',
          'account_id': 'owner',
          'open_revision': 1,
        });
        await tester.pumpAndSettle();
        if (failure) {
          expect(
            log.errorContexts,
            contains('checkpoint_notification_navigation'),
          );
          expect(find.text('Selecionada pelo alerta'), findsNothing);
        } else {
          expect(find.text('Selecionada pelo alerta'), findsOneWidget);
          expect(find.textContaining('Início: no campus'), findsOneWidget);
          expect(log.events, contains('checkpoint_result_opened'));
          await tester.pageBack();
          await tester.pumpAndSettle();
        }
        await tester.pumpWidget(const SizedBox());
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'permission completion and campus edits reconcile existing automation without technical screens',
    (tester) async {
      final h = experience.ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags['foreground_location'] = false;
      final scheduler = Harness();
      final course = experience.experienceCourse;
      await tester.pumpWidget(
        _NavigationApp(
          builder: (context, child) => AcademicSyncHost(child: child!),
          home: CoursePage(
            user: const AuthUser(id: 'owner', email: 'x@ufmg.br'),
            logger: h.logger,
            onSignOut: () async {},
            repository: _FakeCourseRepository(courses: [course]),
            meetingRepository: _FakeMeetingRepository(),
            sessionRepository: _FakeSessionRepository(),
            overviewReadsEnabled: true,
            overviewRepository: _FakeOverviewRepository(
              AcademicOverviewSnapshot(
                courses: [course],
                sessionsByCourse: {course.id: []},
              ),
            ),
            automaticCheckpointScheduler: scheduler.scheduler,
            attendanceExperience: h.controller,
            now: () => experience.experienceNow,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const Key('attendance-setup-reminder')),
        findsOneWidget,
      );
      await tester.tap(find.text('Concluir'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continuar'));
      await tester.pumpAndSettle();
      expect(find.text('Tudo pronto'), findsOneWidget);
      await tester.tap(find.text('Concluir'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('attendance-setup-reminder')), findsNothing);
      await tester.tap(find.byKey(const Key('nav-settings')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('Local das aulas'));
      await tester.tap(find.text('Local das aulas'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Campus Pampulha'));
      await tester.pumpAndSettle();
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
}

Future<void> _selectCourseAction(
  WidgetTester tester,
  String courseCode,
  String action,
) async {
  await tester.tap(find.byKey(ValueKey('course-actions-$courseCode')));
  await tester.pumpAndSettle();
  await tester.tap(find.text(action));
  await tester.pumpAndSettle();
}

Future<void> _fillNewCourse(
  WidgetTester tester, {
  String code = 'DCC203',
  String name = 'POO',
}) async {
  await tester.tap(find.byKey(const Key('add-course')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('course-code')), code);
  await tester.enterText(find.byKey(const Key('course-name')), name);
  expect(find.byKey(const Key('course-workload')), findsNothing);
}

Widget _app(
  CourseRepository repository,
  AuthUser user,
  DateTime now, {
  AppLogger? logger,
}) => _NavigationApp(
  builder: (context, child) => AcademicSyncHost(child: child!),
  home: CoursePage(
    repository: repository,
    meetingRepository: _FakeMeetingRepository(),
    sessionRepository: _FakeSessionRepository(),
    user: user,
    logger: logger ?? _RecordingAppLogger(),
    onSignOut: () async {},
    now: () => now,
    idGenerator: () => 'course-1',
  ),
);

final class _FakeCourseRepository implements CourseRepository {
  _FakeCourseRepository({List<CourseRecord>? courses})
    : courses = courses ?? [];

  final List<CourseRecord> courses;
  final deletedIds = <String>[];
  Object? listError;
  Object? saveError;
  Object? deleteError;
  int listCalls = 0;
  Completer<List<CourseRecord>>? pending;

  @override
  Future<void> deleteCourse(String courseId) async {
    if (deleteError case final error?) throw error;
    deletedIds.add(courseId);
    courses.removeWhere((course) => course.id == courseId);
  }

  @override
  Future<List<CourseRecord>> listCourses() async {
    listCalls++;
    if (listError case final error?) throw error;
    return pending == null ? List.of(courses) : await pending!.future;
  }

  @override
  Future<void> saveCourse(CourseRecord course) async {
    if (saveError case final error?) throw error;
    courses.removeWhere((item) => item.id == course.id);
    courses.add(course);
  }
}

final class _FakeMeetingRepository implements MeetingRepository {
  _FakeMeetingRepository({this.meetings = const {}});

  final Map<String, List<MeetingRecord>> meetings;
  final listedCourseIds = <String>[];
  Object? listError;

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {}

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async {
    listedCourseIds.add(courseId);
    if (listError case final error?) throw error;
    return List.of(meetings[courseId] ?? const []);
  }

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {}
}

final class _FakeSessionRepository implements SessionRepository {
  Future<List<SessionRecord>>? pending;
  _FakeSessionRepository([this.sessions = const {}]);

  final Map<String, List<SessionRecord>> sessions;
  final listedCourseIds = <String>[];
  Object? listError;

  @override
  Future<void> deleteSession(String courseId, String sessionId) async {}

  @override
  Future<List<SessionRecord>> listSessions(String courseId) async {
    listedCourseIds.add(courseId);
    if (pending != null) return pending!;
    if (listError case final error?) throw error;
    return List.of(sessions[courseId] ?? const []);
  }

  @override
  Future<void> saveSession(String courseId, SessionRecord session) async {}
}

final class _FakeOverviewRepository implements AcademicOverviewRepository {
  _FakeOverviewRepository(this.snapshot);

  final AcademicOverviewSnapshot snapshot;
  Object? error;
  int loadCalls = 0;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() async {
    loadCalls++;
    if (error != null) throw error!;
    return snapshot;
  }
}

final class _LocalFirstOverviewRepository
    implements LocalFirstAcademicOverviewRepository {
  _LocalFirstOverviewRepository({
    required this.cached,
    required this.refreshed,
  });

  final AcademicOverviewSnapshot? cached;
  final Future<AcademicOverviewSnapshot> refreshed;
  int cachedCalls = 0;
  int loadCalls = 0;

  @override
  Future<AcademicOverviewSnapshot?> loadCachedOverview() async {
    cachedCalls++;
    return cached;
  }

  @override
  Future<AcademicOverviewSnapshot> loadOverview() {
    loadCalls++;
    return refreshed;
  }
}

final class _FailingOverviewRepository implements AcademicOverviewRepository {
  @override
  Future<AcademicOverviewSnapshot> loadOverview() =>
      Future.error(StateError('backend unavailable'));
}

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

final class _RecordingDocumentStore implements DocumentStore {
  final savedPaths = <String>[];
  final documents = <StoredDocument>[];

  @override
  Future<void> deleteAll(Iterable<String> documentPaths) async {}

  @override
  Future<List<StoredDocument>> list(String collectionPath) async =>
      List.of(documents);

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) async {
    savedPaths.add(documentPath);
    documents
      ..clear()
      ..add(StoredDocument(id: documentPath.split('/').last, data: data));
  }

  @override
  Future<void> update(String documentPath, Map<String, Object?> data) async {}
}

final class _ReloadBlockingCourseRepository implements CourseRepository {
  CourseRecord? savedCourse;
  var _listCalls = 0;

  @override
  Future<void> deleteCourse(String courseId) async {}

  @override
  Future<List<CourseRecord>> listCourses() {
    _listCalls++;
    if (_listCalls == 1) return Future.value([]);
    return Completer<List<CourseRecord>>().future;
  }

  @override
  Future<void> saveCourse(CourseRecord course) async {
    savedCourse = course;
  }
}

final class _BlockingSaveCourseRepository implements CourseRepository {
  final _save = Completer<void>();

  void complete() => _save.complete();

  @override
  Future<void> deleteCourse(String courseId) async {}

  @override
  Future<List<CourseRecord>> listCourses() async => [];

  @override
  Future<void> saveCourse(CourseRecord course) => _save.future;
}

final class _SelectivelyBlockingLogger implements AppLogger {
  _SelectivelyBlockingLogger(this.blockedEvent);

  final String blockedEvent;
  final Completer<void> _delivery = Completer<void>();

  void release() => _delivery.complete();

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (name == blockedEvent) await _delivery.future;
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

final class _RecordingAppLogger implements AppLogger {
  bool failRecording = false;
  bool failDeliveryLog = false;
  final events = <String>[];
  final eventFields = <String, Map<String, Object>>{};
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (failDeliveryLog && name == 'checkpoint_delivery_ui_refresh') {
      throw StateError('logger offline');
    }
    events.add(name);
    eventFields[name] = parameters ?? {};
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
    if (failRecording) throw StateError('logger unavailable');
  }
}

class _UFMGGateway implements BackendUFMGSessionGateway {
  Future<PythonMoodleContentDiscovery>? pendingCatalog;
  _UFMGGateway({
    this.status = const PythonUFMGSessionStatus(
      connected: false,
      reauthenticationRequired: false,
    ),
    this.createdCourses = 0,
    this.syncError,
    this.materialCatalog = const PythonMoodleContentDiscovery(
      courses: [],
      candidateTotal: 0,
      metaturmaCandidateTotal: 0,
    ),
  });

  final PythonUFMGSessionStatus status;
  final int createdCourses;
  final Object? syncError;
  final PythonMoodleContentDiscovery materialCatalog;
  Object? catalogError;
  int statusCalls = 0;
  int syncCalls = 0;

  @override
  Future<PythonMoodleContentDiscovery> discoverMoodleContent() =>
      Future.value(materialCatalog);

  @override
  Future<PythonMoodleContentDiscovery> listMoodleMaterialCatalog() async {
    if (pendingCatalog != null) return pendingCatalog!;
    if (catalogError != null) throw catalogError!;
    return materialCatalog;
  }

  @override
  Future<PythonMoodleMobileCapabilities> probeMoodleMobileCapabilities() =>
      throw UnimplementedError();

  @override
  Future<PythonMoodleSyncResult> syncMoodle() async => PythonMoodleSyncResult(
    dates: await importMoodleDates(),
    candidateTotal: materialCatalog.candidateTotal,
    capabilities: null,
  );

  @override
  Future<List<PythonMoodleMaterialFile>> listMoodleMaterialFiles({
    required String term,
    required String courseId,
    required String sourceId,
  }) => throw UnimplementedError();

  @override
  Future<PythonUFMGSigaSyncResult> syncSiga() async {
    syncCalls++;
    if (syncError case final error?) throw error;
    return PythonUFMGSigaSyncResult(
      courses: PythonUFMGCourseImportResult(
        created: createdCourses,
        existing: 0,
        total: createdCourses,
      ),
      schedules: PythonUFMGScheduleImportResult(
        total: 0,
        updated: 0,
        unchanged: 0,
        conflicts: 0,
        missingCourses: 0,
        meetingsImported: 0,
      ),
      checkedAt: DateTime.utc(2026, 10, 13),
      nextAutomaticSyncAt: DateTime.utc(2026, 10, 20),
    );
  }

  @override
  Future<PythonUFMGScheduleImportResult> importUFMGSchedules() =>
      throw UnimplementedError();

  @override
  Future<PythonMoodleDateImportResult> importMoodleDates() async =>
      const PythonMoodleDateImportResult(
        total: 0,
        matched: 0,
        unmatched: 0,
        created: 0,
        updated: 0,
        unchanged: 0,
      );

  @override
  Future<List<PythonMoodleDate>> listMoodleDates() async => const [];

  @override
  Future<PythonUFMGCourseImportResult> importUFMGCourses() async =>
      const PythonUFMGCourseImportResult(created: 0, existing: 0, total: 0);

  @override
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus() async {
    statusCalls++;
    return status;
  }

  @override
  Future<PythonUFMGSessionStatus> connectUFMG({
    required String username,
    required String password,
  }) => throw UnimplementedError();

  @override
  Future<PythonUFMGSessionStatus> disconnectUFMG() =>
      throw UnimplementedError();
}

final class _ProgressUFMGGateway extends _UFMGGateway
    implements BackendAcademicSyncProgressGateway {
  _ProgressUFMGGateway({
    bool connected = true,
    bool reauthenticationRequired = false,
  }) : super(
         status: PythonUFMGSessionStatus(
           connected: connected,
           reauthenticationRequired: reauthenticationRequired,
         ),
       );
  final progress = ProgressGateway();
  bool failDates = false;
  @override
  Future<List<PythonMoodleDate>> listMoodleDates() {
    if (failDates) return Future.error(StateError('dates unavailable'));
    return super.listMoodleDates();
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncWithProgress(
    String operationId, {
    bool force = false,
  }) => progress.syncWithProgress(operationId, force: force);
  @override
  Future<PythonUnifiedAcademicSyncResult> syncAllAcademicData() =>
      progress.syncAllAcademicData();
  @override
  Stream<AcademicSyncProgress> watchSyncProgress(String operationId) =>
      progress.watchSyncProgress(operationId);
}

final class _PermissionGateway implements AttendancePermissionsGateway {
  @override
  Future<AttendancePermissionStatus> read() async =>
      AttendancePermissionStatus.fromMap(readyPermissionSnapshot);
  @override
  Future<void> perform(AttendancePermissionAction action) async {}
}

final class _FakeUFMGSyncSchedule implements UFMGSyncScheduleGateway {
  _FakeUFMGSyncSchedule({
    required this.due,
    this.failRecording = false,
    this.failReading = false,
  });
  final bool failRecording, failReading;
  final deadlines = <DateTime>[];

  final bool due;
  final recordedUsers = <String>[];

  @override
  Future<bool> isDue(String userId) async {
    if (failReading) throw StateError("schedule unavailable");
    return due;
  }

  @override
  Future<void> record(String userId, DateTime nextAutomaticSyncAt) async {
    if (failRecording) throw StateError("local cache unavailable");
    recordedUsers.add(userId);
    deadlines.add(nextAutomaticSyncAt);
  }
}

class _HubLogStore implements OperationalLogStore {
  final documents = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async =>
      documents.add(document);
}

class _WorkspaceGateway extends _UFMGGateway
    implements BackendAcademicWorkspaceGateway {
  @override
  Future<PythonCourseActivitySnapshot> loadCourseActivitySnapshot(
    String id,
  ) async {
    requested = id;
    return PythonCourseActivitySnapshot.fromJson({
      'course_id': id,
      'term': '2026-2',
      'synced_at': '2026-10-28T12:00:00Z',
      'activities': [],
    });
  }

  String? requested;
  @override
  Future<List<PythonMoodleActivity>> listCourseActivities(String id) async {
    requested = id;
    return [];
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError();
}

final class _RecoveredUFMGGateway extends _ProgressUFMGGateway
    implements BackendResumableAcademicSyncGateway {
  @override
  Future<String?> pendingAcademicSyncId() async => 'old-saved-operation';
}

class _NavigationApp extends StatelessWidget {
  const _NavigationApp({this.home, this.builder, super.key});
  final Widget? home;
  final TransitionBuilder? builder;
  @override
  Widget build(BuildContext context) => ProductNavigation(
    builder: (n) => MaterialApp(
      navigatorObservers: [n.observer],
      builder: (context, child) =>
          n.frame(context, builder?.call(context, child) ?? child!),
      home: home,
    ),
  );
}
