import 'dart:async';
import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';

import '../observability/app_logger.dart';
import 'academic_records.dart';
import 'firestore_schema.dart';
import 'python_overview_repository.dart';

typedef CurrentOverviewUserId = String? Function();

abstract interface class AcademicOverviewCache {
  Future<String?> read(String userId);

  Future<void> write(String userId, String value);

  Future<void> remove(String userId);
}

final class CachedAcademicOverviewRepository
    implements AcademicOverviewRepository {
  const CachedAcademicOverviewRepository({
    required this.remote,
    required this.cache,
    required this.currentUserId,
    required this.logger,
  });

  final AcademicOverviewRepository remote;
  final AcademicOverviewCache cache;
  final CurrentOverviewUserId currentUserId;
  final AppLogger logger;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() async {
    try {
      final snapshot = await remote.loadOverview();
      final userId = currentUserId();
      if (userId != null) {
        try {
          await cache.write(userId, _encode(snapshot));
          _event('academic_overview_cache_write_succeeded');
        } catch (error, stackTrace) {
          _error(error, stackTrace, 'academic_overview_cache_write');
        }
      }
      return snapshot;
    } catch (remoteError, remoteStackTrace) {
      final userId = currentUserId();
      if (userId == null) rethrow;

      late final String? encoded;
      try {
        encoded = await cache.read(userId);
      } catch (error, stackTrace) {
        _error(error, stackTrace, 'academic_overview_cache_read');
        Error.throwWithStackTrace(remoteError, remoteStackTrace);
      }
      if (encoded == null) {
        _event('academic_overview_cache_miss');
        Error.throwWithStackTrace(remoteError, remoteStackTrace);
      }
      try {
        final snapshot = _decode(encoded);
        _event('academic_overview_cache_hit');
        return snapshot;
      } catch (error, stackTrace) {
        _error(error, stackTrace, 'academic_overview_cache_decode');
        try {
          await cache.remove(userId);
        } catch (removeError, removeStackTrace) {
          _error(
            removeError,
            removeStackTrace,
            'academic_overview_cache_remove',
          );
        }
        Error.throwWithStackTrace(remoteError, remoteStackTrace);
      }
    }
  }

  void _event(String name) =>
      unawaited(logger.logEvent(name).catchError((Object _) {}));

  void _error(Object error, StackTrace stackTrace, String context) => unawaited(
    logger
        .recordError(error, stackTrace, context: context)
        .catchError((Object _) {}),
  );
}

String _encode(AcademicOverviewSnapshot snapshot) => jsonEncode({
  'version': 1,
  'courses': [for (final course in snapshot.courses) _courseJson(course)],
  'sessions_by_course': {
    for (final entry in snapshot.sessionsByCourse.entries)
      entry.key: [for (final session in entry.value) _sessionJson(session)],
  },
});

AcademicOverviewSnapshot _decode(String encoded) {
  final root = _map(jsonDecode(encoded));
  if (root.keys.toSet().difference({
        'version',
        'courses',
        'sessions_by_course',
      }).isNotEmpty ||
      root['version'] != 1) {
    throw const FormatException();
  }
  final courses = _list(root['courses']).map(_course).toList(growable: false);
  final courseIds = {for (final course in courses) course.id};
  final rawSessions = _map(root['sessions_by_course']);
  if (rawSessions.keys.any((courseId) => !courseIds.contains(courseId))) {
    throw const FormatException();
  }
  return AcademicOverviewSnapshot(
    courses: courses,
    sessionsByCourse: {
      for (final course in courses)
        course.id: _list(
          rawSessions[course.id],
        ).map(_session).toList(growable: false),
    },
    isLocalCopy: true,
  );
}

Map<String, Object?> _courseJson(CourseRecord course) => {
  'id': course.id,
  'code': course.code,
  'name': course.name,
  'workload': course.workload,
  'term': course.term,
  'starts_on': course.startsOn?.toUtc().toIso8601String(),
  'ends_on': course.endsOn?.toUtc().toIso8601String(),
  'created_at': course.createdAt.toUtc().toIso8601String(),
  'updated_at': course.updatedAt.toUtc().toIso8601String(),
};

Map<String, Object?> _sessionJson(SessionRecord session) => {
  'id': session.id,
  'starts_at': session.startsAt.toUtc().toIso8601String(),
  'ends_at': session.endsAt.toUtc().toIso8601String(),
  'lesson_count': session.lessonCount.value,
  'call_count': session.callCount.value,
  'first_ping': session.firstPing?.code,
  'second_ping': session.secondPing?.code,
  'attendance_status': session.attendanceStatus?.code,
  'absences': session.absences,
  'calendar_status': session.calendarStatus.code,
  'assessment_title': session.assessmentTitle,
  'created_at': session.createdAt.toUtc().toIso8601String(),
  'updated_at': session.updatedAt.toUtc().toIso8601String(),
};

CourseRecord _course(Object? value) {
  final json = _map(value);
  final id = _string(json['id']);
  return CourseRecord.fromFirestore(id, {
    'schemaVersion': FirestoreSchema.version,
    'code': _string(json['code']),
    'name': _string(json['name']),
    'workload': _integer(json['workload']),
    'term': _string(json['term']),
    'startsOn': _nullableTimestamp(json['starts_on']),
    'endsOn': _nullableTimestamp(json['ends_on']),
    'createdAt': _timestamp(json['created_at']),
    'updatedAt': _timestamp(json['updated_at']),
  });
}

SessionRecord _session(Object? value) {
  final json = _map(value);
  final id = _string(json['id']);
  return SessionRecord.fromFirestore(id, {
    'schemaVersion': FirestoreSchema.version,
    'startsAt': _timestamp(json['starts_at']),
    'endsAt': _timestamp(json['ends_at']),
    'lessonCount': _integer(json['lesson_count']),
    'callCount': _integer(json['call_count']),
    'firstPing': _nullableString(json['first_ping']),
    'secondPing': _nullableString(json['second_ping']),
    'attendanceStatus': _nullableString(json['attendance_status']),
    'absences': _nullableInteger(json['absences']),
    'calendarStatus': _string(json['calendar_status']),
    'assessmentTitle': _nullableString(json['assessment_title']),
    'createdAt': _timestamp(json['created_at']),
    'updatedAt': _timestamp(json['updated_at']),
  });
}

Map<String, Object?> _map(Object? value) {
  if (value is! Map) throw const FormatException();
  return Map<String, Object?>.from(value);
}

List<Object?> _list(Object? value) {
  if (value is! List) throw const FormatException();
  return List<Object?>.from(value);
}

String _string(Object? value) {
  if (value is! String) throw const FormatException();
  return value;
}

String? _nullableString(Object? value) => value == null ? null : _string(value);

int _integer(Object? value) {
  if (value is! int) throw const FormatException();
  return value;
}

int? _nullableInteger(Object? value) => value == null ? null : _integer(value);

Timestamp _timestamp(Object? value) {
  final encoded = _string(value);
  final parsed = DateTime.tryParse(encoded);
  if (parsed == null || !encoded.endsWith('Z')) throw const FormatException();
  return Timestamp.fromDate(parsed.toUtc());
}

Timestamp? _nullableTimestamp(Object? value) =>
    value == null ? null : _timestamp(value);
