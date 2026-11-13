import '../domain/campus_areas.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../observability/operation_diagnostics.dart';
import 'attendance_permissions.dart';
import 'academic_records.dart';
import 'campus_location.dart';
import 'calendar_status.dart';
import 'first_checkpoint.dart';
import 'python_overview_repository.dart';

typedef CheckpointAction =
    Future<List<Map<String, Object?>>> Function(
      String action,
      Map<String, Object?> fields,
    );

/// Reconciles a bounded local horizon, never writes academic attendance itself.
class AutomaticCheckpointScheduler {
  AutomaticCheckpointScheduler({
    required this.permissions,
    required this.selection,
    required this.logger,
    required this.perform,
    required this.isActive,
    required this.now,
  });
  final AttendancePermissionsGateway permissions;
  final CampusSelectionGateway selection;
  final AppLogger logger;
  final CheckpointAction perform;
  final bool Function() isActive;
  final DateTime Function() now;
  Future<void> _tail = Future.value();

  Future<void> reconcile(
    AcademicOverviewSnapshot snapshot, {
    required String trigger,
  }) {
    final next = _tail.then((_) => _reconcile(snapshot, trigger));
    // An earlier failed input must not poison later refreshes.
    _tail = next.catchError((Object _) {});
    return next;
  }

  Future<void> _reconcile(
    AcademicOverviewSnapshot snapshot,
    String trigger,
  ) async {
    if (!isActive()) return;
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('automaticCheckpoints'),
      'operation': 'automatic_checkpoints',
      'trigger': trigger,
      'is_local_copy': snapshot.isLocalCopy,
      'horizon_days': 14,
    };
    var stage = 'permissions';
    var scheduled = 0, retained = 0, cancelled = 0, failed = 0, deferred = 0;
    bool stillActive() {
      if (isActive()) return true;
      emitOperationalEvent(logger, 'automatic_checkpoint_reconcile_aborted', {
        ...fields,
        'stage': stage,
        'reason': 'owner_inactive',
        'duration_ms': watch.elapsedMilliseconds,
      });
      return false;
    }

    emitOperationalEvent(
      logger,
      'automatic_checkpoint_reconcile_started',
      fields,
    );
    try {
      final status = await permissions.read();
      if (!stillActive()) return;
      final reason = !status.locationReady
          ? 'location_permission_or_service'
          : !status.batteryUnrestricted
          ? 'battery_optimization_required'
          : status.exactAlarms != true
          ? 'exact_alarm_permission_required'
          : null;
      if (reason != null) {
        emitOperationalEvent(logger, 'automatic_checkpoint_reconcile_blocked', {
          ...fields,
          'stage': stage,
          'reason': reason,
        });
        return;
      }
      stage = 'campus';
      final campus =
          CampusAreas.find(await selection.read() ?? '') ??
          CampusAreas.defaultArea;
      if (!stillActive()) return;
      stage = 'read_reports';
      var reports = await perform('read', const {});
      if (!stillActive()) return;
      stage = 'clear_acknowledged';
      reports = await perform('clear_automatic_completed', const {});
      if (!stillActive()) return;
      final instant = now();
      final horizon = instant.add(const Duration(days: 14));
      final desired = <Map<String, Object?>>[];
      for (final course in snapshot.courses.where((c) => c.tracksAttendance)) {
        for (final session
            in snapshot.sessionsByCourse[course.id] ??
                const <SessionRecord>[]) {
          if (!session.calendarStatus.requiresAttendance ||
              session.attendanceStatus != null ||
              session.endsAt.isBefore(instant) ||
              session.startsAt.isAfter(horizon)) {
            continue;
          }
          final base = <String, Object?>{
            'schedule_origin': 'automatic',
            'delivery_enabled': true,
            'course_id': course.id,
            'course_code': course.code,
            'session_id': session.id,
            'starts_at_ms': session.startsAt.millisecondsSinceEpoch,
            'ends_at_ms': session.endsAt.millisecondsSinceEpoch,
            'lesson_count': session.lessonCount.value,
            'call_count': session.callCount.value,
            'campus_id': campus.id,
            'campus_name': campus.name,
            'rectangles': FirstCheckpointGateway.rectangles(campus),
          };
          final first = session.startsAt.add(const Duration(minutes: 20));
          final second = session.endsAt.subtract(const Duration(minutes: 20));
          // No retroactive absence: a missed first ping cannot be invented.
          final hasFirst = reports.any(
            (r) =>
                _revision(r, {...base, 'moment': 'first'}) &&
                const [
                  'scheduled',
                  'running',
                  'succeeded',
                ].contains(r['status']),
          );
          if (!first.isAfter(instant) && !hasFirst) continue;
          if (first.isAfter(instant)) {
            desired.add({
              ...base,
              'moment': 'first',
              'expected': first.millisecondsSinceEpoch,
            });
          }
          if (second.isAfter(first) && second.isAfter(instant)) {
            desired.add({
              ...base,
              'moment': 'second',
              'expected': second.millisecondsSinceEpoch,
            });
          }
        }
      }
      desired.sort(
        (a, b) => (a['expected'] as int).compareTo(b['expected'] as int),
      );
      // Incomplete/offline snapshots may add known work, never erase missing work.
      stage = 'unschedule';
      if (!snapshot.isLocalCopy) {
        final courses = {for (final c in snapshot.courses) c.id: c};
        for (final report in List<Map<String, Object?>>.of(reports)) {
          if (!stillActive()) return;
          if (report['schedule_origin'] != 'automatic' ||
              report['status'] != 'scheduled') {
            continue;
          }
          final courseId = report['course_id'];
          if (courses.containsKey(courseId) &&
              !snapshot.sessionsByCourse.containsKey(courseId)) {
            continue;
          }
          final course = courses[courseId];
          final sessions =
              snapshot.sessionsByCourse[courseId] ?? const <SessionRecord>[];
          final current = sessions.where((s) => s.id == report['session_id']);
          final obsolete =
              course == null ||
              !course.tracksAttendance ||
              current.isEmpty ||
              !current.first.calendarStatus.requiresAttendance ||
              current.first.attendanceStatus != null ||
              !desired.any((d) => _revision(report, d)) &&
                  (report['checkpoint_expected_at_ms'] as num? ?? 0) >
                      instant.millisecondsSinceEpoch;
          if (!obsolete) continue;
          try {
            reports = await perform('unschedule_automatic', {
              'operation_id': report['operation_id'],
            });
            cancelled++;
          } catch (error, stack) {
            failed++;
            _failure(error, stack, fields, 'unschedule', report);
          }
        }
      }
      stage = 'schedule';
      for (final target in desired) {
        if (!stillActive()) return;
        if (reports.any(
          (r) =>
              _revision(r, target) &&
              const ['scheduled', 'running', 'succeeded'].contains(r['status']),
        )) {
          retained++;
          continue;
        }
        final missingForSession = desired
            .where(
              (d) =>
                  d['course_id'] == target['course_id'] &&
                  d['session_id'] == target['session_id'] &&
                  !reports.any(
                    (r) =>
                        _revision(r, d) &&
                        const [
                          'scheduled',
                          'running',
                          'succeeded',
                        ].contains(r['status']),
                  ),
            )
            .length;
        if (reports.length + missingForSession > 50) {
          deferred++;
          continue;
        }
        try {
          final payload = Map<String, Object?>.of(target)..remove('expected');
          reports = await perform('schedule', payload);
          final confirmed = reports.where((r) => _revision(r, target));
          if (confirmed.isEmpty) {
            throw StateError(
              'automatic_checkpoint_schedule_confirmation_missing',
            );
          }
          emitOperationalEvent(logger, 'automatic_checkpoint_scheduled', {
            ...fields,
            'stage': 'schedule',
            'course_id': target['course_id']!,
            'session_id': target['session_id']!,
            'moment': target['moment']!,
            'checkpoint_operation_id': ?confirmed.first['operation_id'],
          });
          scheduled++;
        } catch (error, stack) {
          failed++;
          _failure(error, stack, fields, 'schedule', target);
        }
      }
      if (deferred > 0) {
        // The 50-item capacity must never silently truncate the semester:
        // desired items are ordered by expected time, so the farthest ones
        // are deferred first, and the shortfall is surfaced as a diagnostic.
        emitOperationalEvent(logger, 'automatic_checkpoint_capacity_exceeded', {
          ...fields,
          'stage': 'finished',
          'duration_ms': watch.elapsedMilliseconds,
          'desired': desired.length,
          'deferred_capacity': deferred,
          'capacity_limit': 50,
        });
        recordOperationalFailure(
          logger,
          StateError('automatic_checkpoint_capacity_exceeded'),
          StackTrace.current,
          'automatic_checkpoint_reconcile',
          {...fields, 'stage': 'capacity', 'deferred_capacity': deferred},
          failureCode: 'automatic_checkpoint_capacity_exceeded',
        );
      }
      emitOperationalEvent(logger, 'automatic_checkpoint_reconcile_finished', {
        ...fields,
        'stage': 'finished',
        'duration_ms': watch.elapsedMilliseconds,
        'scheduled': scheduled,
        'retained': retained,
        'cancelled': cancelled,
        'failed': failed,
        'deferred_capacity': deferred,
        'desired': desired.length,
        'capacity_warning': deferred > 0,
      });
    } catch (error, stack) {
      _failure(
        error,
        stack,
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        stage,
        const {},
      );
    }
  }

  static bool _revision(Map<String, Object?> a, Map<String, Object?> b) =>
      const [
        'course_id',
        'session_id',
        'starts_at_ms',
        'ends_at_ms',
        'campus_id',
        'lesson_count',
        'call_count',
        'moment',
      ].every((key) => a[key] == b[key]);

  void _failure(
    Object error,
    StackTrace stack,
    Map<String, Object> fields,
    String stage,
    Map<String, Object?> target,
  ) => recordOperationalFailure(
    logger,
    error,
    stack,
    'automatic_checkpoint_reconcile',
    {
      ...fields,
      'stage': stage,
      'course_id': ?target['course_id'],
      'course_code': ?target['course_code'],
      'session_id': ?target['session_id'],
      'moment': ?target['moment'],
    },
    failureCode: 'automatic_checkpoint_reconcile_failed',
  );
}
