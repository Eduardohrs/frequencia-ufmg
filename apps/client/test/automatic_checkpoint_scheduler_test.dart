import 'dart:convert';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/automatic_checkpoint_scheduler.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'fixtures/campus_location_fixture.dart';
import 'first_checkpoint_test.dart' show course, session, now, Selection;

void main() {
  test(
    'an empty native schedule response is a diagnosable failure, not success',
    () async {
      final h = Harness();
      final scheduler = AutomaticCheckpointScheduler(
        permissions: h.permissions,
        selection: h.selection,
        logger: h.logger,
        perform: (_, _) async => [],
        isActive: () => true,
        now: () => now,
      );
      await scheduler.reconcile(
        AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {
            'poo': [session('today')],
          },
        ),
        trigger: 'test',
      );
      expect(h.logger.events.last.$2!['scheduled'], 0);
      expect(h.logger.events.last.$2!['failed'], 2);
    },
  );

  test(
    'persisted telemetry identifies the item, stage, partial result and correlation',
    () async {
      final h = Harness()
        ..failAction = 'schedule'
        ..failMoment = 'first';
      final store = CheckpointLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'owner',
        platform: 'android',
      );
      final scheduler = AutomaticCheckpointScheduler(
        permissions: h.permissions,
        selection: h.selection,
        logger: logger,
        perform: h.scheduler.perform,
        isActive: () => true,
        now: () => now,
      );
      await scheduler.reconcile(
        AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {
            'poo': [session('today')],
          },
        ),
        trigger: 'overview_loaded',
      );
      await Future<void>.delayed(Duration.zero);
      final terminal = store.documents.singleWhere(
        (d) => d['event'] == 'automatic_checkpoint_reconcile_finished',
      );
      final start = store.documents.singleWhere(
        (d) => d['event'] == 'automatic_checkpoint_reconcile_started',
      );
      expect(terminal['correlationId'], start['correlationId']);
      final details = jsonDecode(terminal['details'] as String) as Map;
      expect(details['failed'], 1);
      expect(details['scheduled'], 1);
      final error = store.documents.singleWhere(
        (d) => d['errorCode'] == 'automatic_checkpoint_reconcile_failed',
      );
      final failure = jsonDecode(error['errorDetails'] as String) as Map;
      expect(failure['stage'], 'schedule');
      expect(failure['course_id'], 'poo');
      expect(failure['moment'], 'first');
      expect(error['correlationId'], terminal['correlationId']);
    },
  );

  test('one free slot never schedules an incomplete new pair', () async {
    final h = Harness();
    h.reports.addAll(
      List.generate(49, (i) => {'operation_id': '$i', 'status': 'succeeded'}),
    );
    await h.run();
    expect(h.calls.where((c) => c.$1 == 'schedule'), isEmpty);
    expect(h.logger.events.last.$2!['deferred_capacity'], 2);
  });
  test(
    'campus change replaces only future alarms with a new revision',
    () async {
      final h = Harness();
      await h.run();
      h.selection.value = 'direito';
      await h.run();
      expect(h.logger.events.last.$2!['cancelled'], 2);
      expect(h.reports, hasLength(2));
      expect(h.reports.every((r) => r['campus_id'] == 'direito'), isTrue);
    },
  );

  for (final flag in [
    'precise_location',
    'battery_unrestricted',
    'exact_alarms',
  ]) {
    test('blocked $flag never asks permissions or schedules', () async {
      final h = Harness()..permissions.flags[flag] = false;
      await h.run();
      expect(h.calls, isEmpty);
      expect(h.logger.events.last.$1, 'automatic_checkpoint_reconcile_blocked');
    });
  }
  test(
    'repeated snapshots retain the same pair and serialize concurrent refreshes',
    () async {
      final h = Harness();
      await Future.wait([h.run(), h.run()]);
      expect(h.calls.where((c) => c.$1 == 'schedule'), hasLength(2));
      expect(h.reports, hasLength(2));
      expect(h.logger.events.last.$2!['retained'], 2);
    },
  );
  test(
    'cancellation and removal only erase untouched automatic alarms',
    () async {
      final h = Harness();
      await h.run();
      h.reports.add({'operation_id': 'manual', 'status': 'scheduled'});
      await h.run(
        snapshot: AcademicOverviewSnapshot(courses: [], sessionsByCourse: {}),
      );
      expect(h.reports.single['operation_id'], 'manual');
      expect(h.logger.events.last.$2!['cancelled'], 2);
    },
  );
  for (final stale in [true, false]) {
    test('unknown sessions are retained (local=$stale)', () async {
      final h = Harness();
      await h.run();
      final before = h.reports.length;
      await h.run(
        snapshot: AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {},
          isLocalCopy: stale,
        ),
      );
      expect(h.reports, hasLength(before));
    });
  }
  test(
    'one failed item does not block the other moment and is identified',
    () async {
      final h = Harness()
        ..failAction = 'schedule'
        ..failMoment = 'first';
      await h.run();
      expect(h.reports.single['moment'], 'second');
      expect(h.logger.errors.single.$3!['moment'], 'first');
      expect(h.logger.errors.single.$3!['course_id'], 'poo');
      expect(h.logger.events.last.$2!['failed'], 1);
    },
  );
  test(
    'failed removal preserves the receipt and continues best effort',
    () async {
      final h = Harness();
      await h.run();
      h.failAction = 'unschedule_automatic';
      await h.run(
        snapshot: AcademicOverviewSnapshot(courses: [], sessionsByCourse: {}),
      );
      expect(h.reports, hasLength(2));
      expect(h.logger.events.last.$2!['failed'], 2);
    },
  );
  test('capacity does not silently evict evidence', () async {
    final h = Harness();
    h.reports.addAll(
      List.generate(50, (i) => {'operation_id': '$i', 'status': 'succeeded'}),
    );
    await h.run();
    expect(h.reports, hasLength(50));
    expect(h.logger.events.last.$2!['deferred_capacity'], 2);
  });
  test(
    'calendar exceptions and manual attendance never create alarms',
    () async {
      final h = Harness();
      await h.run(
        snapshot: AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {
            'poo': [
              session('cancelled', status: SessionCalendarStatus.cancelled),
              session('holiday', status: SessionCalendarStatus.holiday),
              session('optional', status: SessionCalendarStatus.noCall),
              session('manual', attendance: SituacaoFrequencia.present),
              session(
                'first_already_missed',
                start: now.subtract(const Duration(hours: 1)),
              ),
              session('far', start: now.add(const Duration(days: 20))),
            ],
          },
        ),
      );
      expect(h.reports, isEmpty);
    },
  );
  for (final phase in ['read', 'clear_automatic_completed']) {
    test(
      'records exact native failure stage $phase and recovers next refresh',
      () async {
        final h = Harness()..failAction = phase;
        await h.run();
        expect(h.logger.errors, hasLength(1));
        h.failAction = null;
        await h.run();
        expect(h.reports, hasLength(2));
      },
    );
  }
  test(
    'unreadable permissions and campus do not poison future refreshes',
    () async {
      final h = Harness()..permissions.error = StateError('permissions failed');
      await h.run();
      expect(h.logger.errors.last.$3!['stage'], 'permissions');
      h.permissions.error = null;
      h.selection.fail = true;
      await h.run();
      expect(h.logger.errors.last.$3!['stage'], 'campus');
      h.selection.fail = false;
      await h.run();
      expect(h.reports, hasLength(2));
    },
  );
  test(
    'ownership loss stops remaining actions without reactivating an old account',
    () async {
      final h = Harness()..stopAfter = 'read';
      await h.run();
      expect(h.calls.map((c) => c.$1), ['read']);
      final idle = Harness()..active = false;
      await idle.run();
      expect(idle.calls, isEmpty);
    },
  );
  test('logging outage does not stop scheduling', () async {
    final h = Harness()..logger.failLogging = true;
    await h.run();
    expect(h.reports, hasLength(2));
  });

  test(
    'loading the timetable schedules a correlated pair without manual action',
    () async {
      final calls = <(String, Map<String, Object?>)>[];
      final confirmed = <Map<String, Object?>>[];
      final permissions = CampusTestPermissions();
      permissions.flags['exact_alarms'] = true;
      permissions.flags['battery_unrestricted'] = true;
      final logger = CampusTestLogger();
      final scheduler = AutomaticCheckpointScheduler(
        permissions: permissions,
        selection: Selection(),
        logger: logger,
        now: () => now,
        isActive: () => true,
        perform: (action, fields) async {
          calls.add((action, fields));
          if (action == 'schedule') {
            confirmed.add({
              ...fields,
              'operation_id': 'op${confirmed.length}',
              'status': 'scheduled',
            });
          }
          return List.of(confirmed);
        },
      );
      await scheduler.reconcile(
        AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {
            'poo': [session('today')],
          },
        ),
        trigger: 'overview_loaded',
      );
      final scheduled = calls.where((c) => c.$1 == 'schedule').toList();
      expect(logger.errors, isEmpty);
      expect(scheduled, hasLength(2));
      expect(scheduled.map((c) => c.$2['moment']), ['first', 'second']);
      expect(
        scheduled.every((c) => c.$2['schedule_origin'] == 'automatic'),
        isTrue,
      );
      expect(scheduled.every((c) => c.$2['course_id'] == 'poo'), isTrue);
      expect(scheduled.every((c) => c.$2['delivery_enabled'] == true), isTrue);
      expect(
        logger.events.any(
          (e) => e.$1 == 'automatic_checkpoint_reconcile_finished',
        ),
        isTrue,
      );
    },
  );
}

class Harness {
  final permissions = CampusTestPermissions();
  final selection = Selection();
  final logger = CampusTestLogger();
  final calls = <(String, Map<String, Object?>)>[];
  final reports = <Map<String, Object?>>[];
  String? failAction, failMoment, stopAfter;
  bool active = true;
  late final scheduler = AutomaticCheckpointScheduler(
    permissions: permissions,
    selection: selection,
    logger: logger,
    now: () => now,
    isActive: () => active,
    perform: (action, fields) async {
      calls.add((action, fields));
      if (action == stopAfter) active = false;
      if (action == failAction &&
          (failMoment == null || failMoment == fields['moment'])) {
        throw StateError('native $action failed');
      }
      if (action == 'schedule') {
        reports.add({
          ...fields,
          'operation_id': 'op${reports.length}',
          'status': 'scheduled',
          'checkpoint_expected_at_ms': fields['moment'] == 'first'
              ? (fields['starts_at_ms'] as int) + 1200000
              : (fields['ends_at_ms'] as int) - 1200000,
        });
      }
      if (action == 'unschedule_automatic') {
        reports.removeWhere((r) => r['operation_id'] == fields['operation_id']);
      }
      return List.of(reports);
    },
  );
  Harness() {
    permissions.flags['battery_unrestricted'] = true;
    permissions.flags['exact_alarms'] = true;
  }
  Future<void> run({AcademicOverviewSnapshot? snapshot}) => scheduler.reconcile(
    snapshot ??
        AcademicOverviewSnapshot(
          courses: [course()],
          sessionsByCourse: {
            'poo': [session('today')],
          },
        ),
    trigger: 'test_refresh',
  );
}

class CheckpointLogStore implements OperationalLogStore {
  final documents = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async =>
      documents.add(document);
}
