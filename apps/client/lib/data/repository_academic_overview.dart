import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import 'academic_records.dart';
import 'academic_repositories.dart';
import 'python_overview_repository.dart';

const _maximumOverviewCourses = 50;
const _maximumOverviewSessions = 500;

typedef CurrentUserId = String? Function();
typedef UserCourseRepository = CourseRepository Function(String userId);
typedef UserSessionRepository = SessionRepository Function(String userId);

final class CurrentUserAcademicOverviewRepository
    implements AcademicOverviewRepository {
  const CurrentUserAcademicOverviewRepository({
    required this.currentUserId,
    required this.courseRepositoryFor,
    required this.sessionRepositoryFor,
    required this.logger,
  });

  final CurrentUserId currentUserId;
  final UserCourseRepository courseRepositoryFor;
  final UserSessionRepository sessionRepositoryFor;
  final AppLogger logger;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() {
    final userId = currentUserId();
    if (userId == null || userId.isEmpty) {
      throw StateError('No authenticated user is available.');
    }
    return RepositoryAcademicOverviewRepository(
      courseRepository: courseRepositoryFor(userId),
      sessionRepository: sessionRepositoryFor(userId),
      logger: logger,
    ).loadOverview();
  }
}

final class RepositoryAcademicOverviewRepository
    implements AcademicOverviewRepository {
  const RepositoryAcademicOverviewRepository({
    required this.courseRepository,
    required this.sessionRepository,
    required this.logger,
  });

  final CourseRepository courseRepository;
  final SessionRepository sessionRepository;
  final AppLogger logger;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.academicOverviewLoad,
    action: () async {
      final courses = await courseRepository.listCourses();
      if (courses.length > _maximumOverviewCourses) {
        throw StateError('The academic overview has too many courses.');
      }
      final sessions = await Future.wait([
        for (final course in courses) sessionRepository.listSessions(course.id),
      ]);
      if (sessions.fold<int>(0, (total, items) => total + items.length) >
          _maximumOverviewSessions) {
        throw StateError('The academic overview has too many sessions.');
      }
      return AcademicOverviewSnapshot(
        courses: courses,
        sessionsByCourse: <String, List<SessionRecord>>{
          for (var index = 0; index < courses.length; index += 1)
            courses[index].id: sessions[index],
        },
      );
    },
  );
}
