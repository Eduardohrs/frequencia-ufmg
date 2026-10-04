import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  group('PythonBackendSettings', () {
    test('keeps the backend disabled without requiring an endpoint', () {
      const settings = PythonBackendSettings(enabled: false, endpoint: '');

      expect(settings.endpointUri, isNull);
    });

    test('accepts an HTTPS origin and local development origins', () {
      for (final endpoint in [
        'https://backend.example',
        'http://localhost:8080',
        'http://127.0.0.1:8080',
      ]) {
        final settings = PythonBackendSettings(
          enabled: true,
          endpoint: endpoint,
        );

        expect(settings.endpointUri.toString(), endpoint);
      }
    });

    test('rejects unsafe or ambiguous enabled endpoints', () {
      for (final endpoint in [
        '',
        'http://backend.example',
        'https://user:password@backend.example',
        'https://backend.example/path',
        'https://backend.example?query=yes',
        'https://backend.example#fragment',
      ]) {
        expect(
          () => PythonBackendSettings(
            enabled: true,
            endpoint: endpoint,
          ).endpointUri,
          throwsArgumentError,
        );
      }
    });
  });

  test(
    'sends fresh Firebase credentials in headers and accepts identity',
    () async {
      final tokens = _Tokens();
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: MockClient((request) async {
          captured = request;
          return http.Response(jsonEncode({'authenticated': true}), 200);
        }),
      );

      await transport.verifyIdentity();

      expect(captured.method, 'GET');
      expect(captured.url, Uri.parse('https://backend.example/v1/identity'));
      expect(captured.headers['Authorization'], 'Bearer id-1-cached');
      expect(captured.headers['X-Firebase-AppCheck'], 'app-1');
      expect(tokens.idTokenRefreshes, [false]);
      expect(tokens.appCheckCalls, 1);
    },
  );

  test('default timeout tolerates an Appwrite cold start', () {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((_) async => http.Response('{}', 200)),
    );

    expect(transport.timeout, const Duration(seconds: 30));
  });

  test(
    'posts attendance input and accepts the authoritative decision',
    () async {
      final tokens = _Tokens();
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'status': 'chegou_atrasado', 'absences': 1}),
            200,
          );
        }),
      );

      final decision = await transport.evaluateAttendanceStatus(
        lessons: 2,
        calls: 2,
        status: 'chegou_atrasado',
      );

      expect(captured.method, 'POST');
      expect(
        captured.url,
        Uri.parse('https://backend.example/v1/attendance/evaluate'),
      );
      expect(captured.headers['content-type'], 'application/json');
      expect(jsonDecode(captured.body), {
        'lessons': 2,
        'calls': 2,
        'status': 'chegou_atrasado',
      });
      expect(decision.status, 'chegou_atrasado');
      expect(decision.absences, 1);
    },
  );

  test('rejects a malformed authoritative attendance decision', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'status': 'chegou_atrasado', 'absences': 3}),
          200,
        ),
      ),
    );

    await expectLater(
      transport.evaluateAttendanceStatus(
        lessons: 2,
        calls: 2,
        status: 'chegou_atrasado',
      ),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

  test(
    'lists, saves, and deletes courses through authenticated REST',
    () async {
      final requests = <http.Request>[];
      final courseJson = {
        'id': 'course-1',
        'code': 'DCC203',
        'name': 'POO',
        'workload': 1,
        'term': '2026-2',
        'starts_on': null,
        'ends_on': null,
        'created_at': '2026-10-04T12:00:00Z',
        'updated_at': '2026-10-04T12:00:00Z',
      };
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          requests.add(request);
          return switch (request.method) {
            'GET' => http.Response(
              jsonEncode({
                'courses': [courseJson],
              }),
              200,
            ),
            'PUT' => http.Response(jsonEncode({'course': courseJson}), 200),
            'DELETE' => http.Response(jsonEncode({'deleted': true}), 200),
            _ => http.Response('{}', 500),
          };
        }),
      );
      final course = PythonCourse.fromJson(courseJson);

      expect(course.toJson()['id'], 'course-1');
      expect(
        PythonCourse.fromJson({
          ...courseJson,
          'starts_on': '2026-08-01T00:00:00Z',
          'ends_on': '2026-12-01T00:00:00Z',
        }).startsOn,
        DateTime.utc(2026, 8),
      );

      final listed = await transport.listCourses();
      final saved = await transport.saveCourse(course);
      await transport.deleteCourse('course-1');

      expect(listed.single.code, 'DCC203');
      expect(saved.id, 'course-1');
      expect(requests.map((request) => request.method), [
        'GET',
        'PUT',
        'DELETE',
      ]);
      expect(requests[1].url.path, '/v1/courses/course-1');
      expect(jsonDecode(requests[1].body), isNot(contains('id')));
      expect(requests[2].url.path, '/v1/courses/course-1');
    },
  );

  test('rejects malformed course responses and unsafe ids', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'courses': [{}],
          }),
          200,
        ),
      ),
    );

    await expectLater(
      transport.listCourses(),
      throwsA(isA<PythonBackendException>()),
    );
    await expectLater(
      transport.deleteCourse('bad/id'),
      throwsA(isA<ArgumentError>()),
    );
    final invalidRange = {
      'id': 'course-1',
      'code': 'DCC203',
      'name': 'POO',
      'workload': 1,
      'term': '2026-2',
      'starts_on': '2026-12-01T00:00:00Z',
      'ends_on': '2026-08-01T00:00:00Z',
      'created_at': '2026-10-04T12:00:00Z',
      'updated_at': '2026-10-04T12:00:00Z',
    };
    expect(() => PythonCourse.fromJson(invalidRange), throwsFormatException);
  });

  test('refreshes both credentials once after unauthorized response', () async {
    final tokens = _Tokens();
    final requests = <http.Request>[];
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: tokens,
      client: MockClient((request) async {
        requests.add(request);
        if (requests.length == 1) {
          return http.Response(jsonEncode({'error': 'unauthorized'}), 401);
        }
        return http.Response(jsonEncode({'authenticated': true}), 200);
      }),
    );

    await transport.verifyIdentity();

    expect(tokens.idTokenRefreshes, [false, true]);
    expect(tokens.appCheckCalls, 2);
    expect(requests[1].headers['Authorization'], 'Bearer id-2-fresh');
    expect(requests[1].headers['X-Firebase-AppCheck'], 'app-2');
  });

  test('retries replay once with a new limited-use token', () async {
    final tokens = _Tokens();
    final requests = <http.Request>[];
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: tokens,
      client: MockClient((request) async {
        requests.add(request);
        if (requests.length == 1) {
          return http.Response(
            jsonEncode({'error': 'app_check_replayed'}),
            409,
          );
        }
        return http.Response(jsonEncode({'authenticated': true}), 200);
      }),
    );

    await transport.verifyIdentity();

    expect(tokens.idTokenRefreshes, [false, false]);
    expect(tokens.appCheckCalls, 2);
    expect(requests[1].headers['X-Firebase-AppCheck'], 'app-2');
  });

  test('does not retry permanent App Check rejection', () async {
    final tokens = _Tokens();
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: tokens,
      client: MockClient(
        (_) async =>
            http.Response(jsonEncode({'error': 'app_check_invalid'}), 401),
      ),
    );

    await expectLater(
      transport.verifyIdentity(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.appCheckInvalid,
        ),
      ),
    );
    expect(tokens.idTokenRefreshes, [false]);
  });

  test('maps rate limits and preserves safe retry delay', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'rate_limited'}),
          429,
          headers: {'retry-after': '37'},
        ),
      ),
    );

    await expectLater(
      transport.verifyIdentity(),
      throwsA(
        isA<PythonBackendException>()
            .having(
              (error) => error.code,
              'code',
              PythonBackendError.rateLimited,
            )
            .having(
              (error) => error.retryAfter,
              'retryAfter',
              const Duration(seconds: 37),
            ),
      ),
    );
  });

  test('sanitizes malformed, unavailable, and timed-out responses', () async {
    final cases =
        <
          ({
            Future<http.Response> Function(http.Request) handler,
            PythonBackendError code,
          })
        >[
          (
            handler: (_) async => http.Response('private body', 503),
            code: PythonBackendError.unavailable,
          ),
          (
            handler: (_) async => http.Response('{broken', 200),
            code: PythonBackendError.invalidResponse,
          ),
          (
            handler: (_) => Completer<http.Response>().future,
            code: PythonBackendError.timeout,
          ),
        ];

    for (final item in cases) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(item.handler),
        timeout: const Duration(milliseconds: 1),
      );

      await expectLater(
        transport.verifyIdentity(),
        throwsA(
          isA<PythonBackendException>()
              .having((error) => error.code, 'code', item.code)
              .having(
                (error) => error.toString(),
                'safe message',
                isNot(contains('private body')),
              ),
        ),
      );
    }
  });

  test('rejects missing credentials before the network boundary', () async {
    final client = MockClient((_) async => fail('must not call backend'));
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(idToken: '', appCheckToken: ''),
      client: client,
    );

    await expectLater(
      transport.verifyIdentity(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.credentialsUnavailable,
        ),
      ),
    );
  });
}

final class _Tokens implements PythonBackendTokens {
  _Tokens({this.idToken = 'id', this.appCheckToken = 'app'});

  final String idToken;
  final String appCheckToken;
  final idTokenRefreshes = <bool>[];
  int appCheckCalls = 0;

  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    idTokenRefreshes.add(forceRefresh);
    if (idToken.isEmpty) return '';
    return '$idToken-${idTokenRefreshes.length}-${forceRefresh ? 'fresh' : 'cached'}';
  }

  @override
  Future<String> limitedUseAppCheckToken() async {
    appCheckCalls += 1;
    if (appCheckToken.isEmpty) return '';
    return '$appCheckToken-$appCheckCalls';
  }
}
