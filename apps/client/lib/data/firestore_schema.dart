import 'package:cloud_firestore/cloud_firestore.dart';

enum FirestoreFieldType {
  integer,
  string,
  timestamp,
  nullableInteger,
  nullableString;

  bool accepts(Object? value) => switch (this) {
    FirestoreFieldType.integer => value is int,
    FirestoreFieldType.string => value is String,
    FirestoreFieldType.timestamp => value is Timestamp,
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
    'createdAt': FirestoreFieldType.timestamp,
    'updatedAt': FirestoreFieldType.timestamp,
  });

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
    if (value.isEmpty || value.trim() != value || value.contains('/')) {
      throw ArgumentError.value(value, field, 'invalid Firestore path segment');
    }
    return value;
  }
}
