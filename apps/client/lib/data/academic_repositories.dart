import '../observability/operation_diagnostics.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../domain/attendance.dart';
import 'academic_records.dart';
import 'calendar_status.dart';
import 'document_store.dart';
import 'firestore_schema.dart';

abstract interface class CourseRepository {
  Future<List<CourseRecord>> listCourses();

  Future<void> saveCourse(CourseRecord course);

  Future<void> deleteCourse(String courseId);
}

abstract interface class MeetingRepository {
  Future<List<MeetingRecord>> listMeetings(String courseId);

  Future<void> saveMeeting(String courseId, MeetingRecord meeting);

  Future<void> deleteMeeting(String courseId, String meetingId);
}

abstract interface class SessionRepository {
  Future<List<SessionRecord>> listSessions(String courseId);

  Future<void> saveSession(String courseId, SessionRecord session);

  Future<void> deleteSession(String courseId, String sessionId);
}

abstract interface class OfflineSessionMutationQueue {
  Future<void> patchAttendance(
    String courseId,
    String sessionId, {
    required SituacaoFrequencia status,
    required int? absences,
    required DateTime updatedAt,
  });

  Future<void> patchCalendarStatus(
    String courseId,
    String sessionId, {
    required SessionCalendarStatus status,
    required DateTime updatedAt,
  });
}

final class FirestoreCourseRepository implements CourseRepository {
  FirestoreCourseRepository({
    required String userId,
    required DocumentStore store,
    required AppLogger logger,
  }) : _userId = userId,
       _store = store,
       _logger = logger {
    FirestoreSchema.userDocument(userId);
  }

  final String _userId;
  final DocumentStore _store;
  final AppLogger _logger;

  @override
  Future<List<CourseRecord>> listCourses() => runAuditedOperation(
    logger: _logger,
    operation: AuditedOperation.courseList,
    action: () async {
      final documents = await _store.list(
        FirestoreSchema.coursesCollection(_userId),
      );
      return documents
          .map((document) {
            FirestoreSchema.courseDocument(_userId, document.id);
            return CourseRecord.fromFirestore(document.id, document.data);
          })
          .toList(growable: false);
    },
  );

  @override
  Future<void> saveCourse(CourseRecord course) => runAuditedOperation(
    logger: _logger,
    operation: AuditedOperation.courseSave,
    action: () => _store.set(
      FirestoreSchema.courseDocument(_userId, course.id),
      course.toFirestore(),
    ),
  );

  @override
  Future<void> deleteCourse(String courseId) => runAuditedOperation(
    logger: _logger,
    operation: AuditedOperation.courseDelete,
    action: () async {
      final timer = Stopwatch()..start();
      final coursePath = FirestoreSchema.courseDocument(_userId, courseId);
      const collections = [
        'meetings',
        'sessions',
        'academicDates',
        'materialCatalog',
        'teachingPlans',
      ];
      final fields = <String, Object>{
        'operation_id': currentOperationId!,
        'course_id': courseId,
        'stage': 'children_read',
      };
      emitOperationalEvent(_logger, 'course_delete_read_started', fields);
      var stage = 'children_read';
      try {
        final children = await Future.wait([
          for (final collection in collections)
            () async {
              try {
                return await _store.list('$coursePath/$collection');
              } catch (error, stack) {
                recordOperationalFailure(
                  _logger,
                  error,
                  stack,
                  'course_delete_children_read',
                  {
                    ...fields,
                    'collection': collection,
                    'duration_ms': timer.elapsedMilliseconds,
                  },
                  failureCode: 'course_delete_children_read_failed',
                );
                rethrow;
              }
            }(),
        ]);
        final readMs = timer.elapsedMilliseconds;
        stage = 'batch_validation';
        final paths = [
          for (var i = 0; i < collections.length; i++)
            for (final child in children[i])
              FirestoreSchema.courseChildDocument(
                _userId,
                courseId,
                collections[i],
                child.id,
              ),
          coursePath,
        ];
        if (paths.length > 500) {
          throw StateError('course_delete_batch_too_large');
        }
        stage = 'commit';
        await _store.deleteAll(paths);
        emitOperationalEvent(_logger, 'course_delete_commit_succeeded', {
          ...fields,
          'stage': stage,
          'duration_ms': timer.elapsedMilliseconds,
          'children_read_ms': readMs,
          'commit_ms': timer.elapsedMilliseconds - readMs,
          'deleted_document_count': paths.length,
          for (var i = 0; i < collections.length; i++)
            '${collections[i]}_count': children[i].length,
        });
      } catch (error, stack) {
        recordOperationalFailure(_logger, error, stack, 'course_delete', {
          ...fields,
          'stage': stage,
          'duration_ms': timer.elapsedMilliseconds,
        }, failureCode: 'course_delete_failed');
        rethrow;
      }
    },
  );
}

final class FirestoreMeetingRepository implements MeetingRepository {
  FirestoreMeetingRepository({
    required String userId,
    required DocumentStore store,
    required AppLogger logger,
  }) : _userId = userId,
       _store = store,
       _logger = logger {
    FirestoreSchema.userDocument(userId);
  }

  final String _userId;
  final DocumentStore _store;
  final AppLogger _logger;

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.meetingList,
        action: () async {
          final documents = await _store.list(
            FirestoreSchema.meetingsCollection(_userId, courseId),
          );
          return documents
              .map((document) {
                FirestoreSchema.meetingDocument(_userId, courseId, document.id);
                return MeetingRecord.fromFirestore(document.id, document.data);
              })
              .toList(growable: false);
        },
      );

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.meetingSave,
        action: () => _store.set(
          FirestoreSchema.meetingDocument(_userId, courseId, meeting.id),
          meeting.toFirestore(),
        ),
      );

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.meetingDelete,
        action: () => _store.deleteAll([
          FirestoreSchema.meetingDocument(_userId, courseId, meetingId),
        ]),
      );
}

final class FirestoreSessionRepository
    implements SessionRepository, OfflineSessionMutationQueue {
  FirestoreSessionRepository({
    required String userId,
    required DocumentStore store,
    required AppLogger logger,
  }) : _userId = userId,
       _store = store,
       _logger = logger {
    FirestoreSchema.userDocument(userId);
  }

  final String _userId;
  final DocumentStore _store;
  final AppLogger _logger;

  @override
  Future<List<SessionRecord>> listSessions(String courseId) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.sessionList,
        action: () async {
          final documents = await _store.list(
            FirestoreSchema.sessionsCollection(_userId, courseId),
          );
          return documents
              .map((document) {
                FirestoreSchema.sessionDocument(_userId, courseId, document.id);
                return SessionRecord.fromFirestore(document.id, document.data);
              })
              .toList(growable: false);
        },
      );

  @override
  Future<void> saveSession(String courseId, SessionRecord session) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.sessionSave,
        action: () => _store.set(
          FirestoreSchema.sessionDocument(_userId, courseId, session.id),
          session.toFirestore(),
        ),
      );

  @override
  Future<void> patchAttendance(
    String courseId,
    String sessionId, {
    required SituacaoFrequencia status,
    required int? absences,
    required DateTime updatedAt,
  }) => runAuditedOperation(
    logger: _logger,
    operation: AuditedOperation.sessionSave,
    action: () => _store.update(
      FirestoreSchema.sessionDocument(_userId, courseId, sessionId),
      {
        'attendanceStatus': status.code,
        'absences': absences,
        'updatedAt': updatedAt,
      },
    ),
  );

  @override
  Future<void> patchCalendarStatus(
    String courseId,
    String sessionId, {
    required SessionCalendarStatus status,
    required DateTime updatedAt,
  }) => runAuditedOperation(
    logger: _logger,
    operation: AuditedOperation.sessionSave,
    action: () => _store.update(
      FirestoreSchema.sessionDocument(_userId, courseId, sessionId),
      {'calendarStatus': status.code, 'updatedAt': updatedAt},
    ),
  );

  @override
  Future<void> deleteSession(String courseId, String sessionId) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.sessionDelete,
        action: () => _store.deleteAll([
          FirestoreSchema.sessionDocument(_userId, courseId, sessionId),
        ]),
      );
}
