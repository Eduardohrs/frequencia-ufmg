import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/python_course_repository.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  test(
    'adapts course records to the Python gateway with audited logs',
    () async {
      final gateway = _Gateway();
      final logger = _Logger();
      final repository = PythonCourseRepository(
        gateway: gateway,
        logger: logger,
      );
      final course = _record();

      expect((await repository.listCourses()).single.code, 'DCC203');
      await repository.saveCourse(course);
      await repository.deleteCourse(course.id);

      expect(gateway.saved?.name, 'POO');
      expect(gateway.deleted, 'course-1');
      expect(logger.events, [
        'firestore_course_list_started',
        'firestore_course_list_succeeded',
        'firestore_course_save_started',
        'firestore_course_save_succeeded',
        'firestore_course_delete_started',
        'firestore_course_delete_succeeded',
      ]);
    },
  );
}

CourseRecord _record() => CourseRecord(
  id: 'course-1',
  code: 'DCC203',
  name: 'POO',
  workload: 1,
  term: '2026-2',
  createdAt: DateTime.utc(2026, 10, 4, 12),
  updatedAt: DateTime.utc(2026, 10, 4, 12),
);

final class _Gateway implements BackendCourseGateway {
  PythonCourse? saved;
  String? deleted;

  @override
  Future<List<PythonCourse>> listCourses() async => [
    PythonCourse(
      id: 'course-1',
      code: 'DCC203',
      name: 'POO',
      workload: 1,
      term: '2026-2',
      startsOn: null,
      endsOn: null,
      createdAt: DateTime.utc(2026, 10, 4, 12),
      updatedAt: DateTime.utc(2026, 10, 4, 12),
    ),
  ];

  @override
  Future<PythonCourse> saveCourse(PythonCourse course) async {
    saved = course;
    return course;
  }

  @override
  Future<void> deleteCourse(String courseId) async {
    deleted = courseId;
  }
}

final class _Logger implements AppLogger {
  final events = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {}
}
