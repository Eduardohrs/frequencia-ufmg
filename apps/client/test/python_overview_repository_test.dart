import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/python_overview_repository.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  test(
    'maps one aggregate response into the existing domain records',
    () async {
      final logger = _Logger();
      final repository = PythonOverviewRepository(
        gateway: _Gateway(),
        logger: logger,
      );

      final snapshot = await repository.loadOverview();

      expect(snapshot.courses.single.code, 'DCC203');
      final session = snapshot.sessionsByCourse['course-1']!.single;
      expect(session.firstPing, EstadoPing.onCampus);
      expect(session.attendanceStatus, SituacaoFrequencia.present);
      expect(session.absences, 0);
      expect(logger.events, [
        'academic_overview_load_started',
        'academic_overview_load_succeeded',
      ]);
    },
  );
}

final class _Gateway implements BackendOverviewGateway {
  @override
  Future<List<PythonOverviewItem>> loadOverview() async => [
    PythonOverviewItem(
      course: PythonCourse.fromJson(const {
        'id': 'course-1',
        'code': 'DCC203',
        'name': 'POO',
        'workload': 60,
        'term': '2026-2',
        'starts_on': '2026-07-01T00:00:00Z',
        'ends_on': '2026-12-31T00:00:00Z',
        'created_at': '2026-07-01T12:00:00Z',
        'updated_at': '2026-07-01T12:00:00Z',
      }),
      sessions: [
        PythonSession.fromJson(const {
          'id': 'session-1',
          'starts_at': '2026-10-08T10:00:00Z',
          'ends_at': '2026-10-08T11:40:00Z',
          'lesson_count': 2,
          'call_count': 1,
          'first_ping': 'no_campus',
          'second_ping': null,
          'attendance_status': 'presente',
          'absences': 0,
          'calendar_status': 'scheduled',
          'assessment_title': null,
          'created_at': '2026-07-01T12:00:00Z',
          'updated_at': '2026-10-08T12:00:00Z',
        }),
      ],
    ),
  ];
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
