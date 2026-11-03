import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/material_scope_cache.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  test(
    'course ownership metadata persists independently by user and discipline',
    () async {
      final cache = MaterialScopeCache();
      expect(await cache.read('alice', 'poo'), isEmpty);
      await cache.write('alice', 'poo', {'2026-2/3701/', '2026-2/metaturma/'});
      expect(await MaterialScopeCache().read('alice', 'poo'), {
        '2026-2/3701/',
        '2026-2/metaturma/',
      });
      expect(await cache.read('bob', 'poo'), isEmpty);
      expect(await cache.read('alice', 'calc'), isEmpty);
    },
  );
  test(
    'corrupt or unbounded metadata is rejected rather than associating files incorrectly',
    () async {
      final prefs = SharedPreferencesAsync();
      final cache = MaterialScopeCache(preferences: prefs);
      for (final value in [
        '{}',
        '[3]',
        '["https://example.test/private"]',
        '["2026-3/7/"]',
      ]) {
        await prefs.setString('material_scope.v1.alice.poo', value);
        await expectLater(cache.read('alice', 'poo'), throwsFormatException);
      }
      await expectLater(
        cache.write('alice', 'poo', {
          for (var i = 0; i < 1001; i++) '2026-2/$i/',
        }),
        throwsFormatException,
      );
      await cache.write('alice', 'poo', {});
      expect(await cache.read('alice', 'poo'), isEmpty);
    },
  );
}
