import 'dart:async';
import 'package:frequencia_ufmg/backend/academic_sync_progress.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';

PythonUnifiedAcademicSyncResult syncResult({bool partial = false}) =>
    PythonUnifiedAcademicSyncResult(
      siga: PythonUFMGSigaSyncResult(
        courses: const PythonUFMGCourseImportResult(
          created: 0,
          existing: 1,
          total: 1,
        ),
        schedules: const PythonUFMGScheduleImportResult(
          total: 1,
          updated: 0,
          unchanged: 1,
          conflicts: 0,
          missingCourses: 0,
          meetingsImported: 0,
        ),
        checkedAt: DateTime.utc(2026, 10, 25),
        nextAutomaticSyncAt: DateTime.utc(2027, 1),
      ),
      moodle: const PythonMoodleSyncResult(
        dates: PythonMoodleDateImportResult(
          total: 0,
          matched: 0,
          unmatched: 0,
          created: 0,
          updated: 0,
          unchanged: 0,
        ),
        candidateTotal: 0,
        capabilities: null,
      ),
      teachingPlans: PythonTeachingPlanSyncSummary(
        available: 1,
        imported: 0,
        applied: 0,
        unchanged: 0,
        reviewRequired: partial ? 1 : 0,
      ),
      exceptions: [
        if (partial)
          const PythonAcademicSyncException(
            courseId: 'esa019',
            courseCode: 'ESA019',
            reason: 'teaching_plan_not_published',
            candidateCount: 1,
            changes: [],
            conflicting: 0,
            assessmentConflicts: 0,
          ),
      ],
    );

class ProgressGateway implements BackendAcademicSyncProgressGateway {
  final response = Completer<PythonUnifiedAcademicSyncResult>();
  final updates = StreamController<AcademicSyncProgress>.broadcast(sync: true);
  int calls = 0;
  bool lastForce = false;
  String? operationId;
  bool throwsOnWatch = false;
  @override
  Stream<AcademicSyncProgress> watchSyncProgress(String operationId) {
    if (throwsOnWatch) throw StateError('listener unavailable');
    return updates.stream;
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncWithProgress(
    String id, {
    bool force = false,
  }) {
    calls++;
    lastForce = force;
    operationId = id;
    return response.future;
  }

  @override
  Future<PythonUnifiedAcademicSyncResult> syncAllAcademicData() =>
      response.future;
}
