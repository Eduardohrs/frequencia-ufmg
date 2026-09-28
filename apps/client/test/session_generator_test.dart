import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/session_generator.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

void main() {
  tz_data.initializeTimeZones();
  final location = tz.getLocation('America/Sao_Paulo');
  final createdAt = DateTime.utc(2026, 8, 1, 12);

  test('generates recurring sessions in Sao Paulo without duplicates', () {
    final meetings = [
      MeetingRecord(
        id: 'monday-8',
        weekday: DateTime.monday,
        startMinutes: 480,
        endMinutes: 580,
        lessonCount: QuantidadeAulas.two,
        callCount: NumeroChamadas.one,
        createdAt: createdAt,
        updatedAt: createdAt,
      ),
      MeetingRecord(
        id: 'wednesday-14',
        weekday: DateTime.wednesday,
        startMinutes: 840,
        endMinutes: 1040,
        lessonCount: QuantidadeAulas.four,
        callCount: NumeroChamadas.two,
        createdAt: createdAt,
        updatedAt: createdAt,
      ),
    ];
    final existing = SessionRecord(
      id: '2026-08-03--monday-8',
      startsAt: DateTime.utc(2026, 8, 3, 11),
      endsAt: DateTime.utc(2026, 8, 3, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      attendanceStatus: SituacaoFrequencia.present,
      absences: 0,
      createdAt: createdAt,
      updatedAt: createdAt,
    );

    final generated = SessionGenerator(location).generateMissing(
      meetings: meetings,
      existingSessions: [existing],
      startDate: DateTime(2026, 8, 3),
      endDate: DateTime(2026, 8, 16),
      notBefore: tz.TZDateTime(location, 2026, 8, 1),
      now: createdAt,
    );

    expect(generated.map((session) => session.id), [
      '2026-08-05--wednesday-14',
      '2026-08-10--monday-8',
      '2026-08-12--wednesday-14',
    ]);
    expect(generated.first.startsAt, DateTime.utc(2026, 8, 5, 17));
    expect(generated.first.endsAt, DateTime.utc(2026, 8, 5, 20, 20));
    expect(generated.first.lessonCount, QuantidadeAulas.four);
    expect(generated.first.callCount, NumeroChamadas.two);
    expect(generated.first.attendanceStatus, isNull);
    expect(generated.first.absences, isNull);
    expect(generated.first.createdAt, createdAt);
  });

  test('skips sessions before the cutoff and validates the date range', () {
    final meeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: createdAt,
      updatedAt: createdAt,
    );
    final generator = SessionGenerator(location);

    final generated = generator.generateMissing(
      meetings: [meeting],
      existingSessions: const [],
      startDate: DateTime(2026, 8, 3),
      endDate: DateTime(2026, 8, 17),
      notBefore: tz.TZDateTime(location, 2026, 8, 10, 8, 1),
      now: createdAt,
    );

    expect(generated.map((session) => session.id), ['2026-08-17--monday-8']);
    expect(
      () => generator.generateMissing(
        meetings: [meeting],
        existingSessions: const [],
        startDate: DateTime(2026, 8, 4),
        endDate: DateTime(2026, 8, 3),
        notBefore: tz.TZDateTime(location, 2026, 8, 1),
        now: createdAt,
      ),
      throwsArgumentError,
    );
  });

  test('reconciles a moved range without leaving orphan sessions', () {
    final meeting = _meeting('monday-8');
    final october = SessionRecord(
      id: '2026-10-05--monday-8',
      startsAt: DateTime.utc(2026, 10, 5, 11),
      endsAt: DateTime.utc(2026, 10, 5, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: createdAt,
      updatedAt: createdAt,
    );

    final result = SessionGenerator(location).reconcile(
      meetings: [meeting],
      existingSessions: [october],
      startDate: DateTime(2026, 11, 1),
      endDate: DateTime(2026, 11, 9),
      now: createdAt,
    );

    expect(result.deleteIds, ['2026-10-05--monday-8']);
    expect(result.upserts.map((item) => item.id), [
      '2026-11-02--monday-8',
      '2026-11-09--monday-8',
    ]);
    expect(result.destructiveDeleteCount, 0);
  });

  test('reconciles sessions retroactively from the beginning of the term', () {
    final result = SessionGenerator(location).reconcile(
      meetings: [_meeting('monday-8')],
      existingSessions: const [],
      startDate: DateTime(2026, 8, 3),
      endDate: DateTime(2026, 8, 17),
      now: DateTime.utc(2026, 9, 28, 12),
    );

    expect(result.upserts.map((session) => session.id), [
      '2026-08-03--monday-8',
      '2026-08-10--monday-8',
      '2026-08-17--monday-8',
    ]);
  });

  test('preserves makeups and identifies removed attendance evidence', () {
    final meeting = _meeting('monday-8');
    final recorded = SessionRecord(
      id: '2026-10-05--monday-8',
      startsAt: DateTime.utc(2026, 10, 5, 11),
      endsAt: DateTime.utc(2026, 10, 5, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      attendanceStatus: SituacaoFrequencia.absent,
      absences: 2,
      createdAt: createdAt,
      updatedAt: createdAt,
    );
    final makeup = SessionRecord(
      id: 'makeup-1',
      startsAt: DateTime.utc(2026, 10, 6, 11),
      endsAt: DateTime.utc(2026, 10, 6, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      calendarStatus: SessionCalendarStatus.makeup,
      createdAt: createdAt,
      updatedAt: createdAt,
    );

    final result = SessionGenerator(location).reconcile(
      meetings: [meeting],
      existingSessions: [recorded, makeup],
      startDate: DateTime(2026, 11, 2),
      endDate: DateTime(2026, 11, 2),
      now: createdAt,
    );

    expect(result.deleteIds, ['2026-10-05--monday-8']);
    expect(result.destructiveDeleteCount, 1);
    expect(result.deleteIds, isNot(contains('makeup-1')));
  });

  test('updates unrecorded sessions but preserves evidence and exceptions', () {
    final changedMeeting = MeetingRecord(
      id: 'monday-8',
      weekday: DateTime.monday,
      startMinutes: 600,
      endMinutes: 800,
      lessonCount: QuantidadeAulas.four,
      callCount: NumeroChamadas.two,
      createdAt: createdAt,
      updatedAt: createdAt,
    );
    final holiday = SessionRecord(
      id: '2026-10-05--monday-8',
      startsAt: DateTime.utc(2026, 10, 5, 11),
      endsAt: DateTime.utc(2026, 10, 5, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      calendarStatus: SessionCalendarStatus.holiday,
      createdAt: createdAt,
      updatedAt: createdAt,
    );
    final recorded = SessionRecord(
      id: '2026-10-12--monday-8',
      startsAt: DateTime.utc(2026, 10, 12, 11),
      endsAt: DateTime.utc(2026, 10, 12, 12, 40),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      firstPing: EstadoPing.onCampus,
      attendanceStatus: SituacaoFrequencia.present,
      absences: 0,
      createdAt: createdAt,
      updatedAt: createdAt,
    );

    final result = SessionGenerator(location).reconcile(
      meetings: [changedMeeting],
      existingSessions: [holiday, recorded],
      startDate: DateTime(2026, 10, 5),
      endDate: DateTime(2026, 10, 12),
      now: createdAt.add(const Duration(days: 1)),
    );

    expect(result.deleteIds, isEmpty);
    expect(result.upserts, hasLength(1));
    expect(result.upserts.single.id, holiday.id);
    expect(result.upserts.single.startsAt, DateTime.utc(2026, 10, 5, 13));
    expect(result.upserts.single.lessonCount, QuantidadeAulas.four);
    expect(result.upserts.single.calendarStatus, SessionCalendarStatus.holiday);
    expect(result.upserts.single.createdAt, createdAt);
    expect(
      result.upserts.single.updatedAt,
      createdAt.add(const Duration(days: 1)),
    );
    expect(result.upserts.map((item) => item.id), isNot(contains(recorded.id)));
  });

  test('detects every changed generated-session field', () {
    final generator = SessionGenerator(location);
    final meeting = _meeting('monday-8');
    final desired = generator
        .reconcile(
          meetings: [meeting],
          existingSessions: const [],
          startDate: DateTime(2026, 10, 5),
          endDate: DateTime(2026, 10, 19),
          now: createdAt,
        )
        .upserts;
    SessionRecord changed(
      SessionRecord source, {
      DateTime? endsAt,
      QuantidadeAulas? lessonCount,
      NumeroChamadas? callCount,
    }) => SessionRecord(
      id: source.id,
      startsAt: source.startsAt,
      endsAt: endsAt ?? source.endsAt,
      lessonCount: lessonCount ?? source.lessonCount,
      callCount: callCount ?? source.callCount,
      createdAt: source.createdAt,
      updatedAt: source.updatedAt,
    );

    final result = generator.reconcile(
      meetings: [meeting],
      existingSessions: [
        changed(
          desired[0],
          endsAt: desired[0].endsAt.add(const Duration(minutes: 1)),
        ),
        changed(desired[1], lessonCount: QuantidadeAulas.four),
        changed(desired[2], callCount: NumeroChamadas.two),
      ],
      startDate: DateTime(2026, 10, 5),
      endDate: DateTime(2026, 10, 19),
      now: createdAt,
    );

    expect(result.upserts, hasLength(3));
  });
}

MeetingRecord _meeting(String id) => MeetingRecord(
  id: id,
  weekday: DateTime.monday,
  startMinutes: 480,
  endMinutes: 580,
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  createdAt: DateTime.utc(2026, 8, 1, 12),
  updatedAt: DateTime.utc(2026, 8, 1, 12),
);
