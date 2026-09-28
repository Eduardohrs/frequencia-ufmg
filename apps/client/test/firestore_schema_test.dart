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
      for (final invalid in ['', '   ', 'user/other', 'x' * 129]) {
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
        'startsOn': FirestoreFieldType.nullableTimestamp,
        'endsOn': FirestoreFieldType.nullableTimestamp,
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
        'calendarStatus': FirestoreFieldType.string,
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
          'startsOn': null,
          'endsOn': null,
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
          'calendarStatus': 'scheduled',
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
        'startsOn': null,
        'endsOn': null,
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

  group('Firestore document semantics', () {
    test('accepts valid course, meeting, and unresolved session data', () {
      expect(
        () => FirestoreSchema.validateCourse(_courseDocument()),
        returnsNormally,
      );
      expect(
        () => FirestoreSchema.validateMeeting(_meetingDocument()),
        returnsNormally,
      );
      expect(
        () => FirestoreSchema.validateSession(_sessionDocument()),
        returnsNormally,
      );
    });

    test('rejects invalid course values and timestamp ordering', () {
      for (final invalid in [
        {..._courseDocument(), 'code': ' '},
        {..._courseDocument(), 'code': 'x' * 33},
        {..._courseDocument(), 'name': ' '},
        {..._courseDocument(), 'name': 'x' * 161},
        {..._courseDocument(), 'term': '2026/2'},
        {..._courseDocument(), 'workload': 0},
        {
          ..._courseDocument(),
          'startsOn': Timestamp.fromDate(DateTime.utc(2026, 8, 1)),
          'endsOn': null,
        },
        {
          ..._courseDocument(),
          'startsOn': Timestamp.fromDate(DateTime.utc(2026, 9, 1)),
          'endsOn': Timestamp.fromDate(DateTime.utc(2026, 8, 1)),
        },
        {
          ..._courseDocument(),
          'updatedAt': Timestamp.fromDate(DateTime.utc(2026, 1, 1)),
        },
      ]) {
        expect(
          () => FirestoreSchema.validateCourse(invalid),
          throwsFormatException,
        );
      }
    });

    test('rejects invalid weekly meeting values', () {
      for (final invalid in [
        {..._meetingDocument(), 'weekday': 0},
        {..._meetingDocument(), 'weekday': 8},
        {..._meetingDocument(), 'startMinutes': -1},
        {..._meetingDocument(), 'endMinutes': 1441},
        {..._meetingDocument(), 'startMinutes': 600, 'endMinutes': 600},
        {..._meetingDocument(), 'lessonCount': 3},
        {..._meetingDocument(), 'lessonCount': 1, 'callCount': 2},
        {
          ..._meetingDocument(),
          'updatedAt': Timestamp.fromDate(DateTime.utc(2026, 1, 1)),
        },
      ]) {
        expect(
          () => FirestoreSchema.validateMeeting(invalid),
          throwsFormatException,
        );
      }
    });

    test('accepts resolved and pending attendance values', () {
      expect(
        () => FirestoreSchema.validateSession({
          ..._sessionDocument(),
          'firstPing': 'fora',
          'secondPing': 'no_campus',
          'attendanceStatus': 'chegou_atrasado',
          'absences': 1,
        }),
        returnsNormally,
      );
      expect(
        () => FirestoreSchema.validateSession({
          ..._sessionDocument(),
          'firstPing': 'indisponivel',
          'secondPing': 'fora',
          'attendanceStatus': 'pendente',
          'absences': null,
        }),
        returnsNormally,
      );
    });

    test('rejects invalid session evidence and attendance values', () {
      for (final invalid in [
        {
          ..._sessionDocument(),
          'endsAt': Timestamp.fromDate(DateTime.utc(2026, 8, 3, 8)),
        },
        {..._sessionDocument(), 'lessonCount': 3},
        {..._sessionDocument(), 'lessonCount': 1, 'callCount': 2},
        {..._sessionDocument(), 'firstPing': 'campus_a'},
        {..._sessionDocument(), 'secondPing': 'unknown'},
        {..._sessionDocument(), 'attendanceStatus': 'unknown'},
        {..._sessionDocument(), 'calendarStatus': 'unknown'},
        {..._sessionDocument(), 'absences': 1},
        {..._sessionDocument(), 'attendanceStatus': 'pendente', 'absences': 0},
        {
          ..._sessionDocument(),
          'attendanceStatus': 'presente',
          'absences': null,
        },
        {..._sessionDocument(), 'attendanceStatus': 'presente', 'absences': -1},
        {..._sessionDocument(), 'attendanceStatus': 'presente', 'absences': 3},
        {
          ..._sessionDocument(),
          'updatedAt': Timestamp.fromDate(DateTime.utc(2026, 1, 1)),
        },
      ]) {
        expect(
          () => FirestoreSchema.validateSession(invalid),
          throwsFormatException,
        );
      }
    });
  });
}

Map<String, Object?> _courseDocument() => {
  'schemaVersion': 1,
  'code': 'DCC203',
  'name': 'Programação Orientada a Objetos',
  'workload': 60,
  'term': '2026-2',
  'startsOn': null,
  'endsOn': null,
  'createdAt': Timestamp.fromDate(DateTime.utc(2026, 7, 1)),
  'updatedAt': Timestamp.fromDate(DateTime.utc(2026, 7, 2)),
};

Map<String, Object?> _meetingDocument() => {
  'schemaVersion': 1,
  'weekday': DateTime.monday,
  'startMinutes': 480,
  'endMinutes': 580,
  'lessonCount': 2,
  'callCount': 1,
  ..._timestamps(),
};

Map<String, Object?> _sessionDocument() => {
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
  ..._timestamps(),
};

Map<String, Object?> _timestamps() => {
  'createdAt': Timestamp.fromDate(DateTime.utc(2026, 7, 1)),
  'updatedAt': Timestamp.fromDate(DateTime.utc(2026, 7, 2)),
};
