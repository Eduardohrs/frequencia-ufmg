import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/identity_verification_cache.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  setUp(() {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
  });

  test('is stale until a verification is recorded for the same user', () async {
    var now = DateTime.utc(2026, 11, 13, 12);
    final cache = SharedPreferencesIdentityVerificationCache(now: () => now);

    expect(await cache.isFresh('user-1'), isFalse);

    await cache.record('user-1', now);

    expect(await cache.isFresh('user-1'), isTrue);
    expect(await cache.isFresh('user-2'), isFalse);

    now = now.add(const Duration(hours: 12));
    expect(await cache.isFresh('user-1'), isFalse);

    now = now.add(const Duration(hours: 11, minutes: 59));
    await cache.record('user-1', now);
    now = now.add(const Duration(hours: 11, minutes: 59));
    expect(await cache.isFresh('user-1'), isTrue);
  });

  test('recovers corrupted local data as stale', () async {
    final now = DateTime.utc(2026, 11, 13, 12);
    final preferences = SharedPreferencesAsync();
    final cache = SharedPreferencesIdentityVerificationCache(
      preferences: preferences,
      now: () => now,
    );

    final encoded = base64Url.encode(utf8.encode('user-1')).replaceAll('=', '');
    await preferences.setString('identity_verified.v1.$encoded', 'broken');
    expect(await cache.isFresh('user-1'), isFalse);
    expect(
      await preferences.getString('identity_verified.v1.$encoded'),
      isNull,
    );

    await preferences.setString(
      'identity_verified.v1.$encoded',
      '2026-11-13T12:00:00',
    );
    expect(await cache.isFresh('user-1'), isFalse);
  });

  test('custom ttl bounds freshness', () async {
    var now = DateTime.utc(2026, 11, 13, 12);
    final cache = SharedPreferencesIdentityVerificationCache(
      now: () => now,
      ttl: const Duration(minutes: 30),
    );
    await cache.record('user-1', now);
    now = now.add(const Duration(minutes: 29));
    expect(await cache.isFresh('user-1'), isTrue);
    now = now.add(const Duration(minutes: 2));
    expect(await cache.isFresh('user-1'), isFalse);
  });
}
