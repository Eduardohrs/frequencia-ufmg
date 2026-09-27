import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/firestore_schema.dart';

void main() {
  group('Firestore paths', () {
    test('keeps every academic document below its authenticated user', () {
      expect(FirestoreSchema.userDocument('user-1'), 'users/user-1');
      expect(
        FirestoreSchema.coursesCollection('user-1'),
        'users/user-1/courses',
      );
      expect(
        FirestoreSchema.courseDocument('user-1', 'course-1'),
        'users/user-1/courses/course-1',
      );
      expect(
        FirestoreSchema.meetingsCollection('user-1', 'course-1'),
        'users/user-1/courses/course-1/meetings',
      );
      expect(
        FirestoreSchema.meetingDocument('user-1', 'course-1', 'meeting-1'),
        'users/user-1/courses/course-1/meetings/meeting-1',
      );
      expect(
        FirestoreSchema.sessionsCollection('user-1', 'course-1'),
        'users/user-1/courses/course-1/sessions',
      );
      expect(
        FirestoreSchema.sessionDocument('user-1', 'course-1', 'session-1'),
        'users/user-1/courses/course-1/sessions/session-1',
      );
    });

    test('rejects empty or path-breaking identifiers', () {
      for (final invalid in ['', '   ', 'user/other']) {
        expect(
          () => FirestoreSchema.courseDocument(invalid, 'course-1'),
          throwsArgumentError,
        );
        expect(
          () => FirestoreSchema.courseDocument('user-1', invalid),
          throwsArgumentError,
        );
        expect(
          () => FirestoreSchema.meetingDocument('user-1', 'course-1', invalid),
          throwsArgumentError,
        );
        expect(
          () => FirestoreSchema.sessionDocument('user-1', 'course-1', invalid),
          throwsArgumentError,
        );
      }
    });
  });

  group('Firestore document shapes', () {
    test('defines versioned course, meeting, and session fields', () {
      expect(FirestoreSchema.version, 1);
      expect(FirestoreSchema.course.fields, {
        'schemaVersion': FirestoreFieldType.integer,
        'code': FirestoreFieldType.string,
        'name': FirestoreFieldType.string,
        'workload': FirestoreFieldType.integer,
        'term': FirestoreFieldType.string,
        'createdAt': FirestoreFieldType.timestamp,
        'updatedAt': FirestoreFieldType.timestamp,
      });
      expect(FirestoreSchema.meeting.fields, {
        'schemaVersion': FirestoreFieldType.integer,
        'weekday': FirestoreFieldType.integer,
        'startMinutes': FirestoreFieldType.integer,
        'endMinutes': FirestoreFieldType.integer,
        'lessonCount': FirestoreFieldType.integer,
        'callCount': FirestoreFieldType.integer,
        'createdAt': FirestoreFieldType.timestamp,
        'updatedAt': FirestoreFieldType.timestamp,
      });
      expect(FirestoreSchema.session.fields, {
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
    });

    test('accepts complete maps with the declared field types', () {
      final timestamp = Timestamp.fromDate(DateTime.utc(2026, 8, 3, 9));

      expect(
        () => FirestoreSchema.course.validateShape({
          'schemaVersion': 1,
          'code': 'DCC203',
          'name': 'POO',
          'workload': 60,
          'term': '2026-2',
          'createdAt': timestamp,
          'updatedAt': timestamp,
        }),
        returnsNormally,
      );
      expect(
        () => FirestoreSchema.meeting.validateShape({
          'schemaVersion': 1,
          'weekday': 1,
          'startMinutes': 480,
          'endMinutes': 580,
          'lessonCount': 2,
          'callCount': 1,
          'createdAt': timestamp,
          'updatedAt': timestamp,
        }),
        returnsNormally,
      );
      expect(
        () => FirestoreSchema.session.validateShape({
          'schemaVersion': 1,
          'startsAt': timestamp,
          'endsAt': timestamp,
          'lessonCount': 2,
          'callCount': 1,
          'firstPing': null,
          'secondPing': 'no_campus',
          'attendanceStatus': null,
          'absences': null,
          'createdAt': timestamp,
          'updatedAt': timestamp,
        }),
        returnsNormally,
      );
    });

    test('rejects missing, extra, mistyped, or outdated fields', () {
      final valid = <String, Object?>{
        'schemaVersion': 1,
        'code': 'DCC203',
        'name': 'POO',
        'workload': 60,
        'term': '2026-2',
        'createdAt': Timestamp.now(),
        'updatedAt': Timestamp.now(),
      };

      expect(
        () => FirestoreSchema.course.validateShape({...valid}..remove('code')),
        throwsFormatException,
      );
      expect(
        () => FirestoreSchema.course.validateShape({...valid, 'ownerId': 'x'}),
        throwsFormatException,
      );
      expect(
        () =>
            FirestoreSchema.course.validateShape({...valid, 'workload': '60'}),
        throwsFormatException,
      );
      expect(
        () => FirestoreSchema.course.validateShape({
          ...valid,
          'schemaVersion': 2,
        }),
        throwsFormatException,
      );
    });

    test(
      'does not define PII, ownership duplication, or raw location fields',
      () {
        final fields = {
          ...FirestoreSchema.course.fields.keys,
          ...FirestoreSchema.meeting.fields.keys,
          ...FirestoreSchema.session.fields.keys,
        };

        expect(
          fields.intersection({
            'ownerId',
            'email',
            'displayName',
            'latitude',
            'longitude',
            'location',
          }),
          isEmpty,
        );
      },
    );
  });
}
