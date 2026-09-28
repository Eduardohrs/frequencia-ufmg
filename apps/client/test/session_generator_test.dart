import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
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
}
