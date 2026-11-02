import '../domain/attendance.dart';
import 'academic_records.dart';
import 'calendar_status.dart';

/// A local estimate; never writes to a repository or replaces a saved record.
class CheckpointAttendanceEstimate {
  CheckpointAttendanceEstimate._(
    this.first,
    this.second,
    this.status,
    this.absences,
    this.complete,
    this.firstReason,
    this.secondReason,
    this.firstOperation,
    this.secondOperation,
    this.preservesExistingRecord,
  );
  final EstadoPing first, second;
  final SituacaoFrequencia status;
  final int? absences;
  final bool complete, preservesExistingRecord;
  final String? firstReason, secondReason;
  final Object? firstOperation, secondOperation;

  static bool matches(
    Map<String, Object?> report,
    String courseId,
    SessionRecord session,
    String campusId,
  ) =>
      report['course_id'] == courseId &&
      report['session_id'] == session.id &&
      report['starts_at_ms'] == session.startsAt.millisecondsSinceEpoch &&
      report['ends_at_ms'] == session.endsAt.millisecondsSinceEpoch &&
      report['campus_id'] == campusId &&
      (!report.containsKey('lesson_count') ||
          report['lesson_count'] == session.lessonCount.value) &&
      (!report.containsKey('call_count') ||
          report['call_count'] == session.callCount.value);

  factory CheckpointAttendanceEstimate.fromReports({
    required String courseId,
    required SessionRecord session,
    required String campusId,
    required Iterable<Map<String, Object?>> reports,
    DateTime? now,
  }) {
    Map<String, Object?>? latest(String moment) {
      Map<String, Object?>? found;
      for (final r in reports) {
        if (!matches(r, courseId, session, campusId) ||
            (r['moment'] ?? 'first') != moment) {
          continue;
        }
        final time = r['scheduled_at_ms'];
        if (time is! int) continue;
        if (found == null || time >= (found['scheduled_at_ms']! as int)) {
          found = r;
        }
      }
      return found;
    }

    final a = latest('first'), b = latest('second');
    (EstadoPing, String?) ping(Map<String, Object?>? r, String moment) {
      if (r == null) return (EstadoPing.unavailable, 'not_scheduled');
      if (r['status'] != 'succeeded') {
        return (EstadoPing.unavailable, 'capture_${r['status']}');
      }
      final expected =
          (moment == 'first'
                  ? session.startsAt.add(const Duration(minutes: 20))
                  : session.endsAt.subtract(const Duration(minutes: 20)))
              .millisecondsSinceEpoch;
      final captured = r['captured_at_ms'];
      if (r['checkpoint_expected_at_ms'] != expected ||
          captured is! int ||
          captured < expected ||
          captured - expected > 300000 ||
          captured >= session.endsAt.millisecondsSinceEpoch) {
        return (EstadoPing.unavailable, 'invalid_capture_time');
      }
      final value = r[moment == 'first' ? 'first_ping' : 'second_ping'];
      for (final state in EstadoPing.values) {
        if (state.code == value) return (state, null);
      }
      return (EstadoPing.unavailable, 'invalid_ping');
    }

    final (first, ar) = ping(a, 'first');
    final (second, br) = ping(b, 'second');
    final domain = SessaoAula(
      session.id,
      ConfiguracaoSessao(
        aulas: session.lessonCount,
        chamadas: session.callCount,
      ),
    );
    final status = session.calendarStatus.requiresAttendance
        ? domain.classificar(first, second)
        : SituacaoFrequencia.pending;
    bool done(Map<String, Object?>? r, String moment) {
      if (r != null) {
        return r['status'] != 'scheduled' && r['status'] != 'running';
      }
      final expected = moment == 'first'
          ? session.startsAt.add(const Duration(minutes: 20))
          : session.endsAt.subtract(const Duration(minutes: 20));
      final instant = now ?? DateTime.now();
      return !instant.isBefore(session.endsAt) ||
          instant.isAfter(expected.add(const Duration(minutes: 5)));
    }

    return CheckpointAttendanceEstimate._(
      first,
      second,
      status,
      domain.calcularFaltas(status),
      done(a, 'first') && done(b, 'second'),
      ar,
      br,
      a?['operation_id'],
      b?['operation_id'],
      session.attendanceStatus != null ||
          session.firstPing != null ||
          session.secondPing != null,
    );
  }
  Map<String, Object?> toLogFields() => {
    'first_ping': first.code,
    'second_ping': second.code,
    'attendance_status': status.code,
    'absences': absences,
    'complete': complete,
    'first_reason': firstReason,
    'second_reason': secondReason,
    'first_operation_id': firstOperation,
    'second_operation_id': secondOperation,
    'existing_record_preserved': preservesExistingRecord,
  };
}
