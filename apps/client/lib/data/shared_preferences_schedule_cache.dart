import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../backend/cached_schedule_gateway.dart';

final class SharedPreferencesScheduleCache implements ScheduleCache {
  SharedPreferencesScheduleCache({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  static const _keyPrefix = 'academic_schedule.v1.';

  final SharedPreferencesAsync _preferences;

  @override
  Future<String?> read(String userId, String courseId) =>
      _preferences.getString(_key(userId, courseId));

  @override
  Future<void> write(String userId, String courseId, String value) =>
      _preferences.setString(_key(userId, courseId), value);

  @override
  Future<void> remove(String userId, String courseId) =>
      _preferences.remove(_key(userId, courseId));

  static String _key(String userId, String courseId) =>
      '$_keyPrefix${_part(userId)}.${_part(courseId)}';

  static String _part(String value) =>
      base64Url.encode(utf8.encode(value)).replaceAll('=', '');
}
