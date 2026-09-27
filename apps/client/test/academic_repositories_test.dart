import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/document_store.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  final createdAt = DateTime.utc(2026, 7, 1);
  final updatedAt = DateTime.utc(2026, 7, 2);
  late _FakeDocumentStore store;
  late _FakeAppLogger logger;

  setUp(() {
    store = _FakeDocumentStore();
    logger = _FakeAppLogger();
  });

  test('course repository lists, saves, and deletes below its user', () async {
    final course = CourseRecord(
      id: 'poo',
      code: 'DCC203',
      name: 'Programacao Orientada a Objetos',
      workload: 60,
      term: '2026-2',
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
    store.documents = [
      StoredDocument(id: course.id, data: course.toFirestore()),
    ];
    final repository = FirestoreCourseRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );

    final courses = await repository.listCourses();
    await repository.saveCourse(course);
    await repository.deleteCourse(course.id);

    expect(courses.single.code, 'DCC203');
    expect(store.listedPaths, ['users/user-1/courses']);
    expect(store.savedPaths, ['users/user-1/courses/poo']);
    expect(store.savedData.single, course.toFirestore());
    expect(store.deletedPaths, ['users/user-1/courses/poo']);
    expect(logger.events, [
      'firestore_course_list_started',
      'firestore_course_list_succeeded',
      'firestore_course_save_started',
      'firestore_course_save_succeeded',
      'firestore_course_delete_started',
      'firestore_course_delete_succeeded',
    ]);
  });

  test('meeting repository uses the selected course path', () async {
    final meeting = MeetingRecord(
      id: 'monday',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
    store.documents = [
      StoredDocument(id: meeting.id, data: meeting.toFirestore()),
    ];
    final repository = FirestoreMeetingRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );

    final meetings = await repository.listMeetings('poo');
    await repository.saveMeeting('poo', meeting);
    await repository.deleteMeeting('poo', meeting.id);

    expect(meetings.single.lessonCount, QuantidadeAulas.two);
    expect(store.listedPaths, ['users/user-1/courses/poo/meetings']);
    expect(store.savedPaths, ['users/user-1/courses/poo/meetings/monday']);
    expect(store.savedData.single, meeting.toFirestore());
    expect(store.deletedPaths, ['users/user-1/courses/poo/meetings/monday']);
    expect(logger.events, [
      'firestore_meeting_list_started',
      'firestore_meeting_list_succeeded',
      'firestore_meeting_save_started',
      'firestore_meeting_save_succeeded',
      'firestore_meeting_delete_started',
      'firestore_meeting_delete_succeeded',
    ]);
  });

  test('session repository uses the selected course path', () async {
    final session = SessionRecord(
      id: '2026-08-03',
      startsAt: DateTime.utc(2026, 8, 3, 8),
      endsAt: DateTime.utc(2026, 8, 3, 10),
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.two,
      firstPing: EstadoPing.away,
      secondPing: EstadoPing.onCampus,
      attendanceStatus: SituacaoFrequencia.arrivedLate,
      absences: 1,
      createdAt: createdAt,
      updatedAt: updatedAt,
    );
    store.documents = [
      StoredDocument(id: session.id, data: session.toFirestore()),
    ];
    final repository = FirestoreSessionRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );

    final sessions = await repository.listSessions('poo');
    await repository.saveSession('poo', session);
    await repository.deleteSession('poo', session.id);

    expect(sessions.single.attendanceStatus, SituacaoFrequencia.arrivedLate);
    expect(store.listedPaths, ['users/user-1/courses/poo/sessions']);
    expect(store.savedPaths, ['users/user-1/courses/poo/sessions/2026-08-03']);
    expect(store.savedData.single, session.toFirestore());
    expect(store.deletedPaths, [
      'users/user-1/courses/poo/sessions/2026-08-03',
    ]);
    expect(logger.events, [
      'firestore_session_list_started',
      'firestore_session_list_succeeded',
      'firestore_session_save_started',
      'firestore_session_save_succeeded',
      'firestore_session_delete_started',
      'firestore_session_delete_succeeded',
    ]);
  });

  test('repositories reject unsafe identifiers before store access', () async {
    final courseRepository = FirestoreCourseRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );
    final meetingRepository = FirestoreMeetingRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );
    final sessionRepository = FirestoreSessionRepository(
      userId: 'user-1',
      store: store,
      logger: logger,
    );

    expect(
      () => FirestoreCourseRepository(
        userId: '../other-user',
        store: store,
        logger: logger,
      ),
      throwsArgumentError,
    );
    await expectLater(
      courseRepository.deleteCourse('../course'),
      throwsArgumentError,
    );
    await expectLater(
      meetingRepository.listMeetings('../course'),
      throwsArgumentError,
    );
    await expectLater(
      meetingRepository.deleteMeeting('poo', '../meeting'),
      throwsArgumentError,
    );
    await expectLater(
      sessionRepository.listSessions('../course'),
      throwsArgumentError,
    );
    await expectLater(
      sessionRepository.deleteSession('poo', '../session'),
      throwsArgumentError,
    );
    expect(store.listedPaths, isEmpty);
    expect(store.savedPaths, isEmpty);
    expect(store.deletedPaths, isEmpty);
  });

  test(
    'invalid remote data is reported without leaking document data',
    () async {
      store.documents = [
        const StoredDocument(id: 'broken', data: {'schemaVersion': 1}),
      ];
      final repository = FirestoreCourseRepository(
        userId: 'user-1',
        store: store,
        logger: logger,
      );

      await expectLater(repository.listCourses(), throwsFormatException);

      expect(logger.events, [
        'firestore_course_list_started',
        'firestore_course_list_failed',
      ]);
      expect(logger.errorContexts, ['firestore_course_list']);
      expect(logger.allParameters.toString(), isNot(contains('broken')));
    },
  );
}

final class _FakeDocumentStore implements DocumentStore {
  List<StoredDocument> documents = [];
  final listedPaths = <String>[];
  final savedPaths = <String>[];
  final savedData = <Map<String, Object?>>[];
  final deletedPaths = <String>[];

  @override
  Future<void> delete(String documentPath) async {
    deletedPaths.add(documentPath);
  }

  @override
  Future<List<StoredDocument>> list(String collectionPath) async {
    listedPaths.add(collectionPath);
    return documents;
  }

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) async {
    savedPaths.add(documentPath);
    savedData.add(data);
  }
}

final class _FakeAppLogger implements AppLogger {
  final events = <String>[];
  final allParameters = <Map<String, Object>?>[];
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
    allParameters.add(parameters);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
    allParameters.add(parameters);
  }
}
