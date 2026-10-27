import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_agenda.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/data/document_store.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

final instant = DateTime.utc(2026, 10, 28, 14);
CourseRecord course({bool online = false}) => CourseRecord(
  id: 'poo',
  code: 'DCC203',
  name: 'POO',
  workload: 60,
  term: '2026-2',
  modality: online ? CourseModality.online : CourseModality.inPerson,
  attendancePolicy: online
      ? CourseAttendancePolicy.noCall
      : CourseAttendancePolicy.required,
  createdAt: instant,
  updatedAt: instant,
);
PythonMoodleDate date(
  String title,
  DateTime due, {
  String id = 'moodle-1',
  String courseId = 'poo',
}) => PythonMoodleDate(
  id: id,
  courseId: courseId,
  courseCode: 'DCC203',
  title: title,
  dueAt: due,
  kind: 'assignment',
);
SessionRecord session({
  String? title,
  SessionCalendarStatus status = SessionCalendarStatus.scheduled,
}) => SessionRecord(
  id: 'class',
  startsAt: instant,
  endsAt: instant.add(const Duration(hours: 2)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.one,
  calendarStatus: status,
  assessmentTitle: title,
  createdAt: instant,
  updatedAt: instant,
);

void main() {
  test('standalone assignments appear without creating attendance lessons', () {
    final deadline = date('Parte 2', instant.add(const Duration(days: 1)));
    final original = session();
    final entries = courseAgenda(course(), [original], [deadline]);
    expect(entries.single.title, 'Parte 2');
    expect(entries.single.session, isNull);
    expect(original.assessmentTitle, isNull);
    expect(original.absences, isNull);
    expect(
      courseAgenda(course(), [original], [deadline], includeLessons: true),
      hasLength(2),
    );
  });

  test(
    'deduplicates only the same title and instant inside a linked lesson',
    () {
      final original = session(title: ' PROVA  1 ');
      final due = instant.add(const Duration(minutes: 30));
      final entries = courseAgenda(
        course(),
        [original],
        [
          date('Prova 1', due),
          date('prova 1', due, id: 'diario-2'),
          date('Outra tarefa', due, id: 'moodle-3'),
          date('Prova 1', instant.add(const Duration(days: 1)), id: 'moodle-4'),
          date('Ignorada', due, courseId: 'other'),
        ],
      );
      expect(entries.map((e) => e.title), [
        'Outra tarefa',
        'Prova 1',
        'Prova 1',
      ]);
      expect(entries.where((e) => e.session != null), hasLength(1));
      expect(entries.first.startsAt, due);
      expect(
        courseAgenda(
          course(),
          [session(title: 'Manual')],
          [date('Importada', due)],
        ),
        hasLength(2),
      );
      expect(
        courseAgenda(
          course(),
          [session(title: 'Prova 1')],
          [date('Prova 1', original.endsAt)],
        ),
        hasLength(2),
      );
    },
  );

  test(
    'online, no-call, holiday and cancelled lessons keep independent deadlines',
    () {
      for (final status in SessionCalendarStatus.values) {
        final original = session(title: 'Exercício', status: status);
        final entries = courseAgenda(
          course(),
          [original],
          [date('Entrega', instant)],
          includeLessons: true,
        );
        expect(entries.any((e) => e.title == 'Entrega'), isTrue);
        expect(
          entries.length,
          status == SessionCalendarStatus.cancelled ||
                  status == SessionCalendarStatus.holiday
              ? 1
              : 2,
        );
        expect(
          courseAgenda(
            course(online: true),
            [original],
            [date('Entrega', instant)],
            includeLessons: true,
          ).single.session,
          isNull,
        );
      }
      expect(
        courseAgenda(course(), [
          session(title: 'Z'),
          session(title: 'A'),
        ], []).map((e) => e.title),
        ['A', 'Z'],
      );
    },
  );

  test(
    'reads persisted Moodle and Diário dates, with correlated success and stage errors',
    () async {
      final store = _Store();
      final logger = _Logger();
      final repository = FirestoreAcademicDateRepository(
        userId: 'owner',
        store: store,
        logger: logger,
      );
      final document = <String, Object?>{
        'schemaVersion': 1,
        'title': 'Parte 2',
        'kind': 'assignment',
        'source': 'moodle',
        'sourceId': '1',
        'dueAt': Timestamp.fromDate(instant),
        'createdAt': Timestamp.fromDate(instant),
        'updatedAt': Timestamp.fromDate(instant),
      };
      store.documents = [StoredDocument(id: 'moodle-1', data: document)];
      final values = await repository.listDates('poo');
      expect(store.path, 'users/owner/courses/poo/academicDates');
      expect(values.single.title, 'Parte 2');
      final evidence = logger.events['agenda_dates_read_succeeded']!;
      expect(evidence['course_id'], 'poo');
      expect(evidence['count'], 1);
      expect(evidence['duration_ms'], isA<int>());
      expect(
        evidence['operation_id'],
        logger.events['moodle_date_list_started']!['operation_id'],
      );
      for (final invalid in [
        {...document, 'dueAt': 'broken'},
        {...document, 'kind': 'unknown'},
        {...document, 'schemaVersion': 2},
      ]) {
        store.documents = [StoredDocument(id: 'moodle-1', data: invalid)];
        await expectLater(repository.listDates('poo'), throwsFormatException);
        expect(
          logger.errors.lastWhere(
            (e) => e['context'] == 'agenda_dates_read',
          )['reason'],
          'invalid_date_document',
        );
        expect(
          logger.errors.lastWhere(
            (e) => e['context'] == 'agenda_dates_read',
          )['stage'],
          'date_document_decode',
        );
      }
      store.documents = List.generate(
        501,
        (_) => StoredDocument(id: 'moodle-1', data: document),
      );
      await expectLater(repository.listDates('poo'), throwsFormatException);
      store.error = StateError('offline');
      await expectLater(repository.listDates('poo'), throwsStateError);
      expect(
        logger.errors.lastWhere(
          (e) => e['context'] == 'agenda_dates_read',
        )['reason'],
        'store_read_failed',
      );
      expect(logger.events, contains('moodle_date_list_failed'));
    },
  );

  test('telemetry failure cannot block dates or presentation', () async {
    final logger = _Logger()..fail = true;
    final values = await FirestoreAcademicDateRepository(
      userId: 'owner',
      store: _Store(),
      logger: logger,
    ).listDates('poo');
    expect(values, isEmpty);
    recordAgendaPresentation(
      logger: logger,
      screen: 'home',
      importedCount: 0,
      entryCount: 0,
      unavailableCourses: [],
    );
    await Future<void>.delayed(Duration.zero);
  });
}

class _Store implements DocumentStore {
  List<StoredDocument> documents = [];
  Object? error;
  String? path;
  @override
  Future<List<StoredDocument>> list(String collectionPath) async {
    path = collectionPath;
    if (error != null) throw error!;
    return documents;
  }

  @override
  Future<void> set(String path, Map<String, Object?> data) =>
      throw UnimplementedError();
  @override
  Future<void> update(String path, Map<String, Object?> data) =>
      throw UnimplementedError();
  @override
  Future<void> deleteAll(Iterable<String> paths) => throw UnimplementedError();
}

class _Logger implements AppLogger {
  final events = <String, Map<String, Object>>{};
  final errors = <Map<String, Object>>[];
  bool fail = false;
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (fail) throw StateError('logger offline');
    events[name] = parameters ?? {};
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errors.add({'context': context, ...?parameters});
  }
}
