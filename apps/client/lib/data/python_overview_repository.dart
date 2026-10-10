import '../backend/python_backend_transport.dart';
import '../domain/attendance.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import 'academic_records.dart';
import 'calendar_status.dart';
import 'python_course_repository.dart';

final class AcademicOverviewSnapshot {
  AcademicOverviewSnapshot({
    required List<CourseRecord> courses,
    required Map<String, List<SessionRecord>> sessionsByCourse,
    this.isLocalCopy = false,
  }) : courses = List.unmodifiable(courses),
       sessionsByCourse = Map<String, List<SessionRecord>>.unmodifiable({
         for (final entry in sessionsByCourse.entries)
           entry.key: List<SessionRecord>.unmodifiable(entry.value),
       });

  final List<CourseRecord> courses;
  final Map<String, List<SessionRecord>> sessionsByCourse;
  final bool isLocalCopy;
}

abstract interface class AcademicOverviewRepository {
  Future<AcademicOverviewSnapshot> loadOverview();
}

final class PythonOverviewRepository implements AcademicOverviewRepository {
  const PythonOverviewRepository({required this.gateway, required this.logger});

  final BackendOverviewGateway gateway;
  final AppLogger logger;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.academicOverviewLoad,
    action: () async {
      final items = await gateway.loadOverview();
      return AcademicOverviewSnapshot(
        courses: [
          for (final item in items) courseRecordFromPython(item.course),
        ],
        sessionsByCourse: {
          for (final item in items)
            item.course.id: [
              for (final session in item.sessions) _sessionRecord(session),
            ],
        },
      );
    },
  );
}

SessionRecord _sessionRecord(PythonSession session) => SessionRecord(
  id: session.id,
  startsAt: session.startsAt,
  endsAt: session.endsAt,
  lessonCount: QuantidadeAulas.fromValue(session.lessonCount),
  callCount: NumeroChamadas.fromValue(session.callCount),
  firstPing: session.firstPing == null
      ? null
      : EstadoPing.fromCode(session.firstPing!),
  secondPing: session.secondPing == null
      ? null
      : EstadoPing.fromCode(session.secondPing!),
  attendanceStatus: session.attendanceStatus == null
      ? null
      : SituacaoFrequencia.fromCode(session.attendanceStatus!),
  absences: session.absences,
  calendarStatus: SessionCalendarStatus.fromCode(session.calendarStatus),
  assessmentTitle: session.assessmentTitle,
  createdAt: session.createdAt,
  updatedAt: session.updatedAt,
);
