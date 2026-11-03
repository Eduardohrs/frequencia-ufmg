import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/design/course_visuals.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/general_calendar_page.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

final now = DateTime.utc(2026, 9, 15, 12);
final course = CourseRecord(
  id: 'poo',
  code: 'DCC203',
  name: 'POO',
  workload: 60,
  term: '2026-2',
  createdAt: now,
  updatedAt: now,
);
SessionRecord entry(String id, int day) => SessionRecord(
  id: id,
  startsAt: DateTime.utc(2026, 9, day, 13),
  endsAt: DateTime.utc(2026, 9, day, 15),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  assessmentTitle: id,
  createdAt: now,
  updatedAt: now,
);
void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  testWidgets(
    'empty day describes the active filter without denying saved lessons',
    (tester) async {
      final lesson = SessionRecord(
        id: 'lesson',
        startsAt: now,
        endsAt: now.add(const Duration(hours: 2)),
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.one,
        createdAt: now,
        updatedAt: now,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: GeneralCalendarPage(
            courses: [course],
            repository: _Sessions([lesson]),
            location: location,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('POO'), findsOneWidget);
      expect(find.textContaining('Sem aulas ou prazos'), findsWidgets);
      for (final label in ['Avaliações', 'Entregas e prazos', 'Aulas']) {
        final current = find.byKey(const Key('calendar-type-filter'));
        await tester.tap(current);
        await tester.pumpAndSettle();
        await tester.tap(find.text(label).last);
        await tester.pumpAndSettle();
        expect(find.textContaining('Sem aulas ou prazos'), findsNothing);
        expect(
          find.textContaining('Nenhum item para este filtro'),
          findsWidgets,
        );
        expect(
          find.text('POO'),
          label == 'Aulas' ? findsOneWidget : findsNothing,
        );
      }
      await tester.tap(find.byKey(const Key('calendar-type-filter')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Todos').last);
      await tester.pumpAndSettle();
      expect(find.text('POO'), findsOneWidget);
      expect(find.textContaining('Sem aulas ou prazos'), findsWidgets);
      expect(tester.takeException(), isNull);
    },
  );
  for (final width in [320.0, 390.0, 1200.0]) {
    testWidgets(
      'default short interval is readable and list preserves it at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final state = CalendarNavigationState();
        await tester.pumpWidget(
          MaterialApp(
            home: GeneralCalendarPage(
              courses: [course],
              repository: _Sessions([
                entry('Antiga', 1),
                entry('Nesta semana', 16),
                entry('Na próxima', 23),
              ]),
              location: location,
              now: () => now,
              navigationState: state,
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          state.range,
          width < 900 ? CalendarRange.week : CalendarRange.fortnight,
        );
        final previous = tester.getCenter(find.byTooltip('Período anterior'));
        final next = tester.getCenter(find.byTooltip('Próximo período'));
        expect(next.dy, previous.dy);
        expect(find.byKey(const Key('month-calendar-grid')), findsNothing);
        expect(find.textContaining('Avaliação: Nesta semana'), findsOneWidget);
        expect(find.textContaining('Avaliação: Antiga'), findsNothing);
        expect(
          find.textContaining('Avaliação: Na próxima'),
          width < 900 ? findsNothing : findsOneWidget,
        );
        await tester.tap(find.text('Lista'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Avaliação: Antiga'), findsNothing);
        await tester.tap(find.byTooltip('Próximo período'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Avaliação: Nesta semana'), findsNothing);
        await tester.tap(find.text('Hoje'));
        await tester.pumpAndSettle();
        expect(find.textContaining('Avaliação: Nesta semana'), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'month remains optional and return retains month, list and course filters',
    (tester) async {
      final state = CalendarNavigationState();
      final repo = _Sessions([entry('Antiga', 1), entry('Nesta semana', 16)]);
      Widget app() => MaterialApp(
        home: GeneralCalendarPage(
          courses: [course],
          repository: repo,
          location: location,
          now: () => now,
          navigationState: state,
          initialCourseId: 'poo',
        ),
      );
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      await chooseRange(tester, 'week', 'Mês');
      expect(find.byKey(const Key('month-calendar-grid')), findsOneWidget);
      await tester.tap(find.text('Lista'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Avaliação: Antiga'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpWidget(app());
      await tester.pumpAndSettle();
      expect(state.range, CalendarRange.month);
      expect(state.display, CalendarDisplay.list);
      expect(state.courseId, 'poo');
      expect(find.textContaining('Avaliação: Antiga'), findsOneWidget);
      await tester.tap(find.byTooltip('Período anterior'));
      await tester.pumpAndSettle();
      expect(state.month!.month, 8);
      await tester.tap(find.text('Hoje'));
      await tester.pumpAndSettle();
      expect(state.month!.day, 15);
    },
  );
  testWidgets('fortnight is selectable on mobile without tiny day columns', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          courses: [course],
          repository: _Sessions([
            entry('Prazo longo com nome legível de trabalho', 23),
          ]),
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await chooseRange(tester, 'week', '2 semanas');
    await tester.scrollUntilVisible(
      find.textContaining('Avaliação: Prazo longo'),
      250,
      scrollable: find.byType(Scrollable).last,
    );
    expect(find.textContaining('Avaliação: Prazo longo'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('landscape allows scrolling past filters into the full agenda', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(844, 390);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: GeneralCalendarPage(
          courses: [course],
          repository: _Sessions([entry('Nesta semana', 16)]),
          location: location,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView).first, const Offset(0, -300));
    await tester.pumpAndSettle();
    expect(find.textContaining('Avaliação: Nesta semana'), findsWidgets);
    expect(tester.takeException(), isNull);
  });
  for (final fails in [false, true]) {
    testWidgets(
      'view preferences survive page restart and storage failures are observable ($fails)',
      (tester) async {
        final model = CourseVisualCatalog();
        await model.update('owner', [course]);
        final store = _Store();
        final logger = FirestoreAppLogger(
          store: store,
          currentUserId: () => 'owner',
          platform: 'web',
        );
        final prefs = fails ? _BrokenPreferences() : SharedPreferencesAsync();
        Widget app() => CourseVisualHost(
          catalog: model,
          child: MaterialApp(
            home: GeneralCalendarPage(
              courses: [course],
              repository: _Sessions([]),
              location: location,
              now: () => now,
              logger: logger,
              preferences: prefs,
            ),
          ),
        );
        await tester.pumpWidget(app());
        await tester.pumpAndSettle();
        await chooseRange(tester, 'week', 'Mês');
        await tester.tap(find.text('Lista'));
        await tester.pumpAndSettle();
        await tester.pumpWidget(const SizedBox.shrink());
        await tester.pumpWidget(app());
        await tester.pumpAndSettle();
        if (fails) {
          expect(
            find.byKey(const ValueKey('calendar-range-week')),
            findsOneWidget,
          );
          expect(
            store.items.where(
              (e) => e['operation'] == 'calendar_preference_read',
            ),
            isNotEmpty,
          );
          final failed = store.items.firstWhere(
            (e) => e['operation'] == 'calendar_preference_write',
          );
          expect(
            failed['errorDetails'].toString(),
            contains('preference_write'),
          );
          expect(failed['durationMs'], isA<int>());
          expect(failed['correlationId'], isNotEmpty);
        } else {
          expect(
            find.byKey(const ValueKey('calendar-range-month')),
            findsOneWidget,
          );
          expect(await prefs.getString('calendar_view.v1.owner'), 'month/list');
          expect(
            store.items.any(
              (e) => e['event'] == 'calendar_preference_write_succeeded',
            ),
            isTrue,
          );
          expect(
            store.items.last['details'].toString(),
            contains('range_start'),
          );
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'corrupt preference recovers to a short view without blocking courses',
    (tester) async {
      final model = CourseVisualCatalog();
      await model.update('owner', [course]);
      await SharedPreferencesAsync().setString(
        'calendar_view.v1.owner',
        'bogus/mode',
      );
      final store = _Store();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'owner',
        platform: 'web',
      );
      await tester.pumpWidget(
        CourseVisualHost(
          catalog: model,
          child: MaterialApp(
            home: GeneralCalendarPage(
              courses: [course],
              repository: _Sessions([]),
              location: location,
              now: () => now,
              logger: logger,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('calendar-range-week')), findsOneWidget);
      expect(
        store.items.any((e) => e['operation'] == 'calendar_preference_read'),
        isTrue,
      );
    },
  );
  for (final dispose in [false, true]) {
    testWidgets(
      'late preference cannot replace a deliberate choice or a closed page ($dispose)',
      (tester) async {
        final model = CourseVisualCatalog();
        await model.update('owner', [course]);
        final prefs = _PendingPreferences();
        await tester.pumpWidget(
          CourseVisualHost(
            catalog: model,
            child: MaterialApp(
              home: GeneralCalendarPage(
                courses: [course],
                repository: _Sessions([]),
                location: location,
                now: () => now,
                preferences: prefs,
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        if (dispose) {
          await tester.pumpWidget(const SizedBox.shrink());
        } else {
          await chooseRange(tester, 'week', 'Mês');
        }
        prefs.read.complete('fortnight/list');
        await tester.pumpAndSettle();
        if (!dispose) {
          expect(
            find.byKey(const ValueKey('calendar-range-month')),
            findsOneWidget,
          );
        }
        expect(tester.takeException(), isNull);
      },
    );
  }
}

Future<void> chooseRange(
  WidgetTester tester,
  String current,
  String choice,
) async {
  await tester.ensureVisible(find.byKey(ValueKey('calendar-range-$current')));
  await tester.tap(find.byKey(ValueKey('calendar-range-$current')));
  await tester.pumpAndSettle();
  await tester.tap(find.text(choice).last);
  await tester.pumpAndSettle();
}

class _Sessions implements SessionRepository {
  _Sessions(this.items);
  final List<SessionRecord> items;
  @override
  Future<List<SessionRecord>> listSessions(String id) async => items;
  @override
  Future<void> saveSession(String id, SessionRecord item) async {}
  @override
  Future<void> deleteSession(String id, String session) async {}
}

class _Store implements OperationalLogStore {
  final items = <Map<String, Object?>>[];
  @override
  Future<void> add(String id, Map<String, Object?> document) async =>
      items.add(document);
}

class _BrokenPreferences extends SharedPreferencesAsync {
  @override
  Future<String?> getString(String key) async => throw StateError('read');
  @override
  Future<void> setString(String key, String value) async =>
      throw StateError('write');
}

class _PendingPreferences extends SharedPreferencesAsync {
  final read = Completer<String?>();
  @override
  Future<String?> getString(String key) => read.future;
}
