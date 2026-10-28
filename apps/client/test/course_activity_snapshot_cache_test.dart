import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/course_activity_snapshot_cache.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  test('invalid cached plan is rejected before rendering', () async {
    await SharedPreferencesAsync().setString(
      'plan.course_activity_snapshot.v1.u.c.2026-2',
      '{}',
    );
    await expectLater(
      CourseActivitySnapshotCache().readPlan('u', 'c', '2026-2'),
      throwsFormatException,
    );
  });
  test(
    'plan copy persists without credentials and is scoped to account and semester',
    () async {
      final cache = CourseActivitySnapshotCache();
      expect(await cache.readPlan('u', 'c', '2026-2'), isNull);
      await cache.writePlan('u', 'c', '2026-2', {
        'criteria': [],
        'schedule': [],
        'assessments': [],
        'token': 'never-cache',
      });
      final copy = await CourseActivitySnapshotCache().readPlan(
        'u',
        'c',
        '2026-2',
      );
      expect(copy, {'criteria': [], 'schedule': [], 'assessments': []});
      expect(await cache.readPlan('other', 'c', '2026-2'), isNull);
      expect(await cache.readPlan('u', 'c', '2027-1'), isNull);
      await cache.writePlan('u', 'c', '2026-2', null);
      expect(await cache.readPlan('u', 'c', '2026-2'), copy);
    },
  );
  test(
    'snapshot persists across instances and stays isolated by account,course and semester',
    () async {
      final snapshot = PythonCourseActivitySnapshot.fromJson({
        'course_id': 'poo',
        'term': '2026-2',
        'synced_at': '2026-10-28T12:00:00Z',
        'activities': [],
      });
      final cache = CourseActivitySnapshotCache();
      expect(await cache.read('owner', 'poo', '2026-2'), isNull);
      await cache.write('owner', snapshot);
      final restored = await CourseActivitySnapshotCache().read(
        'owner',
        'poo',
        '2026-2',
      );
      expect(restored!.syncedAt, DateTime.utc(2026, 10, 28, 12));
      expect(await cache.read('other', 'poo', '2026-2'), isNull);
      expect(await cache.read('owner', 'other', '2026-2'), isNull);
      expect(await cache.read('owner', 'poo', '2027-1'), isNull);
      final preferences = SharedPreferencesAsync();
      await preferences.setString(
        'course_activity_snapshot.v1.owner.poo.2026-2',
        jsonEncode({...snapshot.toJson(), 'course_id': 'other'}),
      );
      await expectLater(
        cache.read('owner', 'poo', '2026-2'),
        throwsFormatException,
      );
    },
  );
}
