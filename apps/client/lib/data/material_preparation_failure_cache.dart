import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// Persisted preparation failures (before any native queue entry), keyed by
/// user. Only course/module identifiers and failure codes are stored — never
/// download URLs, cookies or tokens.
final class MaterialPreparationFailureCache {
  MaterialPreparationFailureCache({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  final SharedPreferencesAsync _preferences;

  String _key(String user) => 'material_preparation_failures.v1.$user';

  Future<List<MaterialPreparationFailureRecord>> read(String user) async {
    final stored = await _preferences.getString(_key(user));
    if (stored == null) return const [];
    final decoded = jsonDecode(stored);
    if (decoded is! List || decoded.length > 200) {
      throw const FormatException('Invalid preparation failure list');
    }
    return [
      for (final item in decoded)
        MaterialPreparationFailureRecord.fromJson(item),
    ];
  }

  Future<void> record(
    String user,
    MaterialPreparationFailureRecord entry,
  ) async {
    final current = await read(user);
    final kept = current
        .where((item) => item.materialId != entry.materialId)
        .toList();
    kept.add(entry);
    await _preferences.setString(
      _key(user),
      jsonEncode([for (final item in kept) item.toJson()]),
    );
  }

  Future<void> remove(String user, String materialId) async {
    final current = await read(user);
    final kept = current
        .where((item) => item.materialId != materialId)
        .toList();
    if (kept.length == current.length) return;
    if (kept.isEmpty) {
      await _preferences.remove(_key(user));
    } else {
      await _preferences.setString(
        _key(user),
        jsonEncode([for (final item in kept) item.toJson()]),
      );
    }
  }

  Future<void> clear(String user) async {
    await _preferences.remove(_key(user));
  }
}

final class MaterialPreparationFailureRecord {
  const MaterialPreparationFailureRecord({
    required this.materialId,
    required this.materialName,
    required this.term,
    required this.moodleCourseId,
    required this.sourceId,
    required this.courseCode,
    required this.code,
    required this.at,
  });

  factory MaterialPreparationFailureRecord.fromJson(Object? value) {
    final json = value is Map<String, Object?> ? value : const {};
    String field(String key) {
      final v = json[key];
      if (v is! String || v.isEmpty || v.length > 512) {
        throw const FormatException('Invalid preparation failure field');
      }
      return v;
    }

    final materialId = field('material_id');
    final term = field('term');
    final courseId = field('moodle_course_id');
    final sourceId = field('source_id');
    if (materialId != '$term/$courseId/$sourceId') {
      throw const FormatException('Preparation failure id mismatch');
    }
    if (!RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
        !RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(courseId) ||
        !RegExp(r'^[1-9][0-9]{0,9}$').hasMatch(sourceId)) {
      throw const FormatException('Invalid preparation failure identifiers');
    }
    return MaterialPreparationFailureRecord(
      materialId: materialId,
      materialName: field('material_name'),
      term: term,
      moodleCourseId: courseId,
      sourceId: sourceId,
      courseCode: field('course_code'),
      code: field('code'),
      at: field('at'),
    );
  }

  final String materialId;
  final String materialName;
  final String term;
  final String moodleCourseId;
  final String sourceId;
  final String courseCode;
  final String code;
  final String at;

  Map<String, Object> toJson() => {
    'material_id': materialId,
    'material_name': materialName,
    'term': term,
    'moodle_course_id': moodleCourseId,
    'source_id': sourceId,
    'course_code': courseCode,
    'code': code,
    'at': at,
  };
}
