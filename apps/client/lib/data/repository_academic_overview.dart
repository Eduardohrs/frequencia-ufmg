import 'dart:async';
import '../backend/python_backend_transport.dart';
import 'academic_agenda.dart';
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
    this.dateRepositoryFor,
  });

  final CurrentUserId currentUserId;
  final UserCourseRepository courseRepositoryFor;
  final UserSessionRepository sessionRepositoryFor;
  final AppLogger logger;
  final AcademicDateRepository Function(String userId)? dateRepositoryFor;

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
      dateRepository: dateRepositoryFor?.call(userId),
    ).loadOverview();
  }
}

final class RepositoryAcademicOverviewRepository
    implements AcademicOverviewRepository {
  const RepositoryAcademicOverviewRepository({
    required this.courseRepository,
    required this.sessionRepository,
    required this.logger,
    this.dateRepository,
  });

  final CourseRepository courseRepository;
  final SessionRepository sessionRepository;
  final AppLogger logger;
  final AcademicDateRepository? dateRepository;

  @override
  Future<AcademicOverviewSnapshot> loadOverview() => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.academicOverviewLoad,
    action: () async {
      final courses = await courseRepository.listCourses();
      if (courses.length > _maximumOverviewCourses) {
        throw StateError('The academic overview has too many courses.');
      }
      final datesByCourse = <String, List<PythonMoodleDate>>{};
      final unavailable = <String>{};
      final dateReads = Future.wait([
        if (dateRepository != null)
          for (final course in courses)
            () async {
              try {
                datesByCourse[course.id] = await dateRepository!.listDates(
                  course.id,
                );
              } catch (error, stack) {
                unavailable.add(course.id);
                unawaited(
                  logger
                      .recordError(
                        error,
                        stack,
                        context: 'agenda_course_read',
                        parameters: {
                          'course_id': course.id,
                          'course_code': course.code,
                          'stage': 'academic_dates_read',
                          'operation_id': currentOperationId!,
                        },
                      )
                      .catchError((Object _) {}),
                );
              }
            }(),
      ]);
      final sessions = await Future.wait([
        for (final course in courses) sessionRepository.listSessions(course.id),
      ]);
      if (sessions.fold<int>(0, (total, items) => total + items.length) >
          _maximumOverviewSessions) {
        throw StateError('The academic overview has too many sessions.');
      }
      await dateReads;
      unawaited(
        logger
            .logEvent(
              'agenda_overview_loaded',
              parameters: {
                'operation_id': currentOperationId!,
                'stage': 'academic_dates_read',
                'course_count': courses.length,
                'imported_count': datesByCourse.values.fold<int>(
                  0,
                  (sum, dates) => sum + dates.length,
                ),
                'unavailable_courses': unavailable.join(','),
              },
            )
            .catchError((Object _) {}),
      );
      return AcademicOverviewSnapshot(
        datesByCourse: datesByCourse,
        unavailableDateCourses: unavailable,
        courses: courses,
        sessionsByCourse: <String, List<SessionRecord>>{
          for (var index = 0; index < courses.length; index += 1)
            courses[index].id: sessions[index],
        },
      );
    },
  );
}
