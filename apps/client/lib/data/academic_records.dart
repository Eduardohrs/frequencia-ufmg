import 'package:cloud_firestore/cloud_firestore.dart';

import '../domain/attendance.dart';
import 'firestore_schema.dart';

final class CourseRecord {
  const CourseRecord({
    required this.id,
    required this.code,
    required this.name,
    required this.workload,
    required this.term,
    required this.createdAt,
    required this.updatedAt,
  });

  factory CourseRecord.fromFirestore(String id, Map<String, Object?> data) {
    FirestoreSchema.validateCourse(data);
    return CourseRecord(
      id: id,
      code: data['code']! as String,
      name: data['name']! as String,
      workload: data['workload']! as int,
      term: data['term']! as String,
      createdAt: _date(data, 'createdAt'),
      updatedAt: _date(data, 'updatedAt'),
    );
  }

  final String id;
  final String code;
  final String name;
  final int workload;
  final String term;
  final DateTime createdAt;
  final DateTime updatedAt;

  Map<String, Object?> toFirestore() {
    final data = <String, Object?>{
      'schemaVersion': FirestoreSchema.version,
      'code': code,
      'name': name,
      'workload': workload,
      'term': term,
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
    required this.createdAt,
    required this.updatedAt,
  });

  factory SessionRecord.fromFirestore(String id, Map<String, Object?> data) {
    FirestoreSchema.validateSession(data);
    final firstPing = data['firstPing'] as String?;
    final secondPing = data['secondPing'] as String?;
    final attendanceStatus = data['attendanceStatus'] as String?;
    return SessionRecord(
      id: id,
      startsAt: _date(data, 'startsAt'),
      endsAt: _date(data, 'endsAt'),
      lessonCount: QuantidadeAulas.fromValue(data['lessonCount']! as int),
      callCount: NumeroChamadas.fromValue(data['callCount']! as int),
      firstPing: firstPing == null ? null : EstadoPing.fromCode(firstPing),
      secondPing: secondPing == null ? null : EstadoPing.fromCode(secondPing),
      attendanceStatus: attendanceStatus == null
          ? null
          : SituacaoFrequencia.fromCode(attendanceStatus),
      absences: data['absences'] as int?,
      createdAt: _date(data, 'createdAt'),
      updatedAt: _date(data, 'updatedAt'),
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
      ..._auditFields(createdAt, updatedAt),
    };
    FirestoreSchema.validateSession(data);
    return data;
  }
}

DateTime _date(Map<String, Object?> data, String field) =>
    (data[field]! as Timestamp).toDate().toUtc();

Map<String, Object?> _auditFields(DateTime createdAt, DateTime updatedAt) => {
  'createdAt': Timestamp.fromDate(createdAt.toUtc()),
  'updatedAt': Timestamp.fromDate(updatedAt.toUtc()),
};
