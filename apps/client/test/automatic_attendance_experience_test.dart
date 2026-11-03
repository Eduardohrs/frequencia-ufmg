import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/settings/automatic_attendance_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'fixtures/product_experience_fixture.dart';

void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  final mappings = {
    AttendanceSetupNeed.locationServices: (
      'location_services',
      AttendancePermissionAction.locationSettings,
    ),
    AttendanceSetupNeed.location: (
      'foreground_location',
      AttendancePermissionAction.requestLocation,
    ),
    AttendanceSetupNeed.precise: (
      'precise_location',
      AttendancePermissionAction.appSettings,
    ),
    AttendanceSetupNeed.background: (
      'background_location',
      AttendancePermissionAction.backgroundSettings,
    ),
    AttendanceSetupNeed.battery: (
      'battery_unrestricted',
      AttendancePermissionAction.batterySettings,
    ),
    AttendanceSetupNeed.notifications: (
      'notifications',
      AttendancePermissionAction.requestNotifications,
    ),
  };
  for (final entry in mappings.entries) {
    test(
      'guided setup fixes ${entry.key.name} alone with a correlated outcome',
      () async {
        final h = ExperienceHarness();
        addTearDown(h.dispose);
        h.permissions.flags[entry.value.$1] = false;
        expect(h.controller.title, 'Conferindo configuração');
        await h.controller.refresh();
        expect(h.controller.title, 'Concluir configuração');
        expect(h.controller.next, entry.key);
        expect(h.controller.instruction, isNotEmpty);
        expect(h.controller.showReminder, isTrue);
        await h.controller.resolveNext();
        expect(h.permissions.actions, [entry.value.$2]);
        expect(h.controller.next, isNull);
        expect(h.controller.title, 'Configuração pronta');
        final start = h.store.rows.singleWhere(
          (r) => r['event'] == 'attendance_setup_action_started',
        );
        final end = h.store.rows.singleWhere(
          (r) => r['event'] == 'attendance_setup_action_succeeded',
        );
        expect(start['correlationId'], end['correlationId']);
        expect(end['durationMs'], isA<int>());
        final fields = jsonDecode(end['details'] as String) as Map;
        expect(fields['need_resolved'], isTrue);
        expect(fields['remaining_count'], 0);
        expect(fields['permissions_available'], isTrue);
        await h.controller.resolveNext();
        expect(h.permissions.actions, hasLength(1));
      },
    );
  }
  test(
    'blocked requests open settings and exact alarms use the existing native action',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags.addAll({
        'foreground_location': false,
        'location_requestable': false,
        'notifications': false,
        'notifications_requestable': false,
        'exact_alarms': false,
      });
      await h.controller.refresh();
      await h.controller.resolveNext();
      expect(
        h.permissions.actions.single,
        AttendancePermissionAction.appSettings,
      );
      expect(h.controller.next, AttendanceSetupNeed.alarms);
      expect(h.controller.instruction, contains('alarmes'));
      await h.controller.resolveNext();
      expect(h.nativeActions, ['request_alarm_permission']);
      await h.controller.resolveNext();
      expect(
        h.permissions.actions.last,
        AttendancePermissionAction.notificationSettings,
      );
    },
  );
  test(
    'unknown alarm support is not misrepresented as a denied permission',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags['exact_alarms'] = null;
      await h.controller.refresh();
      expect(h.controller.needs, isEmpty);
      expect(h.controller.showReminder, isFalse);
      expect(h.controller.instruction, contains('disciplin'));
    },
  );
  test(
    'defer persists per account and expires without disabling any permission',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags['battery_unrestricted'] = false;
      await h.controller.refresh();
      await h.controller.defer();
      expect(h.controller.showReminder, isFalse);
      expect(h.permissions.actions, isEmpty);
      final fresh = ExperienceHarness();
      addTearDown(fresh.dispose);
      fresh.permissions.flags['battery_unrestricted'] = false;
      await fresh.controller.refresh();
      expect(fresh.controller.showReminder, isFalse);
      fresh.time = fresh.time.add(const Duration(hours: 25));
      expect(fresh.controller.showReminder, isTrue);
    },
  );
  test(
    'read failures retain previous local evidence and identify the exact failed stage',
    () async {
      final h = ExperienceHarness(preferences: _BrokenPreferences());
      addTearDown(h.dispose);
      final report = experienceReceipt(experienceSession());
      h.reports = [
        report,
        {...report, 'account_id': 'foreign'},
      ];
      await h.controller.refresh();
      expect(h.controller.reports, [report]);
      h.permissions.readError = StateError('permission service unavailable');
      h.reportError = StateError('native receipt storage unavailable');
      await h.controller.refresh();
      expect(h.controller.reports, [report]);
      expect(h.controller.permissionError, isTrue);
      expect(h.controller.reportError, isTrue);
      expect(h.controller.title, contains('Não foi possível'));
      expect(h.controller.instruction, contains('registro manual'));
      final errors = h.store.rows
          .where((r) => r['event'] == 'app_exception')
          .map((r) => jsonDecode(r['errorDetails'] as String) as Map)
          .toList();
      expect(
        errors.map((r) => r['stage']),
        containsAll(['permissions', 'local_receipts', 'snooze_read']),
      );
      final complete = h.store.rows.lastWhere(
        (r) => r['event'] == 'attendance_setup_read_completed',
      );
      final data = jsonDecode(complete['details'] as String) as Map;
      expect(data['receipt_count'], 1);
      expect(data['permissions_available'], isFalse);
      expect(data['receipts_available'], isFalse);
      expect(complete['durationMs'], isA<int>());
    },
  );
  test(
    'failed defer storage still honors the decision in the running app',
    () async {
      final h = ExperienceHarness(preferences: _WriteBrokenPreferences());
      addTearDown(h.dispose);
      h.permissions.flags['battery_unrestricted'] = false;
      await h.controller.refresh();
      await h.controller.defer();
      await h.controller.refresh();
      expect(h.controller.showReminder, isFalse);
      expect(
        h.store.rows.any((r) => r['operation'] == 'attendance_setup_defer'),
        isTrue,
      );
    },
  );
  for (final native in [false, true]) {
    test('failed permission action is recoverable (native=$native)', () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.flags[native ? 'exact_alarms' : 'battery_unrestricted'] =
          false;
      if (native) {
        h.nativeError = StateError('activity unavailable');
      } else {
        h.permissions.actionError = StateError('activity unavailable');
      }
      await h.controller.refresh();
      await expectLater(h.controller.resolveNext(), throwsStateError);
      expect(h.controller.acting, isFalse);
      final error = h.store.rows.singleWhere(
        (r) => r['operation'] == 'attendance_setup_action',
      );
      final fields = jsonDecode(error['errorDetails'] as String) as Map;
      expect(fields['stage'], 'system_settings');
      expect(fields['need'], native ? 'alarms' : 'battery');
      expect(error['durationMs'], isA<int>());
    });
  }
  testWidgets(
    'hung native reads time out, and a disposed owner rejects late updates',
    (tester) async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.permissions.pending = Completer();
      h.pendingReports = Completer();
      final pending = h.controller.refresh();
      await tester.pump(const Duration(seconds: 11));
      await pending;
      expect(h.controller.permissionError, isTrue);
      expect(h.controller.reportError, isTrue);
      expect(h.controller.busy, isFalse);
      h.dispose();
      h.permissions.pending!.complete(
        AttendancePermissionStatus.fromMap(h.permissions.flags),
      );
      h.pendingReports!.complete([]);
      await h.controller.refresh();
    },
  );
  test(
    'parallel refresh calls share work and a requested followup reads again',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      h.pendingReports = Completer();
      final first = h.controller.refresh();
      final second = h.controller.refresh();
      final followup = h.controller.refresh(afterCurrent: true);
      h.pendingReports!.complete([]);
      await Future.wait([first, second, followup]);
      expect(h.permissions.reads, 2);
    },
  );
  test(
    'disposal during an unresolved read prevents notifying detached listeners',
    () async {
      final h = ExperienceHarness();
      h.pendingReports = Completer();
      var count = 0;
      h.controller.addListener(() => count++);
      final pending = h.controller.refresh();
      h.dispose();
      h.pendingReports!.complete([]);
      await pending;
      expect(count, 1);
    },
  );
  test(
    'server evidence and unavailable or future records are distinguished',
    () {
      String? label(s, {bool failed = false}) =>
          attendanceEvidence('poo', s, experienceNow, localReadFailed: failed);
      expect(
        label(experienceSession(calendar: SessionCalendarStatus.noCall)),
        isNull,
      );
      expect(
        label(experienceSession(status: SituacaoFrequencia.present)),
        contains('Registro salvo'),
      );
      expect(
        label(experienceSession(), failed: true),
        contains('Não foi possível'),
      );
      expect(
        label(
          experienceSession(start: experienceNow.add(const Duration(hours: 1))),
        ),
        contains('Aula futura'),
      );
      expect(
        label(
          experienceSession(
            start: experienceNow.subtract(const Duration(minutes: 5)),
          ),
        ),
        contains('Aula em andamento'),
      );
      expect(label(experienceSession()), contains('Sem evidência'));
      for (final state in EstadoPing.values) {
        expect(label(experienceSession(first: state)), contains('Início:'));
        expect(label(experienceSession(second: state)), contains('Fim:'));
      }
    },
  );
  for (final state in [
    'scheduled',
    'running',
    'succeeded',
    'cancelled',
    'superseded',
    'timeout',
  ]) {
    test('capture status $state is described without raw diagnostics', () {
      final s = experienceSession();
      final report = experienceReceipt(
        s,
        state: state,
        enabled: false,
        moment: null,
      );
      final text = attendanceEvidence(
        'poo',
        s,
        experienceNow,
        reports: [report],
      );
      expect(text, isNot(contains('sincronização')));
      expect(text, isNot(contains('timeout')));
      expect(text, contains('Início:'));
      if (state == 'scheduled') expect(text, contains('agendada'));
      if (state == 'running') expect(text, contains('verificando'));
    });
  }
  test('latest matching capture wins, with meaningful delivery outcomes', () {
    final s = experienceSession();
    for (final ping in ['no_campus', 'fora', 'indisponivel']) {
      for (final delivery in [
        'applied',
        'already_applied',
        'preserved',
        'unresolved',
        'rejected',
        'retry',
        'sending',
        'discarded',
        null,
      ]) {
        final latest = {
          ...experienceReceipt(s, ping: ping, delivery: delivery),
          'scheduled_at_ms': 2,
        };
        final old = {
          ...experienceReceipt(s, state: 'timeout'),
          'scheduled_at_ms': 1,
        };
        final text = attendanceEvidence(
          'poo',
          s,
          experienceNow,
          reports: [
            old,
            latest,
            experienceReceipt(
              s,
              moment: 'second',
              enabled: false,
              delivery: 'discarded',
            ),
            {...latest, 'starts_at_ms': 0},
          ],
        );
        expect(text, isNot(contains('não obtida')));
        if (delivery == 'preserved') expect(text, contains('mantido'));
        if (delivery == 'retry' || delivery == null) {
          expect(text, contains('aguardando sincronização'));
        }
        if (delivery == 'unresolved' || delivery == 'rejected') {
          expect(text, contains('registre sua frequência'));
        }
      }
    }
  });
}

class _BrokenPreferences extends SharedPreferencesAsync {
  @override
  Future<int?> getInt(String key) async =>
      throw StateError('preference read failed');
}

class _WriteBrokenPreferences extends SharedPreferencesAsync {
  @override
  Future<void> setInt(String key, int value) async =>
      throw StateError('preference write failed');
}
