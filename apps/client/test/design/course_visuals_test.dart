import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/course_visuals.dart';
import 'package:frequencia_ufmg/design/course_identity.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

CourseRecord course(
  String id,
  String code, {
  String? nickname,
  String term = '2026-2',
}) => CourseRecord(
  id: id,
  code: code,
  name: 'Disciplina $code',
  nickname: nickname,
  workload: 60,
  term: term,
  createdAt: DateTime.utc(2026),
  updatedAt: DateTime.utc(2026),
);
void main() {
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );
  test(
    'same-prefix courses have unique stable colors across rename, reorder, removal, restart and accounts',
    () async {
      final catalog = CourseVisualCatalog();
      final courses = [
        course('cir', 'ELE065'),
        course('lab', 'ELE028'),
        course('poo', 'DCC203'),
      ];
      await catalog.update('a', courses);
      final saved = {for (final c in courses) c.code: catalog.color(c.code)};
      expect(saved.values.toSet().length, 3);
      expect(catalog.color('unknown'), isNull);
      await catalog.update('a', [
        course('poo', 'DCC203', nickname: 'POO'),
        courses[1],
        courses[0],
        course('new', 'MAT001'),
      ]);
      expect({for (final c in courses) c.code: catalog.color(c.code)}, saved);
      expect(
        catalog
            .course(id: 'canonical-other', code: 'DCC203', term: '2026-2')!
            .displayName,
        'POO',
      );
      expect(
        catalog.course(id: 'missing', code: 'DCC203', term: '2027-1'),
        isNull,
      );
      await catalog.update('a', [courses[0]]);
      final restarted = CourseVisualCatalog();
      await restarted.update('a', courses.reversed.toList());
      expect({for (final c in courses) c.code: restarted.color(c.code)}, saved);
      await restarted.update('b', [
        course('b', 'ELE065', nickname: 'Outro usuário'),
      ]);
      expect(
        restarted.course(id: 'poo', code: 'DCC203', term: '2026-2'),
        isNull,
      );
      restarted.clear();
      expect(restarted.owner, isNull);
      expect(restarted.color('ELE065'), isNull);
      await restarted.update('a', courses);
      expect({for (final c in courses) c.code: restarted.color(c.code)}, saved);
    },
  );
  test(
    'palette extends without duplicates and identifies ambiguous semesters without guessing',
    () async {
      final model = CourseVisualCatalog();
      final items = [
        for (var i = 0; i < 32; i++)
          course('c$i', 'ELE${i.toString().padLeft(3, '0')}'),
      ];
      await model.update('owner', items);
      expect(items.map((c) => model.color(c.code)).toSet().length, 32);
      final duplicate = course('duplicate', 'ELE000');
      await model.update('owner', [...items, duplicate]);
      expect(
        model.course(id: 'unknown', code: 'ELE000', term: '2026-2'),
        isNull,
      );
      expect(
        model.course(id: 'duplicate', code: 'ELE000', term: '2026-2'),
        duplicate,
      );
    },
  );
  for (final malformed in [
    '[]',
    'broken',
    '{"ELE065":"red"}',
    '{"ELE065":-1}',
    '{"ELE065":4294967296}',
    '{"":1}',
    '{"ELE065":1,"ELE028":1}',
    jsonEncode({for (var i = 0; i < 1001; i++) 'ELE$i': i}),
    jsonEncode({'x' * 33: 12}),
  ]) {
    test(
      'bad palette cannot block course presentation (${malformed.hashCode})',
      () async {
        await SharedPreferencesAsync().setString(
          'course_visuals.v1.owner',
          malformed,
        );
        final store = _Store();
        final logger = FirestoreAppLogger(
          store: store,
          currentUserId: () => 'owner',
          platform: 'web',
        );
        final model = CourseVisualCatalog();
        await model.update('owner', [course('cir', 'ELE065')], logger: logger);
        await Future<void>.delayed(Duration.zero);
        expect(model.color('ELE065'), isNotNull);
        final failure = store.items.singleWhere(
          (e) => e['operation'] == 'course_visual_cache_read',
        );
        expect(failure['errorDetails'].toString(), contains('palette_read'));
        expect(failure['correlationId'], isNotEmpty);
        expect(failure['durationMs'], isA<int>());
      },
    );
  }
  test(
    'disk read/write failures retain in-memory colors and report their exact stages',
    () async {
      final store = _Store();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'owner',
        platform: 'web',
      );
      final model = CourseVisualCatalog(preferences: _BrokenPreferences());
      await model.update('owner', [
        course('cir', 'ELE065'),
        course('lab', 'ELE028'),
      ], logger: logger);
      await Future<void>.delayed(Duration.zero);
      expect(model.color('ELE065'), isNot(model.color('ELE028')));
      expect(
        store.items
            .where((e) => e['level'] == 'error')
            .map((e) => e['operation']),
        containsAll(['course_visual_cache_read', 'course_visual_cache_write']),
      );
      await model.update('owner', [
        course('cir', 'ELE065', nickname: 'Renomeada'),
      ], logger: logger);
      expect(store.items.last['event'], 'course_visuals_updated');
    },
  );
  test(
    'late reads cannot cross users or replace a newer course snapshot',
    () async {
      final preferences = _PendingPreferences();
      final model = CourseVisualCatalog(preferences: preferences);
      final old = model.update('old', [course('old', 'ELE065')]);
      final current = model.update('new', [course('new', 'DCC203')]);
      preferences.current.complete(null);
      await current;
      preferences.old.complete('{}');
      await old;
      expect(model.owner, 'new');
      expect(model.color('ELE065'), isNull);
      expect(model.color('DCC203'), isNotNull);
    },
  );
  test('late failed reads do not replace a newer owner', () async {
    final preferences = _PendingPreferences();
    final model = CourseVisualCatalog(preferences: preferences);
    final old = model.update('old', [course('old', 'ELE065')]);
    final current = model.update('new', [course('new', 'DCC203')]);
    preferences.current.complete(null);
    await current;
    preferences.old.completeError(StateError('disk'));
    await old;
    expect(model.owner, 'new');
    expect(model.color('ELE065'), isNull);
  });
  testWidgets(
    'shared presentation reaches pushed routes and remains usable without a host',
    (tester) async {
      final model = CourseVisualCatalog();
      await model.update('owner', [
        course('cir', 'ELE065'),
        course('lab', 'ELE028'),
      ]);
      await tester.pumpWidget(
        CourseVisualHost(
          catalog: model,
          child: MaterialApp(
            home: Builder(
              builder: (context) => Scaffold(
                body: Column(
                  children: [
                    const CourseMark(code: 'ELE065'),
                    TextButton(
                      onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) =>
                              const Scaffold(body: CourseMark(code: 'ELE028')),
                        ),
                      ),
                      child: const Text('Materiais'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Materiais'));
      await tester.pumpAndSettle();
      final context = tester.element(find.byType(CourseMark).last);
      expect(
        CourseVisualHost.of(context)!.color('ELE028'),
        model.color('ELE028'),
      );
      await tester.pumpWidget(
        const MaterialApp(home: CourseMark(code: 'DCC203')),
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(
        const CourseVisualHost(
          child: MaterialApp(home: CourseMark(code: 'ELE065')),
        ),
      );
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}

class _Store implements OperationalLogStore {
  final items = <Map<String, Object?>>[];
  @override
  Future<void> add(String id, Map<String, Object?> document) async =>
      items.add(document);
}

class _BrokenPreferences extends SharedPreferencesAsync {
  @override
  Future<String?> getString(String key) async =>
      throw StateError('read unavailable');
  @override
  Future<void> setString(String key, String value) async =>
      throw StateError('write unavailable');
}

class _PendingPreferences extends SharedPreferencesAsync {
  final old = Completer<String?>(), current = Completer<String?>();
  @override
  Future<String?> getString(String key) =>
      key.endsWith('.old') ? old.future : current.future;
}
