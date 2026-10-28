import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../backend/python_backend_transport.dart';

/// Account/course/semester scoped content only. Download credentials are rejected
/// by the snapshot model and never enter preferences.
class CourseActivitySnapshotCache {
  CourseActivitySnapshotCache({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();
  final SharedPreferencesAsync _preferences;
  String _key(String user, String course, String term) =>
      'course_activity_snapshot.v1.${Uri.encodeComponent(user)}.${Uri.encodeComponent(course)}.$term';
  Future<PythonCourseActivitySnapshot?> read(
    String user,
    String course,
    String term,
  ) async {
    final value = await _preferences.getString(_key(user, course, term));
    if (value == null) return null;
    final snapshot = PythonCourseActivitySnapshot.fromJson(
      Map<String, Object?>.from(jsonDecode(value) as Map),
    );
    if (snapshot.courseId != course || snapshot.term != term) {
      throw const FormatException('Snapshot scope mismatch');
    }
    return snapshot;
  }

  Future<void> write(String user, PythonCourseActivitySnapshot snapshot) =>
      _preferences.setString(
        _key(user, snapshot.courseId, snapshot.term),
        jsonEncode(snapshot.toJson()),
      );
}
