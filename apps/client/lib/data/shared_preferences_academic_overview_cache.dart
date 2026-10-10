import 'package:shared_preferences/shared_preferences.dart';

import 'cached_academic_overview_repository.dart';

final class SharedPreferencesAcademicOverviewCache
    implements AcademicOverviewCache {
  SharedPreferencesAcademicOverviewCache({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  static const _keyPrefix = 'academic_overview.v1.';

  final SharedPreferencesAsync _preferences;

  @override
  Future<String?> read(String userId) =>
      _preferences.getString('$_keyPrefix$userId');

  @override
  Future<void> write(String userId, String value) =>
      _preferences.setString('$_keyPrefix$userId', value);

  @override
  Future<void> remove(String userId) =>
      _preferences.remove('$_keyPrefix$userId');
}
