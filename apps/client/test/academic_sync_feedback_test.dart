import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/features/ufmg/academic_sync_feedback.dart';
import 'package:frequencia_ufmg/observability/operation_diagnostics.dart';
import 'fixtures/academic_sync_fixture.dart';
import 'fixtures/product_experience_fixture.dart';

void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  test(
    'large numeric diagnostics remain bounded, parseable and do not stall the operation',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      final counters = <String, Object>{
        'stage': 'result',
        for (var i = 0; i < 50; i++)
          'counter_with_meaningful_domain_name_$i': i,
      };
      emitOperationalEvent(h.logger, 'numeric_report', counters);
      recordOperationalFailure(
        h.logger,
        StateError('ordinary failure'),
        StackTrace.current,
        'numeric_operation',
        counters,
        failureCode: 'numeric_failure',
      );
      await Future<void>.delayed(Duration.zero);
      final success = h.store.rows.singleWhere(
        (r) => r['event'] == 'numeric_report',
      );
      final fields = jsonDecode(success['details'] as String) as Map;
      expect(fields['counter_with_meaningful_domain_name_49'], 49);
      expect((success['details'] as String).length, greaterThan(500));
      final failure = h.store.rows.singleWhere(
        (r) => r['operation'] == 'numeric_operation',
      );
      expect(
        jsonDecode(
          failure['errorDetails'] as String,
        )['counter_with_meaningful_domain_name_49'],
        49,
      );
      emitOperationalEvent(h.logger, 'oversized_report', {
        for (var i = 0; i < 300; i++) '${'domain_' * 15}$i': i,
      });
      await Future<void>.delayed(Duration.zero);
      final large = h.store.rows.singleWhere(
        (r) => r['event'] == 'oversized_report',
      );
      expect((large['details'] as String).length, lessThanOrEqualTo(8192));
      expect(jsonDecode(large['details'] as String)['details_truncated'], true);
    },
  );
  test(
    'success counters stay available in persisted logs without becoming UI notices',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      final result = syncResult();
      expect(unifiedSyncIssues(result), isEmpty);
      logSyncFeedback(
        h.logger,
        'all',
        {...sigaSyncDetails(result.siga), ...moodleSyncDetails(result.moodle)},
        const [],
        operationId: 'same-sync',
      );
      await Future<void>.delayed(Duration.zero);
      final row = h.store.rows.singleWhere(
        (r) => r['event'] == 'academic_sync_result_details',
      );
      final fields = jsonDecode(row['details'] as String) as Map;
      expect(fields['courses_created'], 0);
      expect(fields['courses_existing'], 1);
      expect(fields['dates_created'], 0);
      expect(fields['download_capability'], 'unknown');
      expect(fields['issue_count'], 0);
      expect(row['correlationId'], 'same-sync');
    },
  );
  test(
    'actionable course failures remain identified while unpublished plans stay quiet',
    () async {
      final h = ExperienceHarness();
      addTearDown(h.dispose);
      final original = syncResult();
      final activities = PythonActivitySyncSummary.fromJson({
        'updated': 0,
        'reused': 2,
        'failed': 1,
        'failed_courses': [
          {
            'course_id': 'poo',
            'course_code': 'DCC203',
            'reason': 'upstream_unavailable',
          },
        ],
      });
      final moodle = PythonMoodleSyncResult(
        dates: const PythonMoodleDateImportResult(
          total: 1,
          matched: 0,
          unmatched: 1,
          created: 0,
          updated: 0,
          unchanged: 0,
          failed: 1,
          failedCourses: [
            {'course_id': 'calc', 'course_code': 'MAT002', 'reason': 'timeout'},
          ],
        ),
        candidateTotal: 0,
        capabilities: null,
        activitySnapshots: activities,
      );
      final result = PythonUnifiedAcademicSyncResult(
        siga: original.siga,
        moodle: moodle,
        teachingPlans: original.teachingPlans,
        exceptions: [
          ...syncResult(partial: true).exceptions,
          const PythonAcademicSyncException(
            courseId: 'not-yet',
            courseCode: 'ELE999',
            reason: 'teaching_plan_not_published',
            candidateCount: 0,
            changes: [],
            conflicting: 0,
            assessmentConflicts: 0,
          ),
        ],
      );
      final issues = unifiedSyncIssues(result);
      expect(issues.length, 4);
      expect(issues.map((e) => e.courseCode), contains('DCC203'));
      expect(issues.map((e) => e.courseCode), isNot(contains('ELE999')));
      logSyncFeedback(
        h.logger,
        'all',
        moodleSyncDetails(moodle),
        issues,
        operationId: 'partial-sync',
      );
      await Future<void>.delayed(Duration.zero);
      final records = h.store.rows
          .where((r) => r['event'] == 'academic_sync_course_issue')
          .toList();
      expect(records.length, 4);
      final fields = jsonDecode(
        records.firstWhere(
              (r) => (r['details'] as String).contains('DCC203'),
            )['details']
            as String,
      );
      expect(fields['course_id'], 'poo');
      expect(fields['stage'], 'activities');
      expect(fields['reason'], 'upstream_unavailable');
      expect(records.every((r) => r['correlationId'] == 'partial-sync'), true);
      final noDetails = PythonMoodleSyncResult(
        dates: original.moodle.dates,
        candidateTotal: 0,
        capabilities: null,
        activitySnapshots: const PythonActivitySyncSummary(
          updated: 0,
          failed: 1,
        ),
      );
      expect(moodleSyncIssues(noDetails).single.stage, 'activities');
      expect(
        () => PythonActivitySyncSummary.fromJson({
          'updated': 0,
          'failed': 1,
          'failed_courses': ['broken'],
        }),
        throwsFormatException,
      );
    },
  );
}
