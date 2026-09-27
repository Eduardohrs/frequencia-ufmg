import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import 'academic_records.dart';
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
    action: () =>
        _store.delete(FirestoreSchema.courseDocument(_userId, courseId)),
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
        action: () => _store.delete(
          FirestoreSchema.meetingDocument(_userId, courseId, meetingId),
        ),
      );
}

final class FirestoreSessionRepository implements SessionRepository {
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
  Future<void> deleteSession(String courseId, String sessionId) =>
      runAuditedOperation(
        logger: _logger,
        operation: AuditedOperation.sessionDelete,
        action: () => _store.delete(
          FirestoreSchema.sessionDocument(_userId, courseId, sessionId),
        ),
      );
}
