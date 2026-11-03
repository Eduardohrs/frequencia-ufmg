import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Only course/module identifiers; never download URLs, cookies or tokens.
final class MaterialScopeCache {
  MaterialScopeCache({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();
  final SharedPreferencesAsync _preferences;
  String _key(String user, String course) => 'material_scope.v1.$user.$course';

  Future<Set<String>> read(String user, String course) async {
    final stored = await _preferences.getString(_key(user, course));
    return stored == null ? {} : _validate(jsonDecode(stored));
  }

  Future<void> write(String user, String course, Set<String> prefixes) async {
    final valid = _validate(prefixes.toList());
    await _preferences.setString(
      _key(user, course),
      jsonEncode(valid.toList()),
    );
  }

  Set<String> _validate(Object? value) {
    if (value is! List ||
        value.length > 1000 ||
        value.any(
          (item) =>
              item is! String ||
              !RegExp(r'^\d{4}-[12]/[^/\s]{1,128}/$').hasMatch(item),
        )) {
      throw const FormatException('Invalid material scope');
    }
    return value.cast<String>().toSet();
  }
}
