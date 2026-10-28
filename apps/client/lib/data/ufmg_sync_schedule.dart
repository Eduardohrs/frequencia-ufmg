import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

typedef UtcNow = DateTime Function();

abstract interface class UFMGSyncScheduleGateway {
  Future<bool> isDue(String userId);

  Future<void> record(String userId, DateTime nextAutomaticSyncAt);
}

final class UFMGSyncSchedule implements UFMGSyncScheduleGateway {
  UFMGSyncSchedule({SharedPreferencesAsync? preferences, UtcNow? now})
    : _preferences = preferences ?? SharedPreferencesAsync(),
      _now = now ?? DateTime.now,
      _storagePrefix = 'ufmg_sync.v1.';

  UFMGSyncSchedule.academic({SharedPreferencesAsync? preferences, UtcNow? now})
    : _preferences = preferences ?? SharedPreferencesAsync(),
      _now = now ?? DateTime.now,
      _storagePrefix = 'academic_sync.v1.';
  final String _storagePrefix;

  final SharedPreferencesAsync _preferences;
  final UtcNow _now;

  @override
  Future<bool> isDue(String userId) async {
    final key = _key(userId);
    final saved = await _preferences.getString(key);
    if (saved == null) return true;
    final next = DateTime.tryParse(saved);
    if (next == null || !next.isUtc) {
      await _preferences.remove(key);
      return true;
    }
    return !_now().toUtc().isBefore(next);
  }

  @override
  Future<void> record(String userId, DateTime nextAutomaticSyncAt) async {
    final next = nextAutomaticSyncAt.toUtc();
    if (!next.isAfter(_now().toUtc())) {
      throw ArgumentError.value(
        nextAutomaticSyncAt,
        'nextAutomaticSyncAt',
        'must be in the future',
      );
    }
    await _preferences.setString(_key(userId), next.toIso8601String());
  }

  String _key(String userId) =>
      '$_storagePrefix${base64Url.encode(utf8.encode(userId)).replaceAll('=', '')}';
}
