import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Local persistence for course-create form drafts, scoped per user and per
/// editing session, so a refused registration can be retried with the same
/// values even when the backend is unreachable.
abstract interface class CourseDraftStore {
  /// Stores [formData] locally for [userId] under [sessionId].
  Future<void> save(
    String userId,
    String sessionId,
    Map<String, Object?> formData, {
    String? lastError,
  });

  /// Returns the locally stored form data, or `null` when there is none.
  Future<Map<String, Object?>?> read(String userId, String sessionId);

  /// Removes the locally stored draft for [userId] under [sessionId].
  Future<void> clear(String userId, String sessionId);
}

final class SharedPreferencesCourseDraftStore implements CourseDraftStore {
  SharedPreferencesCourseDraftStore({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  static const _storagePrefix = 'course_draft.v1.';

  final SharedPreferencesAsync _preferences;

  @override
  Future<void> save(
    String userId,
    String sessionId,
    Map<String, Object?> formData, {
    String? lastError,
  }) => _preferences.setString(
    _key(userId, sessionId),
    jsonEncode(<String, Object?>{
      'form_data': formData,
      'last_error': lastError,
    }),
  );

  @override
  Future<Map<String, Object?>?> read(String userId, String sessionId) async {
    final raw = await _preferences.getString(_key(userId, sessionId));
    if (raw == null) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      final formData = decoded['form_data'];
      if (formData is! Map) return null;
      return Map<String, Object?>.from(formData);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> clear(String userId, String sessionId) =>
      _preferences.remove(_key(userId, sessionId));

  static String _key(String userId, String sessionId) =>
      '$_storagePrefix${_part(userId)}.${_part(sessionId)}';

  static String _part(String value) =>
      base64Url.encode(utf8.encode(value)).replaceAll('=', '');
}
