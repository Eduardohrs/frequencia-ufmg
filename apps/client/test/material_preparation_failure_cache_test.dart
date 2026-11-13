import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/material_preparation_failure_cache.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:shared_preferences_platform_interface/types.dart';

void main() {
  setUp(() {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
  });

  MaterialPreparationFailureRecord record(
    String id, {
    String code = 'unavailable',
    String name = 'Cronograma',
  }) {
    final parts = id.split('/');
    return MaterialPreparationFailureRecord(
      materialId: id,
      materialName: name,
      term: parts[0],
      moodleCourseId: parts[1],
      sourceId: parts[2],
      courseCode: 'DCC203',
      code: code,
      at: '2026-11-12T10:00:00.000Z',
    );
  }

  test('starts empty and round-trips records', () async {
    final cache = MaterialPreparationFailureCache();
    expect(await cache.read('user-1'), isEmpty);

    await cache.record('user-1', record('2026-2/3701/102'));
    await cache.record('user-1', record('2026-2/3701/104', name: 'Exercícios'));
    var stored = await cache.read('user-1');
    expect(stored.map((r) => r.materialId), [
      '2026-2/3701/102',
      '2026-2/3701/104',
    ]);
    expect(stored.first.code, 'unavailable');
    expect(stored.first.materialName, 'Cronograma');

    // record novamente no mesmo id substitui
    await cache.record('user-1', record('2026-2/3701/102', code: 'timeout'));
    stored = await cache.read('user-1');
    expect(stored, hasLength(2));
    expect(
      stored.singleWhere((r) => r.materialId == '2026-2/3701/102').code,
      'timeout',
    );

    // remove apaga só o alvo e limpa a chave quando vazio
    await cache.remove('user-1', '2026-2/3701/104');
    expect((await cache.read('user-1')).map((r) => r.materialId), [
      '2026-2/3701/102',
    ]);
    await cache.remove('user-1', '2026-2/3701/102');
    expect(await cache.read('user-1'), isEmpty);

    await cache.record('user-1', record('2026-2/3701/102'));
    await cache.clear('user-1');
    expect(await cache.read('user-1'), isEmpty);
  });

  test('keeps users isolated', () async {
    final cache = MaterialPreparationFailureCache();
    await cache.record('user-1', record('2026-2/3701/102'));
    expect(await cache.read('user-2'), isEmpty);
  });

  test('rejects malformed payloads', () async {
    final prefs = InMemorySharedPreferencesAsync.empty();
    SharedPreferencesAsyncPlatform.instance = prefs;
    await prefs.setString(
      'material_preparation_failures.v1.user-1',
      '[{"material_id":"2026-2/3701/102","material_name":"x","term":"2026-1","moodle_course_id":"3701","source_id":"102","course_code":"DCC203","code":"unavailable","at":"2026-11-12T10:00:00.000Z"}]',
      const SharedPreferencesOptions(),
    );
    final cache = MaterialPreparationFailureCache();
    // term não bate com o id → inválido
    expect(() => cache.read('user-1'), throwsFormatException);
  });
}
