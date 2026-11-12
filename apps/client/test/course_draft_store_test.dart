import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/course_draft_store.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  setUp(() {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
  });

  group('SharedPreferencesCourseDraftStore', () {
    test('read returns null when nothing was saved', () async {
      final store = SharedPreferencesCourseDraftStore();
      expect(await store.read('user-1', 'course-create'), isNull);
    });

    test(
      'save then read round-trips the form data and the last error',
      () async {
        final store = SharedPreferencesCourseDraftStore();
        await store.save('user-1', 'course-create', {
          'code': 'DCC203',
          'name': 'POO',
          'attempts': 2,
        }, lastError: 'permission-denied');

        final draft = await store.read('user-1', 'course-create');
        expect(draft, {'code': 'DCC203', 'name': 'POO', 'attempts': 2});

        final raw = await SharedPreferencesAsync().getString(
          _key('user-1', 'course-create'),
        );
        final payload = jsonDecode(raw!) as Map<String, Object?>;
        expect(payload['form_data'], {
          'code': 'DCC203',
          'name': 'POO',
          'attempts': 2,
        });
        expect(payload['last_error'], 'permission-denied');
      },
    );

    test('save without a last error stores a null error', () async {
      final store = SharedPreferencesCourseDraftStore();
      await store.save('user-1', 'course-create', {'code': 'DCC203'});

      final raw = await SharedPreferencesAsync().getString(
        _key('user-1', 'course-create'),
      );
      final payload = jsonDecode(raw!) as Map<String, Object?>;
      expect(payload['form_data'], {'code': 'DCC203'});
      expect(payload['last_error'], isNull);
      expect(await store.read('user-1', 'course-create'), {'code': 'DCC203'});
    });

    test('drafts are isolated per user', () async {
      final store = SharedPreferencesCourseDraftStore();
      await store.save('user-1', 'course-create', {'code': 'DCC203'});
      await store.save('user-2', 'course-create', {'code': 'MAT001'});

      expect((await store.read('user-1', 'course-create'))!['code'], 'DCC203');
      expect((await store.read('user-2', 'course-create'))!['code'], 'MAT001');
    });

    test('drafts are isolated per session', () async {
      final store = SharedPreferencesCourseDraftStore();
      await store.save('user-1', 'course-create', {'code': 'DCC203'});
      await store.save('user-1', 'other-session', {'code': 'MAT001'});

      expect((await store.read('user-1', 'course-create'))!['code'], 'DCC203');
      expect((await store.read('user-1', 'other-session'))!['code'], 'MAT001');
    });

    test(
      'save overwrites the previous draft for the same user and session',
      () async {
        final store = SharedPreferencesCourseDraftStore();
        await store.save('user-1', 'course-create', {'code': 'DCC203'});
        await store.save('user-1', 'course-create', {
          'code': 'DCC204',
        }, lastError: 'unavailable');

        expect(await store.read('user-1', 'course-create'), {'code': 'DCC204'});
      },
    );

    test('clear removes only the matching user and session', () async {
      final store = SharedPreferencesCourseDraftStore();
      await store.save('user-1', 'course-create', {'code': 'DCC203'});
      await store.save('user-1', 'other-session', {'code': 'MAT001'});
      await store.save('user-2', 'course-create', {'code': 'DCC205'});

      await store.clear('user-1', 'course-create');

      expect(await store.read('user-1', 'course-create'), isNull);
      expect(await store.read('user-1', 'other-session'), {'code': 'MAT001'});
      expect(await store.read('user-2', 'course-create'), {'code': 'DCC205'});
    });

    test('clear is a no-op when nothing was saved', () async {
      final store = SharedPreferencesCourseDraftStore();
      await store.clear('user-1', 'course-create');
      expect(await store.read('user-1', 'course-create'), isNull);
    });

    test(
      'keys use the prefixed base64Url encoding of user and session',
      () async {
        final store = SharedPreferencesCourseDraftStore();
        await store.save('user/1', 'sess=2', {'code': 'X'});

        final preferences = SharedPreferencesAsync();
        final raw = await preferences.getString(_key('user/1', 'sess=2'));
        expect(raw, isNotNull);
        expect(
          jsonDecode(raw!) as Map,
          containsPair('form_data', {'code': 'X'}),
        );
        expect(
          await preferences.getString('course_draft.v1.user_1.sess_2'),
          isNull,
        );
      },
    );

    test('read returns null when the stored value is not valid JSON', () async {
      final store = SharedPreferencesCourseDraftStore();
      await SharedPreferencesAsync().setString(
        _key('user-1', 'course-create'),
        'not-json{',
      );
      expect(await store.read('user-1', 'course-create'), isNull);
    });

    test('read returns null when the payload is not a JSON object', () async {
      final store = SharedPreferencesCourseDraftStore();
      await SharedPreferencesAsync().setString(
        _key('user-1', 'course-create'),
        jsonEncode('just a string'),
      );
      expect(await store.read('user-1', 'course-create'), isNull);
    });

    test('read returns null when form_data is not a map', () async {
      final store = SharedPreferencesCourseDraftStore();
      await SharedPreferencesAsync().setString(
        _key('user-1', 'course-create'),
        jsonEncode(<String, Object?>{'form_data': 42}),
      );
      expect(await store.read('user-1', 'course-create'), isNull);
    });
  });
}

String _part(String value) =>
    base64Url.encode(utf8.encode(value)).replaceAll('=', '');

String _key(String userId, String sessionId) =>
    'course_draft.v1.${_part(userId)}.${_part(sessionId)}';
