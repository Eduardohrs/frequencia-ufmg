import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';

import 'calendar_status.dart';

enum FirestoreFieldType {
  integer,
  string,
  timestamp,
  nullableTimestamp,
  nullableInteger,
  nullableString;

  bool accepts(Object? value) => switch (this) {
    FirestoreFieldType.integer => value is int,
    FirestoreFieldType.string => value is String,
    FirestoreFieldType.timestamp => value is Timestamp,
    FirestoreFieldType.nullableTimestamp => value == null || value is Timestamp,
    FirestoreFieldType.nullableInteger => value == null || value is int,
    FirestoreFieldType.nullableString => value == null || value is String,
  };
}

final class FirestoreDocumentSchema {
  const FirestoreDocumentSchema(this.fields);

  final Map<String, FirestoreFieldType> fields;

  void validateShape(Map<String, Object?> document) {
    final hasExactFields =
        document.length == fields.length &&
        fields.keys.every(document.containsKey);
    if (!hasExactFields) {
      throw const FormatException('document fields do not match the schema');
    }
    for (final field in fields.entries) {
      if (!field.value.accepts(document[field.key])) {
        throw FormatException('${field.key} has an invalid type');
      }
    }
    if (document['schemaVersion'] != FirestoreSchema.version) {
      throw const FormatException('unsupported schema version');
    }
  }
}

abstract final class FirestoreSchema {
  static const version = 1;

  static const course = FirestoreDocumentSchema({
    'schemaVersion': FirestoreFieldType.integer,
    'code': FirestoreFieldType.string,
    'name': FirestoreFieldType.string,
    'workload': FirestoreFieldType.integer,
    'term': FirestoreFieldType.string,
    'startsOn': FirestoreFieldType.nullableTimestamp,
    'endsOn': FirestoreFieldType.nullableTimestamp,
    'createdAt': FirestoreFieldType.timestamp,
    'updatedAt': FirestoreFieldType.timestamp,
  });

  static const meeting = FirestoreDocumentSchema({
    'schemaVersion': FirestoreFieldType.integer,
    'weekday': FirestoreFieldType.integer,
    'startMinutes': FirestoreFieldType.integer,
    'endMinutes': FirestoreFieldType.integer,
    'lessonCount': FirestoreFieldType.integer,
    'callCount': FirestoreFieldType.integer,
    'createdAt': FirestoreFieldType.timestamp,
    'updatedAt': FirestoreFieldType.timestamp,
  });

  static const session = FirestoreDocumentSchema({
    'schemaVersion': FirestoreFieldType.integer,
    'startsAt': FirestoreFieldType.timestamp,
    'endsAt': FirestoreFieldType.timestamp,
    'lessonCount': FirestoreFieldType.integer,
    'callCount': FirestoreFieldType.integer,
    'firstPing': FirestoreFieldType.nullableString,
    'secondPing': FirestoreFieldType.nullableString,
    'attendanceStatus': FirestoreFieldType.nullableString,
    'absences': FirestoreFieldType.nullableInteger,
    'calendarStatus': FirestoreFieldType.string,
    'assessmentTitle': FirestoreFieldType.nullableString,
    'createdAt': FirestoreFieldType.timestamp,
    'updatedAt': FirestoreFieldType.timestamp,
  });

  static void validateCourse(Map<String, Object?> document) {
    course.validateShape(document);
    _validateText(document['code']! as String, 'code', 32);
    _validateText(document['name']! as String, 'name', 160);
    if (!RegExp(r'^\d{4}-[12]$').hasMatch(document['term']! as String)) {
      throw const FormatException('term must use YYYY-S format');
    }
    if ((document['workload']! as int) <= 0) {
      throw const FormatException('workload must be positive');
    }
    final startsOn = document['startsOn'] as Timestamp?;
    final endsOn = document['endsOn'] as Timestamp?;
    if ((startsOn == null) != (endsOn == null)) {
      throw const FormatException('course date range must be complete');
    }
    if (startsOn != null && endsOn!.toDate().isBefore(startsOn.toDate())) {
      throw const FormatException('course end date cannot precede start date');
    }
    _validateAuditTimestamps(document);
  }

  static void validateMeeting(Map<String, Object?> document) {
    meeting.validateShape(document);
    final weekday = document['weekday']! as int;
    if (weekday < DateTime.monday || weekday > DateTime.sunday) {
      throw const FormatException('weekday must be between 1 and 7');
    }
    final startMinutes = document['startMinutes']! as int;
    final endMinutes = document['endMinutes']! as int;
    if (startMinutes < 0 || endMinutes > 1440 || startMinutes >= endMinutes) {
      throw const FormatException('meeting minutes are invalid');
    }
    _validateConfiguration(document);
    _validateAuditTimestamps(document);
  }

  static void validateSession(Map<String, Object?> document) {
    session.validateShape(document);
    final startsAt = document['startsAt']! as Timestamp;
    final endsAt = document['endsAt']! as Timestamp;
    if (!startsAt.toDate().isBefore(endsAt.toDate())) {
      throw const FormatException('session end must follow its start');
    }
    _validateConfiguration(document);
    _validatePing(document['firstPing'] as String?);
    _validatePing(document['secondPing'] as String?);

    final statusCode = document['attendanceStatus'] as String?;
    final status = statusCode == null ? null : _attendanceStatus(statusCode);
    final absences = document['absences'] as int?;
    try {
      SessionCalendarStatus.fromCode(document['calendarStatus']! as String);
    } on ArgumentError {
      throw const FormatException('calendar status is invalid');
    }
    final assessmentTitle = document['assessmentTitle'] as String?;
    if (assessmentTitle != null) {
      _validateText(assessmentTitle, 'assessmentTitle', 120);
    }
    if (status == null || status == SituacaoFrequencia.pending) {
      if (absences != null) {
        throw const FormatException(
          'unresolved attendance cannot have absences',
        );
      }
    } else {
      final lessonCount = document['lessonCount']! as int;
      if (absences == null || absences < 0 || absences > lessonCount) {
        throw const FormatException('resolved attendance has invalid absences');
      }
    }
    _validateAuditTimestamps(document);
  }

  static String userDocument(String userId) =>
      'users/${_segment(userId, 'userId')}';

  static String coursesCollection(String userId) =>
      '${userDocument(userId)}/courses';

  static String courseDocument(String userId, String courseId) =>
      '${coursesCollection(userId)}/${_segment(courseId, 'courseId')}';

  static String meetingsCollection(String userId, String courseId) =>
      '${courseDocument(userId, courseId)}/meetings';

  static String meetingDocument(
    String userId,
    String courseId,
    String meetingId,
  ) =>
      '${meetingsCollection(userId, courseId)}/${_segment(meetingId, 'meetingId')}';

  static String sessionsCollection(String userId, String courseId) =>
      '${courseDocument(userId, courseId)}/sessions';

  static String sessionDocument(
    String userId,
    String courseId,
    String sessionId,
  ) =>
      '${sessionsCollection(userId, courseId)}/${_segment(sessionId, 'sessionId')}';

  static String _segment(String value, String field) {
    if (value.isEmpty ||
        value.length > 128 ||
        value.trim() != value ||
        value.contains('/')) {
      throw ArgumentError.value(value, field, 'invalid Firestore path segment');
    }
    return value;
  }

  static void _validateText(String value, String field, int maxLength) {
    if (value.trim() != value || value.isEmpty || value.length > maxLength) {
      throw FormatException('$field is invalid');
    }
  }

  static void _validateConfiguration(Map<String, Object?> document) {
    try {
      ConfiguracaoSessao(
        aulas: QuantidadeAulas.fromValue(document['lessonCount']! as int),
        chamadas: NumeroChamadas.fromValue(document['callCount']! as int),
      );
    } on ArgumentError {
      throw const FormatException('session configuration is invalid');
    }
  }

  static void _validatePing(String? code) {
    if (code == null) return;
    try {
      EstadoPing.fromCode(code);
    } on ArgumentError {
      throw const FormatException('ping state is invalid');
    }
  }

  static SituacaoFrequencia _attendanceStatus(String code) {
    try {
      return SituacaoFrequencia.fromCode(code);
    } on ArgumentError {
      throw const FormatException('attendance status is invalid');
    }
  }

  static void _validateAuditTimestamps(Map<String, Object?> document) {
    final createdAt = document['createdAt']! as Timestamp;
    final updatedAt = document['updatedAt']! as Timestamp;
    if (updatedAt.toDate().isBefore(createdAt.toDate())) {
      throw const FormatException('updatedAt cannot precede createdAt');
    }
  }
}
