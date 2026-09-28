import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';

void main() {
  final createdAt = DateTime.utc(2026, 7, 1);
  final updatedAt = DateTime.utc(2026, 7, 2);

  test('course record round-trips through the Firestore schema', () {
    final record = CourseRecord(
      id: 'poo',
      code: 'DCC203',
      name: 'Programacao Orientada a Objetos',
      workload: 60,
      term: '2026-2',
      createdAt: createdAt,
      updatedAt: updatedAt,
    );

    final restored = CourseRecord.fromFirestore(
      record.id,
      record.toFirestore(),
    );

    expect(restored.id, 'poo');
    expect(restored.code, 'DCC203');
    expect(restored.name, 'Programacao Orientada a Objetos');
    expect(restored.workload, 60);
    expect(restored.term, '2026-2');
    expect(restored.createdAt, createdAt);
    expect(restored.updatedAt, updatedAt);
  });

  test('meeting record round-trips with typed lesson and call counts', () {
    final record = MeetingRecord(
      id: 'monday-morning',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );

    final restored = MeetingRecord.fromFirestore(
      record.id,
      record.toFirestore(),
    );

    expect(restored.id, 'monday-morning');
    expect(restored.weekday, DateTime.monday);
    expect(restored.startMinutes, 480);
    expect(restored.endMinutes, 580);
    expect(restored.lessonCount, QuantidadeAulas.two);
    expect(restored.callCount, NumeroChamadas.one);
    expect(restored.createdAt, createdAt);
    expect(restored.updatedAt, updatedAt);
  });

  test('session record round-trips nullable and resolved attendance', () {
    final record = SessionRecord(
      id: '2026-08-03',
      startsAt: DateTime.utc(2026, 8, 3, 8),
      endsAt: DateTime.utc(2026, 8, 3, 10),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.two,
      firstPing: EstadoPing.away,
      secondPing: EstadoPing.onCampus,
      attendanceStatus: SituacaoFrequencia.arrivedLate,
      absences: 1,
      calendarStatus: SessionCalendarStatus.makeup,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );

    final restored = SessionRecord.fromFirestore(
      record.id,
      record.toFirestore(),
    );

    expect(restored.id, '2026-08-03');
    expect(restored.startsAt, DateTime.utc(2026, 8, 3, 8));
    expect(restored.endsAt, DateTime.utc(2026, 8, 3, 10));
    expect(restored.lessonCount, QuantidadeAulas.two);
    expect(restored.callCount, NumeroChamadas.two);
    expect(restored.firstPing, EstadoPing.away);
    expect(restored.secondPing, EstadoPing.onCampus);
    expect(restored.attendanceStatus, SituacaoFrequencia.arrivedLate);
    expect(restored.absences, 1);
    expect(restored.calendarStatus, SessionCalendarStatus.makeup);
    expect(restored.createdAt, createdAt);
    expect(restored.updatedAt, updatedAt);
  });

  test('session record preserves unresolved attendance', () {
    final data = <String, Object?>{
      'schemaVersion': 1,
      'startsAt': Timestamp.fromDate(DateTime.utc(2026, 8, 3, 8)),
      'endsAt': Timestamp.fromDate(DateTime.utc(2026, 8, 3, 10)),
      'lessonCount': 2,
      'callCount': 1,
      'firstPing': null,
      'secondPing': null,
      'attendanceStatus': null,
      'absences': null,
      'calendarStatus': 'scheduled',
      'createdAt': Timestamp.fromDate(createdAt),
      'updatedAt': Timestamp.fromDate(updatedAt),
    };

    final restored = SessionRecord.fromFirestore('session', data);

    expect(restored.firstPing, isNull);
    expect(restored.secondPing, isNull);
    expect(restored.attendanceStatus, isNull);
    expect(restored.absences, isNull);
  });

  test('older sessions default to a scheduled calendar status', () {
    final data = SessionRecord(
      id: 'legacy',
      startsAt: DateTime.utc(2026, 8, 3, 8),
      endsAt: DateTime.utc(2026, 8, 3, 10),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: createdAt,
      updatedAt: updatedAt,
    ).toFirestore()..remove('calendarStatus');

    final restored = SessionRecord.fromFirestore('legacy', data);

    expect(restored.calendarStatus, SessionCalendarStatus.scheduled);
  });

  test('records reject documents outside the declared schema', () {
    expect(
      () => CourseRecord.fromFirestore('course', {
        'schemaVersion': 1,
        'code': 'DCC203',
      }),
      throwsFormatException,
    );
    expect(
      () => SessionRecord.fromFirestore('session', {
        ...SessionRecord(
          id: 'session',
          startsAt: DateTime.utc(2026, 8, 3, 8),
          endsAt: DateTime.utc(2026, 8, 3, 10),
          lessonCount: QuantidadeAulas.two,
          callCount: NumeroChamadas.one,
          createdAt: createdAt,
          updatedAt: updatedAt,
        ).toFirestore(),
        'firstPing': 'invalid',
      }),
      throwsFormatException,
    );
  });
}
