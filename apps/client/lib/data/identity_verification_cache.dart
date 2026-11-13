import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

typedef UtcNow = DateTime Function();

/// Persists the last successful backend identity probe per user so reopening
/// the app within [ttl] does not fire a redundant `/v1/identity` execution.
abstract interface class IdentityVerificationCache {
  Future<bool> isFresh(String userId);

  Future<void> record(String userId, DateTime verifiedAt);
}

final class SharedPreferencesIdentityVerificationCache
    implements IdentityVerificationCache {
  SharedPreferencesIdentityVerificationCache({
    SharedPreferencesAsync? preferences,
    UtcNow? now,
    Duration? ttl,
  }) : _preferences = preferences ?? SharedPreferencesAsync(),
       _now = now ?? DateTime.now,
       _ttl = ttl ?? const Duration(hours: 12);

  static const _storagePrefix = 'identity_verified.v1.';

  final SharedPreferencesAsync _preferences;
  final UtcNow _now;
  final Duration _ttl;

  @override
  Future<bool> isFresh(String userId) async {
    final saved = await _preferences.getString(_key(userId));
    if (saved == null) return false;
    final verifiedAt = DateTime.tryParse(saved);
    if (verifiedAt == null || !verifiedAt.isUtc) {
      await _preferences.remove(_key(userId));
      return false;
    }
    return _now().toUtc().difference(verifiedAt) < _ttl;
  }

  @override
  Future<void> record(String userId, DateTime verifiedAt) async {
    await _preferences.setString(
      _key(userId),
      verifiedAt.toUtc().toIso8601String(),
    );
  }

  String _key(String userId) =>
      '$_storagePrefix${base64Url.encode(utf8.encode(userId)).replaceAll('=', '')}';
}
