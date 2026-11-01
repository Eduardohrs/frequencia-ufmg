import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/checkpoint_attendance_estimate.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';

final start = DateTime.utc(2026, 11, 1, 12);
SessionRecord session({
  NumeroChamadas calls = NumeroChamadas.two,
  QuantidadeAulas lessons = QuantidadeAulas.two,
  SituacaoFrequencia? saved,
  EstadoPing? first,
  EstadoPing? second,
  SessionCalendarStatus calendar = SessionCalendarStatus.scheduled,
}) => SessionRecord(
  id: 's',
  startsAt: start,
  endsAt: start.add(const Duration(minutes: 100)),
  lessonCount: lessons,
  callCount: calls,
  attendanceStatus: saved,
  absences: saved == null
      ? null
      : saved == SituacaoFrequencia.absent
      ? lessons.value
      : 0,
  firstPing: first,
  secondPing: second,
  calendarStatus: calendar,
  createdAt: start,
  updatedAt: start,
);
Map<String, Object?> report(String moment, String ping) {
  final expected = start
      .add(Duration(minutes: moment == 'first' ? 20 : 80))
      .millisecondsSinceEpoch;
  return {
    'course_id': 'c',
    'session_id': 's',
    'campus_id': 'pampulha',
    'starts_at_ms': start.millisecondsSinceEpoch,
    'ends_at_ms': session().endsAt.millisecondsSinceEpoch,
    'moment': moment,
    'status': 'succeeded',
    'operation_id': moment,
    'scheduled_at_ms': start.millisecondsSinceEpoch,
    'checkpoint_expected_at_ms': expected,
    'captured_at_ms': expected + 1000,
    (moment == 'first' ? 'first_ping' : 'second_ping'): ping,
  };
}

CheckpointAttendanceEstimate estimate(
  List<Map<String, Object?>> reports, {
  SessionRecord? s,
  DateTime? now,
}) => CheckpointAttendanceEstimate.fromReports(
  courseId: 'c',
  session: s ?? session(),
  campusId: 'pampulha',
  reports: reports,
  now: now,
);
void main() {
  test(
    'all moments, call policies and lesson quantities use the canonical attendance rules',
    () {
      for (final calls in NumeroChamadas.values) {
        for (final lessons in QuantidadeAulas.values) {
          if (calls == NumeroChamadas.two && lessons == QuantidadeAulas.one) {
            continue;
          }
          for (final a in EstadoPing.values) {
            for (final b in EstadoPing.values) {
              final r = estimate([
                report('first', a.code),
                report('second', b.code),
              ], s: session(calls: calls, lessons: lessons));
              final unknown =
                  a == EstadoPing.unavailable || b == EstadoPing.unavailable;
              final positive =
                  a == EstadoPing.onCampus || b == EstadoPing.onCampus;
              final expected = unknown
                  ? (calls == NumeroChamadas.one && positive
                        ? SituacaoFrequencia.present
                        : SituacaoFrequencia.pending)
                  : a == EstadoPing.onCampus
                  ? (b == EstadoPing.onCampus
                        ? SituacaoFrequencia.present
                        : SituacaoFrequencia.leftEarly)
                  : b == EstadoPing.onCampus
                  ? SituacaoFrequencia.arrivedLate
                  : SituacaoFrequencia.absent;
              expect(r.status, expected);
              expect(
                r.absences,
                expected == SituacaoFrequencia.pending
                    ? null
                    : expected == SituacaoFrequencia.absent
                    ? lessons.value
                    : expected == SituacaoFrequencia.present ||
                          calls == NumeroChamadas.one
                    ? 0
                    : lessons.value ~/ 2,
              );
              expect(r.complete, true);
            }
          }
        }
      }
    },
  );
  test(
    'missing and failed moments remain explicit; a cancelled newer attempt supersedes success',
    () {
      expect(estimate([]).firstReason, 'not_scheduled');
      final a = report('first', 'no_campus');
      final r = estimate([
        a,
        {
          ...a,
          'status': 'cancelled',
          'scheduled_at_ms': start.millisecondsSinceEpoch + 1,
        },
        report('second', 'fora'),
      ]);
      expect(r.status, SituacaoFrequencia.pending);
      expect(r.firstReason, 'capture_cancelled');
      expect(r.toLogFields()['second_operation_id'], 'second');
      expect(
        estimate([
          a,
          {...report('second', 'fora'), 'status': 'scheduled'},
        ]).complete,
        false,
      );
      expect(
        estimate([
          a,
          {...report('second', 'fora'), 'status': 'running'},
        ]).complete,
        false,
      );
      expect(
        estimate([
          {...a, 'scheduled_at_ms': start.millisecondsSinceEpoch - 1},
          a,
        ]).first,
        EstadoPing.onCampus,
      );
    },
  );
  test(
    'never combines different courses, sessions, times, campuses or invalid captures',
    () {
      final a = report('first', 'no_campus');
      final bad = <Map<String, Object?>>[
        {...a, 'course_id': 'other'},
        {...a, 'session_id': 'other'},
        {...a, 'starts_at_ms': 0},
        {...a, 'ends_at_ms': 0},
        {...a, 'campus_id': 'other'},
        {...a, 'lesson_count': 4},
        {...a, 'call_count': 1},
        {...a, 'moment': 'wrong'},
        {...a, 'scheduled_at_ms': 'bad'},
      ];
      expect(estimate(bad).firstReason, 'not_scheduled');
      for (final change in [
        {'checkpoint_expected_at_ms': 0},
        {'captured_at_ms': 'bad'},
        {'captured_at_ms': start.millisecondsSinceEpoch},
        {'captured_at_ms': (a['checkpoint_expected_at_ms']! as int) + 300001},
        {'captured_at_ms': session().endsAt.millisecondsSinceEpoch},
      ]) {
        expect(
          estimate([
            {...a, ...change},
          ]).firstReason,
          'invalid_capture_time',
        );
      }
      expect(
        estimate([
          {...a, 'first_ping': 'invalid'},
        ]).firstReason,
        'invalid_ping',
      );
      final legacy = {...a}..remove('moment');
      expect(estimate([legacy]).first, EstadoPing.onCampus);
    },
  );
  test(
    'a missing moment resolves only after its window; captures after class end are invalid',
    () {
      final end = session().endsAt;
      expect(estimate([], now: start).complete, false);
      expect(estimate([], now: end).complete, true);
      expect(
        estimate([
          report('first', 'no_campus'),
        ], now: start.add(const Duration(minutes: 86))).complete,
        true,
      );
      expect(
        estimate([
          report('first', 'no_campus'),
        ], now: start.add(const Duration(minutes: 84))).complete,
        false,
      );
      expect(
        estimate([
          report('second', 'no_campus'),
        ], now: start.add(const Duration(minutes: 26))).complete,
        true,
      );
      final short = SessionRecord(
        id: 's',
        startsAt: start,
        endsAt: start.add(const Duration(minutes: 22)),
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.two,
        createdAt: start,
        updatedAt: start,
      );
      final a = {
        ...report('first', 'no_campus'),
        'ends_at_ms': short.endsAt.millisecondsSinceEpoch,
        'captured_at_ms': short.endsAt.millisecondsSinceEpoch,
      };
      expect(estimate([a], s: short).firstReason, 'invalid_capture_time');
    },
  );
  test(
    'preserves saved state; cancelled sessions have no automatic classification',
    () {
      for (final s in [
        session(saved: SituacaoFrequencia.absent),
        session(first: EstadoPing.away),
        session(second: EstadoPing.away),
      ]) {
        final before = s.toFirestore();
        final r = estimate([
          report('first', 'no_campus'),
          report('second', 'no_campus'),
        ], s: s);
        expect(r.preservesExistingRecord, true);
        expect(s.toFirestore(), before);
      }
      final r = estimate([
        report('first', 'no_campus'),
        report('second', 'no_campus'),
      ], s: session(calendar: SessionCalendarStatus.cancelled));
      expect(r.status, SituacaoFrequencia.pending);
      expect(r.absences, isNull);
    },
  );
}
