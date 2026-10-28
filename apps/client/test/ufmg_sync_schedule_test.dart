import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/ufmg_sync_schedule.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  test(
    'academic cadence is account scoped and independent of enrollment cadence',
    () async {
      SharedPreferencesAsyncPlatform.instance =
          InMemorySharedPreferencesAsync.empty();
      final now = DateTime.utc(2026, 10, 28);
      final enrollment = UFMGSyncSchedule(now: () => now);
      final academic = UFMGSyncSchedule.academic(now: () => now);
      await academic.record('user1', now.add(const Duration(hours: 6)));
      expect(await academic.isDue('user1'), isFalse);
      expect(await enrollment.isDue('user1'), isTrue);
      expect(await academic.isDue('user2'), isTrue);
    },
  );

  setUp(() {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
  });

  test('is due until a future server schedule is recorded', () async {
    var now = DateTime.utc(2026, 10, 13, 12);
    final schedule = UFMGSyncSchedule(now: () => now);

    expect(await schedule.isDue('user-1'), isTrue);

    await schedule.record('user-1', DateTime.utc(2026, 12, 6));

    expect(await schedule.isDue('user-1'), isFalse);
    expect(await schedule.isDue('user-2'), isTrue);
    now = DateTime.utc(2026, 12, 6);
    expect(await schedule.isDue('user-1'), isTrue);
  });

  test(
    'rejects non-future deadlines and recovers corrupted local data',
    () async {
      final now = DateTime.utc(2026, 10, 13, 12);
      final preferences = SharedPreferencesAsync();
      final schedule = UFMGSyncSchedule(
        preferences: preferences,
        now: () => now,
      );

      await expectLater(schedule.record('user-1', now), throwsArgumentError);

      final encoded = base64Url
          .encode(utf8.encode('user-1'))
          .replaceAll('=', '');
      await preferences.setString('ufmg_sync.v1.$encoded', 'broken');

      expect(await schedule.isDue('user-1'), isTrue);
      expect(await preferences.getString('ufmg_sync.v1.$encoded'), isNull);
    },
  );
}
