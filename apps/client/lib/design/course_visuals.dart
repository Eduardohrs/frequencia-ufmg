import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../data/academic_records.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../observability/operation_diagnostics.dart';

/// Device-local presentation only. Academic records and official course codes never change.
class CourseVisualCatalog extends ChangeNotifier {
  CourseVisualCatalog({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();
  final SharedPreferencesAsync _preferences;
  String? owner;
  int _version = 0;
  bool _loaded = false;
  Map<String, int> _colors = {};
  List<CourseRecord> _courses = [];
  static const _palette = [
    0xFF2667A8,
    0xFFA45725,
    0xFF7952A3,
    0xFF237B70,
    0xFFA13D64,
    0xFF527528,
    0xFF936820,
    0xFF46649C,
    0xFF924432,
    0xFF516A76,
    0xFF6B5B8F,
    0xFF15778B,
  ];
  @override
  void dispose() {
    _version++;
    super.dispose();
  }

  String _code(String value) => value.trim().toUpperCase();
  Color? color(String code) {
    final value = _colors[_code(code)];
    return value == null ? null : Color(value);
  }

  CourseRecord? course({
    required String id,
    required String code,
    String? term,
  }) {
    final matches = _courses
        .where(
          (c) =>
              (term == null || c.term == term) && _code(c.code) == _code(code),
        )
        .toList();
    return matches.where((c) => c.id == id).firstOrNull ??
        (matches.length == 1 ? matches.single : null);
  }

  void clear() {
    _version++;
    owner = null;
    _loaded = false;
    _colors = {};
    _courses = [];
    notifyListeners();
  }

  Future<void> update(
    String user,
    List<CourseRecord> courses, {
    AppLogger? logger,
  }) async {
    final version = ++_version;
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('course_visuals'),
      'stage': 'palette_read',
      'course_count': courses.length,
    };
    if (owner != user) {
      owner = user;
      _loaded = false;
      _colors = {};
      _courses = [];
    }
    final key = 'course_visuals.v1.${Uri.encodeComponent(user)}';
    if (!_loaded) {
      try {
        final stored = await _preferences.getString(key);
        final value = stored == null ? <String, dynamic>{} : jsonDecode(stored);
        if (value is! Map ||
            value.length > 1000 ||
            value.entries.any(
              (e) =>
                  e.key is! String ||
                  (e.key as String).isEmpty ||
                  (e.key as String).length > 32 ||
                  e.value is! int ||
                  (e.value as int) < 0 ||
                  (e.value as int) > 0xFFFFFFFF,
            ) ||
            value.values.toSet().length != value.length) {
          throw const FormatException('Invalid course palette');
        }
        if (version != _version) return;
        _colors = Map<String, int>.from(value);
      } catch (error, stack) {
        if (version != _version) return;
        if (logger != null) {
          recordOperationalFailure(
            logger,
            error,
            stack,
            'course_visual_cache_read',
            {...fields, 'duration_ms': watch.elapsedMilliseconds},
            failureCode: 'course_palette_cache_failed',
          );
        }
      }
      if (version != _version) return;
      _loaded = true;
    }
    final codes = courses.map((c) => _code(c.code)).toSet().toList()..sort();
    var changed = false;
    final used = _colors.values.toSet();
    for (final code in codes) {
      if (_colors.containsKey(code)) continue;
      var slot = 0;
      int candidate;
      do {
        candidate = slot < _palette.length
            ? _palette[slot]
            : HSLColor.fromAHSL(
                1,
                (slot * 137.508) % 360,
                .56,
                .42,
              ).toColor().toARGB32();
        slot++;
      } while (used.contains(candidate));
      changed = true;
      _colors[code] = candidate;
      used.add(candidate);
    }
    _courses = List.of(courses);
    notifyListeners();
    if (!changed) {
      if (logger != null) {
        emitOperationalEvent(logger, 'course_visuals_updated', {
          ...fields,
          'stage': 'palette_cached',
          'color_count': _colors.length,
          'duration_ms': watch.elapsedMilliseconds,
        });
      }
      return;
    }
    try {
      await _preferences.setString(key, jsonEncode(_colors));
      if (logger != null) {
        emitOperationalEvent(logger, 'course_visuals_updated', {
          ...fields,
          'stage': 'palette_write',
          'color_count': _colors.length,
          'duration_ms': watch.elapsedMilliseconds,
        });
      }
    } catch (error, stack) {
      if (logger != null) {
        recordOperationalFailure(
          logger,
          error,
          stack,
          'course_visual_cache_write',
          {
            ...fields,
            'stage': 'palette_write',
            'duration_ms': watch.elapsedMilliseconds,
          },
          failureCode: 'course_palette_cache_failed',
        );
      }
    }
  }
}

class CourseVisualHost extends StatefulWidget {
  const CourseVisualHost({required this.child, this.catalog, super.key});
  final Widget child;
  final CourseVisualCatalog? catalog;
  static CourseVisualCatalog? of(BuildContext context, {bool listen = true}) =>
      (listen
              ? context.dependOnInheritedWidgetOfExactType<_VisualScope>()
              : context.getInheritedWidgetOfExactType<_VisualScope>())
          ?.notifier;
  @override
  State<CourseVisualHost> createState() => _CourseVisualHostState();
}

class _CourseVisualHostState extends State<CourseVisualHost> {
  late final catalog = widget.catalog ?? CourseVisualCatalog();
  @override
  Widget build(BuildContext context) =>
      _VisualScope(notifier: catalog, child: widget.child);
  @override
  void dispose() {
    if (widget.catalog == null) catalog.dispose();
    super.dispose();
  }
}

class _VisualScope extends InheritedNotifier<CourseVisualCatalog> {
  const _VisualScope({required super.notifier, required super.child});
}

Color courseColor(BuildContext context, String code, Color fallback) =>
    CourseVisualHost.of(context)?.color(code) ?? fallback;
