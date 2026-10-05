import 'package:cloud_firestore/cloud_firestore.dart';

import '../domain/attendance.dart';
import 'calendar_status.dart';
import 'firestore_schema.dart';

final class CourseRecord {
  const CourseRecord({
    required this.id,
    required this.code,
    required this.name,
    required this.workload,
    required this.term,
    this.startsOn,
    this.endsOn,
    required this.createdAt,
    required this.updatedAt,
  });

  factory CourseRecord.fromFirestore(String id, Map<String, Object?> data) {
    final normalized = {
      ...data,
      'startsOn': data['startsOn'],
      'endsOn': data['endsOn'],
    };
    FirestoreSchema.validateCourse(normalized);
    return CourseRecord(
      id: id,
      code: normalized['code']! as String,
      name: normalized['name']! as String,
      workload: normalized['workload']! as int,
      term: normalized['term']! as String,
      startsOn: _nullableDate(normalized, 'startsOn'),
      endsOn: _nullableDate(normalized, 'endsOn'),
      createdAt: _date(normalized, 'createdAt'),
      updatedAt: _date(normalized, 'updatedAt'),
    );
  }

  final String id;
  final String code;
  final String name;
  final int workload;
  final String term;
  final DateTime? startsOn;
  final DateTime? endsOn;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toFirestore() {
    final data = <String, Object?>{
      'schemaVersion': FirestoreSchema.version,
      'code': code,
      'name': name,
      'workload': workload,
      'term': term,
      'startsOn': startsOn == null
          ? null
          : Timestamp.fromDate(startsOn!.toUtc()),
      'endsOn': endsOn == null ? null : Timestamp.fromDate(endsOn!.toUtc()),
      ..._auditFields(createdAt, updatedAt),
    };
    FirestoreSchema.validateCourse(data);
    return data;
  }
}

final class MeetingRecord {
  const MeetingRecord({
    required this.id,
    required this.weekday,
    required this.startMinutes,
    required this.endMinutes,
    required this.lessonCount,
    required this.callCount,
    required this.createdAt,
    required this.updatedAt,
  });

  factory MeetingRecord.fromFirestore(String id, Map<String, Object?> data) {
    FirestoreSchema.validateMeeting(data);
    return MeetingRecord(
      id: id,
      weekday: data['weekday']! as int,
      startMinutes: data['startMinutes']! as int,
      endMinutes: data['endMinutes']! as int,
      lessonCount: QuantidadeAulas.fromValue(data['lessonCount']! as int),
      callCount: NumeroChamadas.fromValue(data['callCount']! as int),
      createdAt: _date(data, 'createdAt'),
      updatedAt: _date(data, 'updatedAt'),
    );
  }

  final String id;
  final int weekday;
  final int startMinutes;
  final int endMinutes;
  final QuantidadeAulas lessonCount;
  final NumeroChamadas callCount;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toFirestore() {
    final data = <String, Object?>{
      'schemaVersion': FirestoreSchema.version,
      'weekday': weekday,
      'startMinutes': startMinutes,
      'endMinutes': endMinutes,
      'lessonCount': lessonCount.value,
      'callCount': callCount.value,
      ..._auditFields(createdAt, updatedAt),
    };
    FirestoreSchema.validateMeeting(data);
    return data;
  }
}

final class SessionRecord {
  const SessionRecord({
    required this.id,
    required this.startsAt,
    required this.endsAt,
    required this.lessonCount,
    required this.callCount,
    this.firstPing,
    this.secondPing,
    this.attendanceStatus,
    this.absences,
    this.calendarStatus = SessionCalendarStatus.scheduled,
    this.assessmentTitle,
    required this.createdAt,
    required this.updatedAt,
  });

  factory SessionRecord.fromFirestore(String id, Map<String, Object?> data) {
    final normalized = {
      ...data,
      'calendarStatus': data['calendarStatus'] ?? 'scheduled',
      'assessmentTitle': data['assessmentTitle'],
    };
    FirestoreSchema.validateSession(normalized);
    final firstPing = normalized['firstPing'] as String?;
    final secondPing = normalized['secondPing'] as String?;
    final attendanceStatus = normalized['attendanceStatus'] as String?;
    return SessionRecord(
      id: id,
      startsAt: _date(normalized, 'startsAt'),
      endsAt: _date(normalized, 'endsAt'),
      lessonCount: QuantidadeAulas.fromValue(normalized['lessonCount']! as int),
      callCount: NumeroChamadas.fromValue(normalized['callCount']! as int),
      firstPing: firstPing == null ? null : EstadoPing.fromCode(firstPing),
      secondPing: secondPing == null ? null : EstadoPing.fromCode(secondPing),
      attendanceStatus: attendanceStatus == null
          ? null
          : SituacaoFrequencia.fromCode(attendanceStatus),
      absences: normalized['absences'] as int?,
      calendarStatus: SessionCalendarStatus.fromCode(
        normalized['calendarStatus']! as String,
      ),
      assessmentTitle: normalized['assessmentTitle'] as String?,
      createdAt: _date(normalized, 'createdAt'),
      updatedAt: _date(normalized, 'updatedAt'),
    );
  }

  final String id;
  final DateTime startsAt;
  final DateTime endsAt;
  final QuantidadeAulas lessonCount;
  final NumeroChamadas callCount;
  final EstadoPing? firstPing;
  final EstadoPing? secondPing;
  final SituacaoFrequencia? attendanceStatus;
  final int? absences;
  final SessionCalendarStatus calendarStatus;
  final String? assessmentTitle;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toFirestore() {
    final data = <String, Object?>{
      'schemaVersion': FirestoreSchema.version,
      'startsAt': Timestamp.fromDate(startsAt.toUtc()),
      'endsAt': Timestamp.fromDate(endsAt.toUtc()),
      'lessonCount': lessonCount.value,
      'callCount': callCount.value,
      'firstPing': firstPing?.code,
      'secondPing': secondPing?.code,
      'attendanceStatus': attendanceStatus?.code,
      'absences': absences,
      'calendarStatus': calendarStatus.code,
      'assessmentTitle': assessmentTitle,
      ..._auditFields(createdAt, updatedAt),
    };
    FirestoreSchema.validateSession(data);
    return data;
  }
}

DateTime _date(Map<String, Object?> data, String field) =>
    (data[field]! as Timestamp).toDate().toUtc();

DateTime? _nullableDate(Map<String, Object?> data, String field) =>
    (data[field] as Timestamp?)?.toDate().toUtc();

Map<String, Object?> _auditFields(DateTime createdAt, DateTime updatedAt) => {
  'createdAt': Timestamp.fromDate(createdAt.toUtc()),
  'updatedAt': Timestamp.fromDate(updatedAt.toUtc()),
};
