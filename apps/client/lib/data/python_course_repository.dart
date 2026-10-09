import '../backend/python_backend_transport.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import 'academic_records.dart';
import 'academic_repositories.dart';

final class PythonCourseRepository implements CourseRepository {
  const PythonCourseRepository({required this.gateway, required this.logger});

  final BackendCourseGateway gateway;
  final AppLogger logger;

  @override
  Future<List<CourseRecord>> listCourses() => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.courseList,
    action: () async => (await gateway.listCourses())
        .map(courseRecordFromPython)
        .toList(growable: false),
  );

  @override
  Future<void> saveCourse(CourseRecord course) => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.courseSave,
    action: () async {
      await gateway.saveCourse(_toPython(course));
    },
  );

  @override
  Future<void> deleteCourse(String courseId) => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.courseDelete,
    action: () => gateway.deleteCourse(courseId),
  );

  static PythonCourse _toPython(CourseRecord course) => PythonCourse(
    id: course.id,
    code: course.code,
    name: course.name,
    workload: course.workload,
    term: course.term,
    startsOn: course.startsOn,
    endsOn: course.endsOn,
    createdAt: course.createdAt,
    updatedAt: course.updatedAt,
  );
}

CourseRecord courseRecordFromPython(PythonCourse course) => CourseRecord(
  id: course.id,
  code: course.code,
  name: course.name,
  workload: course.workload,
  term: course.term,
  startsOn: course.startsOn,
  endsOn: course.endsOn,
  createdAt: course.createdAt,
  updatedAt: course.updatedAt,
);
