import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/data/campus_location.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/features/navigation/product_navigation.dart';
import 'package:frequencia_ufmg/features/settings/settings_page.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'fixtures/product_experience_fixture.dart';

void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  for (final size in [
    const Size(390, 844),
    const Size(1200, 900),
    const Size(844, 390),
  ]) {
    testWidgets(
      'navigation survives details, return, modal and logout at $size',
      (t) async {
        await t.binding.setSurfaceSize(size);
        addTearDown(() => t.binding.setSurfaceSize(null));
        final h = ExperienceHarness();
        addTearDown(h.dispose);
        late ProductNavigationController n;
        var opens = 0;
        final owner = Object();
        await t.pumpWidget(
          ProductNavigation(
            builder: (nav) {
              n = nav;
              return MaterialApp(
                navigatorObservers: [n.observer],
                builder: (context, child) => n.frame(context, child!),
                home: Builder(
                  builder: (context) {
                    n.bind(owner, (index) async {
                      opens++;
                      await Navigator.of(context).push<void>(
                        MaterialPageRoute(
                          settings: RouteSettings(
                            name: [
                              'root',
                              'agenda',
                              'absences',
                              'settings',
                            ][index],
                          ),
                          builder: (_) => Scaffold(
                            appBar: AppBar(title: Text('Section $index')),
                            body: Column(
                              children: [
                                TextButton(
                                  onPressed: () =>
                                      Navigator.of(context).push<void>(
                                        MaterialPageRoute(
                                          builder: (_) => Scaffold(
                                            appBar: AppBar(
                                              title: const Text('Detail'),
                                            ),
                                          ),
                                        ),
                                      ),
                                  child: const Text('Detail'),
                                ),
                                TextButton(
                                  onPressed: () => showModalBottomSheet<void>(
                                    context: context,
                                    builder: (_) => const SizedBox(
                                      height: 100,
                                      child: Text('Unsaved filter'),
                                    ),
                                  ),
                                  child: const Text('Filter'),
                                ),
                              ],
                            ),
                          ),
                        ),
                      );
                    }, logger: h.logger);
                    return Scaffold(appBar: AppBar(title: const Text('Home')));
                  },
                ),
              );
            },
          ),
        );
        await t.pumpAndSettle();
        expect(n.active, isTrue);
        expect(ProductNavigation.of(t.element(find.text('Home'))), same(n));
        expect(
          find.byType(
            size.width >= 840 && size.height >= 600
                ? NavigationRail
                : NavigationBar,
          ),
          findsOneWidget,
        );
        await n.select(1);
        await t.pumpAndSettle();
        expect(find.text('Section 1'), findsOneWidget);
        expect(n.selected, 1);
        await t.tap(find.text('Detail'));
        await t.pumpAndSettle();
        expect(n.selected, 1);
        expect(find.byKey(const Key('nav-home')), findsOneWidget);
        await t.pageBack();
        await t.pumpAndSettle();
        await t.tap(find.text('Filter'));
        await t.pumpAndSettle();
        expect(n.modal, isTrue);
        await n.select(2);
        await t.pumpAndSettle();
        expect(find.text('Unsaved filter'), findsOneWidget);
        expect(opens, 1);
        Navigator.of(t.element(find.text('Unsaved filter'))).pop();
        await t.pumpAndSettle();
        await n.select(2);
        await t.pumpAndSettle();
        expect(find.text('Section 2'), findsOneWidget);
        expect(find.text('Section 1'), findsNothing);
        await n.select(2);
        await t.pumpAndSettle();
        await t.pageBack();
        await t.pumpAndSettle();
        expect(find.text('Home'), findsOneWidget);
        await n.select(3);
        await t.pumpAndSettle();
        expect(n.selected, 3);
        n.unbind(Object());
        expect(n.active, isTrue);
        n.unbind(owner);
        await t.pumpAndSettle();
        expect(n.active, isFalse);
        expect(find.byType(NavigationBar), findsNothing);
        expect(find.text('Home'), findsOneWidget);
        await n.select(1);
        expect(n.active, isFalse);
        await t.pumpWidget(const SizedBox());
        await t.pumpAndSettle();
        expect(t.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'route replacement and removal keep selection with the current page',
    (t) async {
      final n = ProductNavigationController();
      final key = GlobalKey<NavigatorState>();
      final owner = Object();
      await t.pumpWidget(
        MaterialApp(
          navigatorKey: key,
          navigatorObservers: [n.observer],
          builder: (context, child) => n.frame(context, child!),
          home: const Scaffold(body: Text('root')),
        ),
      );
      n.bind(owner, (_) async {});
      await t.pumpAndSettle();
      Route<void> route(String name) => MaterialPageRoute<void>(
        settings: RouteSettings(name: name),
        builder: (_) => Scaffold(body: Text(name)),
      );
      final agenda = route('agenda'), detail = route('detail');
      unawaited(key.currentState!.push(agenda));
      await t.pumpAndSettle();
      unawaited(key.currentState!.push(detail));
      await t.pumpAndSettle();
      key.currentState!.removeRoute(agenda);
      await t.pumpAndSettle();
      expect(n.selected, 1);
      expect(find.text('detail'), findsOneWidget);
      final replacement = route('replacement');
      key.currentState!.replace(oldRoute: detail, newRoute: replacement);
      await t.pumpAndSettle();
      expect(n.selected, 1);
      key.currentState!.removeRoute(replacement);
      await t.pumpAndSettle();
      expect(n.selected, 0);
      expect(find.text('root'), findsOneWidget);
      await t.pumpWidget(const SizedBox());
      n.dispose();
      await t.pumpAndSettle();
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'defer works directly from home and initial setup waits for the native read',
    (t) async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags['notifications'] = false;
      await t.runAsync(h.controller.refresh);
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AttendanceSetupReminder(controller: h.controller),
          ),
        ),
      );
      await t.tap(find.text('Agora não'));
      await t.pumpAndSettle();
      expect(find.byKey(const Key('attendance-setup-reminder')), findsNothing);
      final waiting = ExperienceHarness();
      addTearDown(waiting.dispose);
      waiting.permissions.pending = Completer();
      unawaited(waiting.controller.refresh());
      await t.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () =>
                    showAttendanceSetup(context, waiting.controller),
                child: const Text('Configure'),
              ),
            ),
          ),
        ),
      );
      await t.tap(find.text('Configure'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(find.text('Conferindo configuração'), findsOneWidget);
      expect(find.text('Concluir'), findsNothing);
      waiting.permissions.pending!.complete(await h.permissions.read());
      await t.pumpAndSettle();
      await t.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'navigation logs destination errors and ignores late owner work after disposal',
    (t) async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      final n = ProductNavigationController();
      final owner = Object();
      n.bind(
        owner,
        (_) => Future<void>.error(StateError('route failed')),
        logger: h.logger,
      );
      await n.select(1);
      await t.pumpAndSettle();
      expect(
        h.store.rows.any((r) => r['operation'] == 'app_navigation'),
        isTrue,
      );
      n.unbind(owner);
      n.dispose();
      await t.pump();
      expect(t.takeException(), isNull);
    },
  );
  testWidgets(
    'settings gives one step, allows refusal, error recovery and completion',
    (t) async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags['foreground_location'] = false;
      await t.runAsync(h.controller.refresh);
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                AttendanceSetupReminder(controller: h.controller),
                TextButton(
                  onPressed: () => showAttendanceSetup(
                    t.element(find.byType(AttendanceSetupReminder)),
                    h.controller,
                  ),
                  child: const Text('Configure'),
                ),
              ],
            ),
          ),
        ),
      );
      await t.tap(find.text('Concluir'));
      await t.pumpAndSettle();
      expect(find.text('Histórico de capturas'), findsNothing);
      expect(find.textContaining('Permita a localização'), findsWidgets);
      h.permissions.grant = false;
      await t.tap(find.text('Continuar'));
      await t.pumpAndSettle();
      expect(find.textContaining('ainda não foi ativado'), findsOneWidget);
      h.permissions.actionError = StateError('settings failed');
      await t.tap(find.text('Continuar'));
      await t.pumpAndSettle();
      expect(find.textContaining('Não foi possível abrir'), findsOneWidget);
      await t.tap(find.text('Agora não').last);
      await t.pumpAndSettle();
      expect(find.byKey(const Key('attendance-setup-reminder')), findsNothing);
      await t.tap(find.text('Configure'));
      await t.pumpAndSettle();
      h.permissions.actionError = null;
      h.permissions.grant = true;
      await t.tap(find.text('Continuar'));
      await t.pumpAndSettle();
      expect(find.text('Tudo pronto'), findsOneWidget);
      await t.tap(find.text('Concluir'));
      await t.pumpAndSettle();
      h.permissions.readError = StateError('bridge unavailable');
      await t.runAsync(h.controller.refresh);
      await t.pumpAndSettle();
      await t.tap(find.text('Configure'));
      await t.pumpAndSettle();
      expect(find.text('Conferir configuração'), findsOneWidget);
      h.permissions.readError = null;
      await t.tap(find.text('Tentar novamente'));
      await t.pumpAndSettle();
      expect(find.text('Tudo pronto'), findsOneWidget);
      await t.pumpWidget(const SizedBox());
      await t.pumpAndSettle();
      expect(t.takeException(), isNull);
    },
  );
  for (final fails in [false, true]) {
    testWidgets(
      'settings shows honest results and recoverable campus edits (failure=$fails)',
      (t) async {
        final h = ExperienceHarness();
        addTearDown(h.dispose);
        final campus = _Campus();
        var saved = 0, account = 0, logout = 0;
        if (fails) {
          h.reportError = StateError('read failed');
          campus.readError = true;
        } else {
          h.reports = [experienceReceipt(experienceSession())];
        }
        await t.runAsync(h.controller.refresh);
        await t.pumpWidget(
          MaterialApp(
            home: AppSettingsPage(
              user: const AuthUser(id: 'owner', email: 'owner@ufmg.br'),
              logger: h.logger,
              attendance: h.controller,
              campusSelection: campus,
              onCampusChanged: () => saved++,
              onAcademicAccount: () async {
                account++;
              },
              onSignOut: () async {
                logout++;
              },
            ),
          ),
        );
        await t.pumpAndSettle();
        expect(find.text('Configuração pronta'), findsOneWidget);
        expect(find.textContaining('Os resultados estão'), findsNothing);
        await t.ensureVisible(find.text('Local das aulas'));
        await t.tap(find.text('Local das aulas'));
        await t.pumpAndSettle();
        if (fails) {
          expect(find.text('Tentar novamente'), findsOneWidget);
          campus.readError = false;
          await t.tap(find.text('Tentar novamente'));
          await t.pumpAndSettle();
          campus.saveError = true;
        }
        final name = CampusAreas.values.first.name;
        await t.tap(find.text(name));
        await t.pumpAndSettle();
        if (fails) {
          expect(
            find.text('Não foi possível salvar o campus.'),
            findsOneWidget,
          );
          expect(saved, 0);
          campus.saveError = false;
          await t.tap(find.text(name));
          await t.pumpAndSettle();
        }
        expect(saved, 1);
        expect(campus.id, CampusAreas.values.first.id);
        await t.ensureVisible(
          find.byKey(const Key('settings-academic-account')),
        );
        await t.tap(find.byKey(const Key('settings-academic-account')));
        expect(account, 1);
        expect(find.text('Arquivos no aparelho'), findsNothing);
        await t.pump(const Duration(seconds: 5));
        await t.pumpAndSettle();
        await t.ensureVisible(find.text('Sair da conta'));
        await t.tap(find.text('Sair da conta'));
        expect(logout, 1);
        expect(t.takeException(), isNull);
      },
    );
  }
  testWidgets('missing settings status is guided, not a technical checklist', (
    t,
  ) async {
    final h = ExperienceHarness();
    addTearDown(h.dispose);
    h.permissions.flags['notifications'] = false;
    await t.runAsync(h.controller.refresh);
    await t.pumpWidget(
      MaterialApp(
        home: AppSettingsPage(
          user: const AuthUser(
            id: 'owner',
            email: 'x@ufmg.br',
            displayName: 'Estudante',
          ),
          logger: h.logger,
          attendance: h.controller,
          onSignOut: () async {},
        ),
      ),
    );
    await t.tap(find.text('Presença nas aulas'));
    await t.pumpAndSettle();
    expect(find.textContaining('Permita notificações'), findsWidgets);
    await t.tap(find.text('Agora não'));
    await t.pumpAndSettle();
    expect(h.controller.showReminder, isFalse);
    expect(find.text('Permissões do aplicativo'), findsNothing);
    expect(find.text('Presença automática'), findsNothing);
    await t.pumpWidget(
      MaterialApp(
        home: AppSettingsPage(
          user: const AuthUser(id: 'owner', email: 'x@ufmg.br'),
          logger: h.logger,
          onSignOut: () async {},
        ),
      ),
    );
    await t.pumpAndSettle();
    expect(find.text('Local das aulas'), findsNothing);
  });
}

class _Campus implements CampusSelectionGateway {
  bool readError = false, saveError = false;
  String? id;
  @override
  Future<String?> read() async {
    if (readError) throw StateError('campus read');
    return id;
  }

  @override
  Future<void> save(String value) async {
    if (saveError) throw StateError('campus write');
    id = value;
  }
}
