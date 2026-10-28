import 'dart:async';
import 'dart:convert';
import 'package:firebase_core/firebase_core.dart';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/audited_operation.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test(
    'authorization failure while watching does not become endless retries',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (r) async => r.method == 'POST'
              ? http.Response('{"operation_id":"sync-test123"}', 202)
              : http.Response('{"error":"academic_sync_access_denied"}', 403),
        ),
      );
      await expectLater(
        transport.syncAllAcademicData(background: true),
        throwsA(isA<PythonBackendException>()),
      );
    },
  );

  test(
    'background sync survives lost reads without submitting the job twice',
    () async {
      var posts = 0;
      var reads = 0;
      var delays = 0;
      var failedReads = 0;
      final resultBody = {
        'siga': {
          'courses': {'created': 1, 'existing': 4, 'total': 5},
          'schedules': {
            'total': 5,
            'updated': 1,
            'unchanged': 3,
            'conflicts': 1,
            'missing_courses': 0,
            'meetings_imported': 2,
          },
          'checked_at': '2026-10-24T12:00:00Z',
          'next_automatic_sync_at': '2026-12-06T00:00:00Z',
        },
        'moodle': {
          'dates': {
            'total': 3,
            'matched': 3,
            'unmatched': 0,
            'created': 1,
            'updated': 1,
            'unchanged': 1,
          },
          'content': {
            'course_total': 5,
            'candidate_total': 8,
            'metaturma_candidate_total': 2,
            'found': 4,
            'empty': 1,
            'unmatched': 0,
            'ambiguous': 0,
          },
          'capabilities': null,
        },
        'teaching_plans': {
          'available': 3,
          'imported': 2,
          'applied': 1,
          'unchanged': 0,
          'review_required': 3,
        },
        'exceptions': [
          {
            'course_id': 'course-a',
            'course_code': 'ELE028',
            'reason': 'reconciliation_conflict',
            'candidate_count': 1,
            'changes': [
              {
                'action': 'create_session',
                'occurrence_key': '2026-10-24T19:00-20:40',
                'date': '2026-10-24',
                'starts_at': '19:00',
                'ends_at': '20:40',
                'subject': 'Circuitos',
              },
            ],
            'conflicting': 1,
            'assessment_conflicts': 0,
          },
          {
            'course_id': 'course-b',
            'course_code': 'MAT001',
            'reason': 'ambiguous_teaching_plan',
            'candidate_count': 2,
            'changes': [],
            'conflicting': 0,
            'assessment_conflicts': 0,
          },
          {
            'course_id': 'course-c',
            'course_code': 'ESA019',
            'reason': 'teaching_plan_unavailable',
            'candidate_count': 1,
            'changes': [],
            'conflicting': 0,
            'assessment_conflicts': 0,
          },
        ],
      };
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        jobDelay: (_) async {
          delays++;
        },
        client: MockClient((request) async {
          if (request.method == 'POST') {
            posts++;
            expect(jsonDecode(request.body)['background'], true);
            return http.Response(
              '{"operation_id":"sync-test123","status":"queued"}',
              202,
            );
          }
          if (failedReads++ < 2) {
            throw http.ClientException('connection temporarily lost');
          }
          reads++;
          return http.Response(
            jsonEncode({
              'operation_id': 'sync-test123',
              'status': reads == 1 ? 'running' : 'succeeded',
              'result': resultBody,
            }),
            200,
          );
        }),
      );
      expect(
        (await transport.syncAllAcademicData(
          progressId: 'sync-test123',
          background: true,
        )).siga.courses.created,
        1,
      );
      expect(posts, 1);
      expect(reads, 2);
      expect(delays, greaterThanOrEqualTo(1));
      expect(await transport.pendingAcademicSyncId(), 'sync-test123');
    },
  );

  test(
    'saved job failures and replacement retain actionable diagnostics',
    () async {
      for (final state in [
        {
          'operation_id': 'sync-test123',
          'status': 'failed',
          'failure_code': 'MoodleUnavailable',
        },
        {'operation_id': 'other-operation', 'status': 'running'},
        {
          'operation_id': 'sync-test123',
          'status': 'failed',
          'failure_code': 'UFMGReauthenticationRequired',
        },
      ]) {
        final transport = PythonBackendTransport(
          endpoint: Uri.parse('https://backend.example'),
          tokens: _Tokens(),
          client: MockClient(
            (r) async => r.method == 'POST'
                ? http.Response('{"operation_id":"sync-test123"}', 202)
                : http.Response(jsonEncode(state), 200),
          ),
        );
        await expectLater(
          transport.syncAllAcademicData(background: true),
          throwsA(isA<PythonBackendException>()),
        );
      }
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response('{"status":"missing"}', 200),
        ),
      );
      expect(await transport.pendingAcademicSyncId(), isNull);
    },
  );

  test(
    'observation expiration does not cancel or restart the server job',
    () async {
      var posts = 0;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        jobDelay: (_) async {},
        client: MockClient((r) async {
          if (r.method == 'POST') {
            posts++;
            return http.Response('{"operation_id":"sync-test123"}', 202);
          }
          return http.Response(
            '{"operation_id":"sync-test123","status":"running"}',
            200,
          );
        }),
      );
      await expectLater(
        transport.syncAllAcademicData(background: true),
        throwsA(isA<PythonBackendException>()),
      );
      expect(posts, 1);
    },
  );

  test(
    'parallel metadata reads reuse App Check instead of minting one-use tokens',
    () async {
      final tokens = _DelayedRegularAppCheckTokens();
      final requests = <http.Request>[];
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: MockClient((request) async {
          requests.add(request);
          return http.Response('{"files":[],"count":0}', 200);
        }),
      );
      final reads = List.generate(
        12,
        (i) => transport.listMoodleMaterialFiles(
          term: '2026-2',
          courseId: '4953',
          sourceId: '${100 + i}',
        ),
      );
      await Future<void>.delayed(Duration.zero);
      expect(tokens.regularCalls, 1);
      tokens.regularToken.complete('cached-app-token');
      await Future.wait(reads);
      expect(requests, hasLength(12));
      expect(
        requests.every(
          (r) => r.headers['X-Firebase-AppCheck'] == 'cached-app-token',
        ),
        isTrue,
      );
    },
  );

  test(
    'credential failures retain sanitized SDK reason across request wrapping',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _FailingAppCheckTokens(
          FirebaseException(
            plugin: 'firebase_app_check',
            code: 'unknown',
            message: 'Too many attempts. token=secret-value',
          ),
        ),
        client: MockClient((_) async => fail('must not call backend')),
      );
      await expectLater(
        transport.verifyIdentity(),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.toString(),
            'persisted SDK diagnostics',
            allOf(
              contains('sdk_code=unknown'),
              contains('Too many attempts'),
              isNot(contains('secret-value')),
            ),
          ),
        ),
      );
    },
  );
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
      expect(captured.headers['X-Firebase-AppCheck'], 'regular-app-1');
      expect(
        captured.headers['X-Request-ID'],
        matches(RegExp(r'^[a-z0-9-]+$')),
      );
      expect(tokens.idTokenRefreshes, [false]);
      expect(tokens.appCheckCalls, 1);
    },
  );

  test('retries one transient transport failure for a read request', () async {
    var requests = 0;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((_) async {
        requests++;
        if (requests == 1) {
          throw http.ClientException('connection closed');
        }
        return http.Response(jsonEncode({'authenticated': true}), 200);
      }),
    );

    await transport.verifyIdentity();

    expect(requests, 2);
  });

  test(
    'retains a safe cause type when transport retries are exhausted',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async {
          throw http.ClientException('connection reset password=secret-value');
        }),
      );

      await expectLater(
        transport.verifyIdentity(),
        throwsA(
          isA<PythonBackendException>()
              .having(
                (error) => error.toString(),
                'safe diagnostic',
                contains('cause=ClientException'),
              )
              .having(
                (error) => error.toString(),
                'secret value',
                isNot(contains('secret-value')),
              ),
        ),
      );
    },
  );

  test('preserves backend HTTP failure and correlation diagnostics', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'error': 'security_guard_unavailable'}),
          503,
          headers: {'x-request-id': 'server-123'},
        ),
      ),
    );
    await expectLater(
      transport.previewOfficialCalendar(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.logDetails,
          'HTTP diagnostics',
          allOf(
            contains('stage=http_response'),
            contains('method=post'),
            contains('path=/v1/calendar/official/preview'),
            contains('status=503'),
            contains('backend_error=security_guard_unavailable'),
            contains('server_request_id=server-123'),
          ),
        ),
      ),
    );
  });

  test('does not retry a transient failure for a mutation', () async {
    var requests = 0;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((_) async {
        requests++;
        throw http.ClientException('connection closed');
      }),
    );

    await expectLater(
      transport.connectUFMG(username: 'student', password: 'private'),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.unavailable,
        ),
      ),
    );
    expect(requests, 1);
  });

  test(
    'reserves limited-use App Check tokens for state-changing requests',
    () async {
      final tokens = _Tokens();
      final requests = <http.Request>[];
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: MockClient((request) async {
          requests.add(request);
          if (request.method == 'GET') {
            return http.Response(jsonEncode({'authenticated': true}), 200);
          }
          return http.Response(
            jsonEncode({
              'connected': true,
              'created_at': 1000,
              'expires_at': 33400,
            }),
            200,
          );
        }),
      );

      await transport.verifyIdentity();
      await transport.connectUFMG(
        username: '2025019259',
        password: 'private-password',
      );

      expect(requests[0].headers['X-Firebase-AppCheck'], 'regular-app-1');
      expect(requests[1].headers['X-Firebase-AppCheck'], 'app-1');
      expect(tokens.regularAppCheckCalls, 1);
      expect(tokens.limitedAppCheckCalls, 1);
      expect(tokens.appCheckCalls, 2);
    },
  );

  test(
    'loads, connects, and disconnects the UFMG session without echoing credentials',
    () async {
      final requests = <http.Request>[];
      final responses = <http.Response>[
        http.Response(
          jsonEncode({
            'connected': true,
            'created_at': 900,
            'expires_at': 33300,
            'reauthentication_required': false,
          }),
          200,
        ),
        http.Response(
          jsonEncode({
            'connected': true,
            'created_at': 1000,
            'expires_at': 33400,
          }),
          200,
        ),
        http.Response(jsonEncode({'connected': false}), 200),
      ];
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          requests.add(request);
          return responses.removeAt(0);
        }),
      );

      final initial = await transport.getUFMGSessionStatus();
      final connected = await transport.connectUFMG(
        username: '2025019259',
        password: 'private-password',
      );
      final disconnected = await transport.disconnectUFMG();

      expect(initial.connected, isTrue);
      expect(initial.reauthenticationRequired, isFalse);
      expect(connected.connected, isTrue);
      expect(
        connected.expiresAt,
        DateTime.fromMillisecondsSinceEpoch(33400000, isUtc: true),
      );
      expect(disconnected.connected, isFalse);
      expect(requests.map((request) => request.method), [
        'GET',
        'POST',
        'DELETE',
      ]);
      expect(
        requests.map((request) => request.url.path),
        everyElement('/v1/ufmg/session'),
      );
      expect(jsonDecode(requests[1].body), {
        'username': '2025019259',
        'password': 'private-password',
      });
      expect(requests[0].body, isEmpty);
      expect(requests[2].body, isEmpty);

      final expiredTransport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({'connected': false, 'reauthentication_required': true}),
            200,
          ),
        ),
      );
      final expired = await expiredTransport.getUFMGSessionStatus();
      expect(expired.connected, isFalse);
      expect(expired.reauthenticationRequired, isTrue);
    },
  );

  test(
    'imports UFMG courses and accepts only a bounded count summary',
    () async {
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({'created': 2, 'existing': 3, 'total': 5}),
            200,
          );
        }),
      );

      final result = await transport.importUFMGCourses();

      expect(result.created, 2);
      expect(result.existing, 3);
      expect(result.total, 5);
      expect(captured.method, 'POST');
      expect(captured.url.path, '/v1/ufmg/import/courses');
      expect(captured.body, '{}');
    },
  );

  test('rejects malformed UFMG import summaries', () async {
    for (final body in [
      {'created': 2, 'existing': 3, 'total': 4},
      {'created': -1, 'existing': 0, 'total': -1},
      {
        'created': 1,
        'existing': 0,
        'total': 1,
        'courses': ['private'],
      },
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async => http.Response(jsonEncode(body), 200)),
      );

      await expectLater(
        transport.importUFMGCourses(),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            PythonBackendError.invalidResponse,
          ),
        ),
      );
    }
  });

  test(
    'imports UFMG schedules and accepts only bounded aggregate counts',
    () async {
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({
              'total': 5,
              'updated': 2,
              'unchanged': 1,
              'conflicts': 1,
              'missing_courses': 1,
              'meetings_imported': 3,
            }),
            200,
          );
        }),
      );

      final result = await transport.importUFMGSchedules();

      expect(result.updated, 2);
      expect(result.conflicts, 1);
      expect(result.meetingsImported, 3);
      expect(captured.method, 'POST');
      expect(captured.url.path, '/v1/ufmg/import/schedules');
      expect(captured.body, '{}');
    },
  );

  test('rejects malformed UFMG schedule import summaries', () async {
    for (final body in [
      {
        'total': 4,
        'updated': 2,
        'unchanged': 1,
        'conflicts': 1,
        'missing_courses': 1,
        'meetings_imported': 3,
      },
      {
        'total': 1,
        'updated': 1,
        'unchanged': 0,
        'conflicts': 0,
        'missing_courses': 0,
        'meetings_imported': 33,
      },
      {
        'total': 0,
        'updated': 0,
        'unchanged': 0,
        'conflicts': 0,
        'missing_courses': 0,
      },
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async => http.Response(jsonEncode(body), 200)),
      );

      await expectLater(
        transport.importUFMGSchedules(),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            PythonBackendError.invalidResponse,
          ),
        ),
      );
    }
  });

  test('imports bounded structured Moodle date counts', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'total': 4,
            'matched': 3,
            'unmatched': 1,
            'created': 2,
            'updated': 1,
            'unchanged': 0,
          }),
          200,
        );
      }),
    );

    final result = await transport.importMoodleDates();

    expect(result.created, 2);
    expect(result.updated, 1);
    expect(result.unmatched, 1);
    expect(captured.method, 'POST');
    expect(captured.url.path, '/v1/ufmg/import/dates');
    expect(captured.body, '{}');
  });

  test('rejects malformed Moodle date summaries', () async {
    for (final body in [
      {
        'total': 4,
        'matched': 3,
        'unmatched': 0,
        'created': 2,
        'updated': 1,
        'unchanged': 0,
      },
      {
        'total': 501,
        'matched': 501,
        'unmatched': 0,
        'created': 501,
        'updated': 0,
        'unchanged': 0,
      },
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async => http.Response(jsonEncode(body), 200)),
      );
      await expectLater(
        transport.importMoodleDates(),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            PythonBackendError.invalidResponse,
          ),
        ),
      );
    }
  });

  test('discovers bounded Moodle content candidates', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'courses': [
              {
                'course_id': 'dcc203',
                'course_code': 'DCC203',
                'term': '2026-2',
                'moodle_course_id': '3701',
                'status': 'found',
                'candidates': [
                  {
                    'source_id': '101',
                    'kind': 'page',
                    'title': 'Plano de ensino',
                    'url':
                        'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
                    'relevance': 'teaching_plan',
                    'origin': 'canonical',
                  },
                  {
                    'source_id': '102',
                    'kind': 'text',
                    'title': 'Orientações',
                    'url': null,
                    'relevance': 'other',
                    'origin': 'metaturma',
                  },
                ],
              },
              {
                'course_id': 'mat001',
                'course_code': 'MAT001',
                'term': '2026-2',
                'moodle_course_id': '4953',
                'status': 'empty',
                'candidates': <Object?>[],
              },
              {
                'course_id': 'ele028',
                'course_code': 'ELE028',
                'term': '2026-2',
                'moodle_course_id': null,
                'status': 'unmatched',
                'candidates': <Object?>[],
              },
              {
                'course_id': 'amb001',
                'course_code': 'AMB001',
                'term': '2026-2',
                'moodle_course_id': null,
                'status': 'ambiguous',
                'candidates': <Object?>[],
              },
            ],
            'course_total': 4,
            'candidate_total': 2,
            'metaturma_candidate_total': 1,
            'found': 1,
            'empty': 1,
            'unmatched': 1,
            'ambiguous': 1,
          }),
          200,
        );
      }),
    );

    final result = await transport.discoverMoodleContent();

    expect(result.candidateTotal, 2);
    expect(result.metaturmaCandidateTotal, 1);
    expect(result.courses.first.candidates.first.title, 'Plano de ensino');
    expect(
      result.courses.first.candidates.last.origin,
      PythonMoodleContentOrigin.metaturma,
    );
    expect(result.courses[1].status, PythonMoodleContentStatus.empty);
    expect(result.courses.first.moodleCourseId, '3701');
    expect(result.courses.first.term, '2026-2');
    expect(result.courses.first.candidates.last.moodleCourseId, '3701');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/v1/ufmg/discover/content');
    expect(captured.body, '{}');
  });

  test(
    'loads the persisted Moodle material catalog without synchronizing',
    () async {
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({
              'courses': <Object?>[],
              'course_total': 0,
              'candidate_total': 0,
              'metaturma_candidate_total': 0,
              'found': 0,
              'empty': 0,
              'unmatched': 0,
              'ambiguous': 0,
            }),
            200,
          );
        }),
      );

      final result = await transport.listMoodleMaterialCatalog();

      expect(result.courses, isEmpty);
      expect(captured.method, 'GET');
      expect(captured.url.path, '/v1/moodle/materials');
    },
  );

  test('validates bounded Moodle mobile download capabilities', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'term': '2026-2',
            'direct_download_supported': true,
            'download_files': true,
            'private_file_access': true,
            'webservice_token_issued': true,
          }),
          200,
        );
      }),
    );

    final result = await transport.probeMoodleMobileCapabilities();

    expect(result.term, '2026-2');
    expect(result.directDownloadSupported, isTrue);
    expect(captured.method, 'POST');
    expect(captured.url.path, '/v1/ufmg/moodle/capabilities');
    expect(captured.body, '{}');
  });

  test('rejects inconsistent Moodle mobile download capabilities', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'term': '2026-2',
            'direct_download_supported': true,
            'download_files': false,
            'private_file_access': true,
            'webservice_token_issued': true,
          }),
          200,
        ),
      ),
    );

    await expectLater(
      transport.probeMoodleMobileCapabilities(),
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
    'accepts reusable Moodle download credentials without reissuing them',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'term': '2026-2',
              'direct_download_supported': true,
              'download_files': true,
              'private_file_access': true,
              'webservice_token_issued': false,
            }),
            200,
          ),
        ),
      );

      final result = await transport.probeMoodleMobileCapabilities();

      expect(result.directDownloadSupported, isTrue);
      expect(result.webserviceTokenIssued, isFalse);
    },
  );

  test('synchronizes Moodle stages through one bounded contract', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'activities': {'updated': 2, 'failed': 1, 'failed_courses': []},
            'dates': {
              'total': 3,
              'matched': 2,
              'unmatched': 1,
              'created': 1,
              'updated': 1,
              'unchanged': 0,
            },
            'content': {
              'course_total': 2,
              'candidate_total': 8,
              'metaturma_candidate_total': 3,
              'found': 1,
              'empty': 1,
              'unmatched': 0,
              'ambiguous': 0,
            },
            'capabilities': {
              'term': '2026-2',
              'direct_download_supported': true,
              'download_files': true,
              'private_file_access': true,
              'webservice_token_issued': false,
            },
          }),
          200,
        );
      }),
    );

    final result = await transport.syncMoodle();

    expect(result.activitySnapshots!.failed, 1);
    expect(result.dates.created, 1);
    expect(result.candidateTotal, 8);
    expect(result.capabilities?.directDownloadSupported, isTrue);
    expect(result.capabilities?.webserviceTokenIssued, isFalse);
    expect(captured.method, 'POST');
    expect(captured.url.path, '/v1/ufmg/sync/moodle');
    expect(captured.body, '{}');
  });

  test('rejects malformed combined Moodle synchronization results', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'dates': {
              'total': 0,
              'matched': 0,
              'unmatched': 0,
              'created': 0,
              'updated': 0,
              'unchanged': 0,
            },
            'content': {
              'course_total': 2,
              'candidate_total': 0,
              'metaturma_candidate_total': 0,
              'found': 1,
              'empty': 0,
              'unmatched': 0,
              'ambiguous': 0,
            },
            'capabilities': null,
          }),
          200,
        ),
      ),
    );

    await expectLater(
      transport.syncMoodle(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

  test('validates a bounded Diario de Classe PDF probe', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'available': true,
            'delivery': 'form',
            'format': 'pdf',
            'content_length': 12345,
            'term': '2026-2',
            'source_id': '701',
          }),
          200,
        );
      }),
    );

    final result = await transport.probeMoodleDiarioPlan(
      term: '2026-2',
      sourceId: '701',
    );

    expect(result.delivery, 'form');
    expect(result.contentLength, 12345);
    expect(captured.url.path, '/v1/ufmg/moodle/diario-plan');
    expect(jsonDecode(captured.body), {'term': '2026-2', 'source_id': 701});
  });

  test(
    'accepts the observed Diario HTML plan delivered through a link',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'available': true,
              'delivery': 'link',
              'format': 'html',
              'content_length': 12345,
              'term': '2026-2',
              'source_id': '701',
            }),
            200,
          ),
        ),
      );

      final result = await transport.probeMoodleDiarioPlan(
        term: '2026-2',
        sourceId: '701',
      );

      expect(result.delivery, 'link');
      expect(result.contentLength, 12345);
    },
  );

  test('rejects malformed Diario plan requests and responses', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'available': true,
            'delivery': 'other',
            'format': 'pdf',
            'content_length': 12345,
            'term': '2026-2',
            'source_id': '701',
          }),
          200,
        ),
      ),
    );

    expect(
      () => transport.probeMoodleDiarioPlan(term: 'invalid', sourceId: '701'),
      throwsArgumentError,
    );
    await expectLater(
      transport.probeMoodleDiarioPlan(term: '2026-2', sourceId: '701'),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

  test('imports one structured Diario teaching plan', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'course_id': 'dcc203',
            'term': '2026-2',
            'source_id': '701',
            'plan': 'created',
            'assessment_total': 2,
            'undated_assessment_total': 3,
            'dates_created': 2,
            'dates_updated': 0,
            'dates_unchanged': 0,
            'dates_removed': 0,
            'criteria_total': 1,
            'schedule_total': 30,
            'confidence': 'authoritative',
          }),
          200,
        );
      }),
    );

    final result = await transport.importMoodleTeachingPlan(
      courseId: 'dcc203',
      term: '2026-2',
      sourceId: '701',
    );

    expect(captured.url.path, '/v1/ufmg/import/teaching-plan');
    expect(jsonDecode(captured.body), {
      'course_id': 'dcc203',
      'term': '2026-2',
      'source_id': 701,
    });
    expect(result.assessmentTotal, 2);
    expect(result.undatedAssessmentTotal, 3);
    expect(result.criteriaTotal, 1);
    expect(result.scheduleTotal, 30);
    expect(result.createdDates, 2);
  });

  test(
    'accepts an explicitly unpublished plan as an informational outcome',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'course_id': 'dcc203',
              'term': '2026-2',
              'source_id': '701',
              'plan': 'not_published',
              'assessment_total': 0,
              'undated_assessment_total': 0,
              'dates_created': 0,
              'dates_updated': 0,
              'dates_unchanged': 0,
              'dates_removed': 0,
              'criteria_total': 0,
              'schedule_total': 0,
              'confidence': 'authoritative',
            }),
            200,
          ),
        ),
      );
      final result = await transport.importMoodleTeachingPlan(
        courseId: 'dcc203',
        term: '2026-2',
        sourceId: '701',
      );
      expect(result.notPublished, isTrue);
      expect(result.removedDates, 0);
    },
  );

  test('rejects invalid and malformed structured Diario imports', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'course_id': 'dcc203',
            'term': '2026-2',
            'source_id': '701',
            'plan': 'created',
            'assessment_total': 101,
            'undated_assessment_total': 0,
            'dates_created': 2,
            'dates_updated': 0,
            'dates_unchanged': 0,
            'dates_removed': 0,
            'criteria_total': 1,
            'schedule_total': 30,
            'confidence': 'authoritative',
          }),
          200,
        ),
      ),
    );

    expect(
      () => transport.importMoodleTeachingPlan(
        courseId: 'dcc203',
        term: 'invalid',
        sourceId: '701',
      ),
      throwsArgumentError,
    );
    await expectLater(
      transport.importMoodleTeachingPlan(
        courseId: 'dcc203',
        term: '2026-2',
        sourceId: '701',
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

  test('previews and applies teaching plan reconciliation', () async {
    final requests = <http.Request>[];
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        requests.add(request);
        final apply =
            (jsonDecode(request.body) as Map<String, dynamic>)['apply'] as bool;
        return http.Response(
          jsonEncode({
            'course_id': 'dcc203',
            'mode': apply ? 'applied' : 'preview',
            'matched': 28,
            'missing': apply ? 0 : 2,
            'conflicting': 1,
            'assessments_linked': 1,
            'assessment_conflicts': 0,
            'outside_schedule': 1,
            'workload_validation': {
              'status': 'below_expected',
              'expected_lesson_units': 60,
              'actual_lesson_units': 58,
              'difference_lesson_units': -2,
              'expected_typical_meetings': 30,
              'active_encounters': 29,
              'excluded_encounters': 2,
              'scheduled_lesson_units': 54,
              'no_call_lesson_units': 2,
              'makeup_lesson_units': 2,
            },
            'applied': apply ? 2 : 0,
            'changes': [
              {
                'action': 'create_session',
                'occurrence_key': '2026-08-10T19:00-20:40',
                'date': '2026-08-10',
                'starts_at': '19:00',
                'ends_at': '20:40',
                'subject': 'Polimorfismo',
              },
            ],
            'excluded': [
              {
                'action': 'excluded',
                'occurrence_key': '2026-08-11T19:00-20:40',
                'date': '2026-08-11',
                'starts_at': '19:00',
                'ends_at': '20:40',
                'subject': 'Atividade assíncrona',
                'reason': 'outside_weekly_schedule',
              },
            ],
            'conflicts': [
              {
                'occurrence_key': '2026-08-10T19:00-20:40',
                'reason': 'overlapping_session',
                'existing_session_ids': ['manual'],
              },
            ],
          }),
          200,
        );
      }),
    );

    final preview = await transport.reconcileMoodleTeachingPlan(
      courseId: 'dcc203',
      apply: false,
    );
    final applied = await transport.reconcileMoodleTeachingPlan(
      courseId: 'dcc203',
      apply: true,
    );

    expect(
      requests.every(
        (request) => request.url.path == '/v1/ufmg/reconcile/teaching-plan',
      ),
      isTrue,
    );
    expect(preview.missing, 2);
    expect(preview.conflicting, 1);
    expect(preview.assessmentsLinked, 1);
    expect(preview.outsideSchedule, 1);
    expect(preview.changes.single.subject, 'Polimorfismo');
    expect(preview.excluded.single.reason, 'outside_weekly_schedule');
    final workload = preview.workloadValidation!;
    expect(workload.status, 'below_expected');
    expect(workload.expectedLessonUnits, 60);
    expect(workload.actualLessonUnits, 58);
    expect(workload.noCallLessonUnits, 2);
    expect(applied.applied, 2);
  });

  test(
    'accepts outside-grade removals and an unknown legacy workload',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'course_id': 'ele065',
              'mode': 'preview',
              'matched': 16,
              'missing': 0,
              'conflicting': 0,
              'assessments_linked': 0,
              'assessment_conflicts': 0,
              'outside_schedule': 2,
              'applied': 0,
              'changes': [
                for (final day in ['2026-11-22', '2026-11-23'])
                  {
                    'action': 'remove_session',
                    'occurrence_key': '${day}T19:00-20:40',
                    'date': day,
                    'starts_at': '19:00',
                    'ends_at': '20:40',
                    'subject': 'Atividade assíncrona',
                  },
              ],
              'excluded': const [],
              'conflicts': const [],
              'workload_validation': null,
            }),
            200,
          ),
        ),
      );

      final preview = await transport.reconcileMoodleTeachingPlan(
        courseId: 'ele065',
        apply: false,
      );

      expect(preview.outsideSchedule, 2);
      expect(
        preview.changes.map((change) => change.action),
        everyElement('remove_session'),
      );
      expect(preview.excluded, isEmpty);
      expect(preview.workloadValidation, isNull);
    },
  );

  test('resolves bounded direct Moodle material files', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'files': [
              {
                'name': 'Plano.pdf',
                'url':
                    'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
                    'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf'
                    '?forcedownload=1',
                'size': 123,
                'mime_type': 'application/pdf',
              },
            ],
            'count': 1,
          }),
          200,
        );
      }),
    );

    final files = await transport.listMoodleMaterialFiles(
      term: '2026-2',
      courseId: '3701',
      sourceId: '701',
    );

    expect(files.single.name, 'Plano.pdf');
    expect(files.single.size, 123);
    expect(files.single.mimeType, 'application/pdf');
    expect(captured.url.path, '/v1/ufmg/moodle/material-files');
    expect(jsonDecode(captured.body), {
      'term': '2026-2',
      'course_id': 3701,
      'source_id': 701,
    });
  });

  test(
    'rejects unsafe Moodle material file responses and identities',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'files': [
                {
                  'name': 'Unsafe.pdf',
                  'url': 'https://attacker.example/file.pdf',
                  'size': 1,
                  'mime_type': 'application/pdf',
                },
              ],
              'count': 1,
            }),
            200,
          ),
        ),
      );

      await expectLater(
        transport.listMoodleMaterialFiles(
          term: '2026-2',
          courseId: '3701',
          sourceId: '701',
        ),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            PythonBackendError.invalidResponse,
          ),
        ),
      );
      expect(
        () => transport.listMoodleMaterialFiles(
          term: 'invalid',
          courseId: '3701',
          sourceId: '701',
        ),
        throwsArgumentError,
      );
    },
  );

  test('accepts bounded long Moodle content titles', () {
    final title = List.filled(1024, 'x').join();

    final candidate = PythonMoodleContentCandidate.fromJson({
      'source_id': '101',
      'moodle_course_id': '3701',
      'kind': 'page',
      'title': title,
      'url': 'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
      'relevance': 'other',
      'origin': 'canonical',
    });

    expect(candidate.title, title);
  });

  test('accepts a bounded Moodle link module', () {
    final candidate = PythonMoodleContentCandidate.fromJson({
      'source_id': '701',
      'moodle_course_id': '3701',
      'kind': 'link',
      'title': 'Plano de ensino',
      'url': 'https://virtual.ufmg.br/20262/mod/url/view.php?id=701',
      'relevance': 'teaching_plan',
      'origin': 'canonical',
    });

    expect(candidate.kind, 'link');
    expect(candidate.canOpenDirectly, isTrue);
  });

  test('rejects unknown Moodle content origins', () {
    expect(
      () => PythonMoodleContentCandidate.fromJson({
        'source_id': '101',
        'moodle_course_id': '3701',
        'kind': 'page',
        'title': 'Material',
        'url': 'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
        'relevance': 'other',
        'origin': 'external',
      }),
      throwsFormatException,
    );
  });

  test('rejects Moodle material URLs outside the direct-download contract', () {
    for (final entry in [
      ('101', 'page', 'https://example.com/20262/mod/page/view.php?id=101'),
      ('101', 'page', 'https://virtual.ufmg.br/login/index.php?id=101'),
      ('101', 'page', 'https://virtual.ufmg.br/20262/mod/page/view.php?id=102'),
      (
        '101',
        'page',
        'https://virtual.ufmg.br/20262/mod/resource/view.php?id=101',
      ),
      (
        'not-an-id',
        'page',
        'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
      ),
      (
        '101',
        'file',
        'https://virtual.ufmg.br/20262/mod/folder/view.php?id=101&extra=1',
      ),
    ]) {
      expect(
        () => PythonMoodleContentCandidate.fromJson({
          'source_id': entry.$1,
          'moodle_course_id': '3701',
          'kind': entry.$2,
          'title': 'Material',
          'url': entry.$3,
          'relevance': 'other',
          'origin': 'canonical',
        }),
        throwsFormatException,
      );
    }
  });

  test('lists canonical Moodle dates in chronological order', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'dates': [
              {
                'id': 'moodle-910',
                'course_id': 'dcc203',
                'course_code': 'DCC203',
                'title': 'Trabalho prático',
                'due_at': '2026-10-22T23:00:00Z',
                'kind': 'assignment',
                'source': 'moodle',
                'source_id': '910',
                'created_at': '2026-10-13T20:00:00Z',
                'updated_at': '2026-10-13T20:00:00Z',
              },
            ],
          }),
          200,
        ),
      ),
    );

    final dates = await transport.listMoodleDates();

    expect(dates.single.courseCode, 'DCC203');
    expect(dates.single.title, 'Trabalho prático');
    expect(dates.single.dueAt, DateTime.utc(2026, 10, 22, 23));
  });

  test('rejects malformed or unsorted Moodle date lists', () async {
    final valid = {
      'id': 'moodle-910',
      'course_id': 'dcc203',
      'course_code': 'DCC203',
      'title': 'Trabalho',
      'due_at': '2026-10-22T23:00:00Z',
      'kind': 'assignment',
      'source': 'moodle',
      'source_id': '910',
      'created_at': '2026-10-13T20:00:00Z',
      'updated_at': '2026-10-13T20:00:00Z',
    };
    for (final body in [
      {
        'dates': [
          {...valid, 'source': 'manual'},
        ],
      },
      {
        'dates': [
          valid,
          {
            ...valid,
            'id': 'moodle-911',
            'source_id': '911',
            'due_at': '2026-10-01T00:00:00Z',
          },
        ],
      },
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async => http.Response(jsonEncode(body), 200)),
      );
      await expectLater(
        transport.listMoodleDates(),
        throwsA(isA<PythonBackendException>()),
      );
    }
  });

  test('synchronizes UFMG stages through one bounded contract', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'courses': {'created': 1, 'existing': 4, 'total': 5},
            'schedules': {
              'total': 5,
              'updated': 1,
              'unchanged': 3,
              'conflicts': 1,
              'missing_courses': 0,
              'meetings_imported': 2,
            },
            'checked_at': '2026-10-13T12:00:00Z',
            'next_automatic_sync_at': '2026-12-06T00:00:00Z',
          }),
          200,
        );
      }),
    );

    final result = await transport.syncSiga();

    expect(result.courses.created, 1);
    expect(result.schedules.updated, 1);
    expect(result.schedules.conflicts, 1);
    expect(result.checkedAt, DateTime.utc(2026, 10, 13, 12));
    expect(result.nextAutomaticSyncAt, DateTime.utc(2026, 12, 6));
    expect(captured.method, 'POST');
    expect(captured.url.path, '/v1/ufmg/sync/siga');
    expect(captured.body, '{}');
  });

  test(
    'synchronizes every academic source and exposes review exceptions',
    () async {
      late http.Request captured;
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          captured = request;
          return http.Response(
            jsonEncode({
              'siga': {
                'courses': {'created': 1, 'existing': 4, 'total': 5},
                'schedules': {
                  'total': 5,
                  'updated': 1,
                  'unchanged': 3,
                  'conflicts': 1,
                  'missing_courses': 0,
                  'meetings_imported': 2,
                },
                'checked_at': '2026-10-24T12:00:00Z',
                'next_automatic_sync_at': '2026-12-06T00:00:00Z',
              },
              'moodle': {
                'dates': {
                  'total': 3,
                  'matched': 3,
                  'unmatched': 0,
                  'created': 1,
                  'updated': 1,
                  'unchanged': 1,
                },
                'content': {
                  'course_total': 5,
                  'candidate_total': 8,
                  'metaturma_candidate_total': 2,
                  'found': 4,
                  'empty': 1,
                  'unmatched': 0,
                  'ambiguous': 0,
                },
                'capabilities': null,
              },
              'teaching_plans': {
                'available': 3,
                'imported': 2,
                'applied': 1,
                'unchanged': 0,
                'review_required': 3,
              },
              'exceptions': [
                {
                  'course_id': 'course-a',
                  'course_code': 'ELE028',
                  'reason': 'reconciliation_conflict',
                  'candidate_count': 1,
                  'changes': [
                    {
                      'action': 'create_session',
                      'occurrence_key': '2026-10-24T19:00-20:40',
                      'date': '2026-10-24',
                      'starts_at': '19:00',
                      'ends_at': '20:40',
                      'subject': 'Circuitos',
                    },
                  ],
                  'conflicting': 1,
                  'assessment_conflicts': 0,
                },
                {
                  'course_id': 'course-b',
                  'course_code': 'MAT001',
                  'reason': 'ambiguous_teaching_plan',
                  'candidate_count': 2,
                  'changes': [],
                  'conflicting': 0,
                  'assessment_conflicts': 0,
                },
                {
                  'course_id': 'course-c',
                  'course_code': 'ESA019',
                  'reason': 'teaching_plan_unavailable',
                  'candidate_count': 1,
                  'changes': [],
                  'conflicting': 0,
                  'assessment_conflicts': 0,
                },
              ],
            }),
            200,
          );
        }),
      );

      final result = await transport.syncAllAcademicData(
        progressId: 'sync-test123',
      );

      expect(result.siga.courses.created, 1);
      expect(result.moodle.dates.created, 1);
      expect(result.teachingPlans.applied, 1);
      expect(result.exceptions.first.courseCode, 'ELE028');
      expect(result.exceptions.first.changes.single.subject, 'Circuitos');
      expect(result.exceptions[1].courseCode, 'MAT001');
      expect(result.exceptions.last.courseCode, 'ESA019');
      expect(result.exceptions.last.reason, 'teaching_plan_unavailable');
      expect(captured.method, 'POST');
      expect(captured.url.path, '/v1/ufmg/sync/all');
      expect(jsonDecode(captured.body), {'progress_id': 'sync-test123'});
    },
  );

  test('rejects malformed intelligent synchronization contracts', () async {
    for (final body in [
      {
        'courses': {'created': 1, 'existing': 4, 'total': 4},
        'schedules': {
          'total': 5,
          'updated': 1,
          'unchanged': 3,
          'conflicts': 1,
          'missing_courses': 0,
          'meetings_imported': 2,
        },
        'checked_at': '2026-10-13T12:00:00Z',
        'next_automatic_sync_at': '2026-12-06T00:00:00Z',
      },
      {
        'courses': {'created': 1, 'existing': 4, 'total': 5},
        'schedules': {
          'total': 5,
          'updated': 1,
          'unchanged': 3,
          'conflicts': 1,
          'missing_courses': 0,
          'meetings_imported': 2,
        },
        'checked_at': 'not-a-date',
        'next_automatic_sync_at': '2026-12-06T00:00:00Z',
      },
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((_) async => http.Response(jsonEncode(body), 200)),
      );

      await expectLater(
        transport.syncSiga(),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            PythonBackendError.invalidResponse,
          ),
        ),
      );
    }
  });

  test('previews and applies official UFMG calendar changes', () async {
    late http.Request captured;
    var request = 0;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((value) async {
        captured = value;
        request++;
        return http.Response(
          jsonEncode(
            request == 1
                ? {
                    'candidates': [
                      {
                        'course_id': 'ele028',
                        'course_code': 'ELE028',
                        'session_id': 'session-1',
                        'date': '2026-10-12',
                        'starts_at': '2026-10-12T22:00:00Z',
                        'ends_at': '2026-10-12T23:40:00Z',
                        'events': [
                          {
                            'title': 'Feriado: Nossa Senhora Aparecida',
                            'source_url':
                                'https://www.ufmg.br/a-universidade/calendario-escolar/?mes=10&ano=2026',
                            'confidence': 'official',
                          },
                        ],
                        'from': 'scheduled',
                        'to': 'holiday',
                      },
                    ],
                    'counts': {
                      'candidates': 1,
                      'unchanged': 0,
                      'protected': 0,
                      'advisories': 0,
                    },
                  }
                : {'applied': 1, 'skipped': 0},
          ),
          200,
        );
      }),
    );

    final preview = await transport.previewOfficialCalendar();
    expect(preview.candidates.single.courseCode, 'ELE028');
    expect(preview.candidates.single.eventTitle, contains('Nossa Senhora'));
    final result = await transport.applyOfficialCalendar(preview.candidates);
    expect(result.applied, 1);
    expect(captured.url.path, '/v1/calendar/official/apply');
    expect(jsonDecode(captured.body), {
      'changes': [
        {'course_id': 'ele028', 'session_id': 'session-1'},
      ],
    });
  });

  test('classifies invalid UFMG credentials separately from outages', () async {
    for (final entry in [
      (
        401,
        'ufmg_credentials_invalid',
        PythonBackendError.ufmgCredentialsInvalid,
      ),
      (
        503,
        'ufmg_authentication_unavailable',
        PythonBackendError.ufmgUnavailable,
      ),
    ]) {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(jsonEncode({'error': entry.$2}), entry.$1),
        ),
      );

      await expectLater(
        transport.connectUFMG(username: 'student', password: 'secret'),
        throwsA(
          isA<PythonBackendException>().having(
            (error) => error.code,
            'code',
            entry.$3,
          ),
        ),
      );
    }
  });

  test('rejects malformed UFMG session metadata', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({'connected': true, 'token': 'must-not-be-accepted'}),
          200,
        ),
      ),
    );

    await expectLater(
      transport.getUFMGSessionStatus(),
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
    'shares an in-flight regular App Check token across parallel reads',
    () async {
      final tokens = _DelayedRegularAppCheckTokens();
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: MockClient((request) async {
          if (request.url.path == '/v1/identity') {
            return http.Response(jsonEncode({'authenticated': true}), 200);
          }
          return http.Response(
            jsonEncode({
              'connected': true,
              'created_at': 900,
              'expires_at': 33300,
              'reauthentication_required': false,
            }),
            200,
          );
        }),
      );

      final identity = transport.verifyIdentity();
      final status = transport.getUFMGSessionStatus();
      await Future<void>.delayed(Duration.zero);

      expect(tokens.regularCalls, 1);
      tokens.regularToken.complete('shared-app-check');
      await Future.wait([identity, status]);
    },
  );

  test(
    'reuses the audited operation id across an authentication retry',
    () async {
      final requests = <http.Request>[];
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          requests.add(request);
          if (requests.length == 1) {
            return http.Response(jsonEncode({'error': 'unauthorized'}), 401);
          }
          return http.Response(jsonEncode({'authenticated': true}), 200);
        }),
      );

      await runAuditedOperation(
        logger: _SilentLogger(),
        operation: AuditedOperation.courseList,
        action: transport.verifyIdentity,
      );

      expect(requests, hasLength(2));
      expect(requests[0].headers['X-Request-ID'], isNotEmpty);
      expect(
        requests[1].headers['X-Request-ID'],
        requests[0].headers['X-Request-ID'],
      );
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

  test('loads one validated academic overview snapshot', () async {
    late http.Request captured;
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        captured = request;
        return http.Response(
          jsonEncode({
            'items': [
              {
                'course': _courseJson,
                'sessions': [
                  {..._sessionJson, 'call_count': 2, 'second_ping': 'fora'},
                ],
              },
            ],
          }),
          200,
        );
      }),
    );

    final overview = await transport.loadOverview();

    expect(captured.url, Uri.parse('https://backend.example/v1/overview'));
    expect(overview, hasLength(1));
    expect(overview.single.course.code, 'DCC203');
    expect(overview.single.sessions.single.id, 'session-1');
    expect(overview.single.sessions.single.secondPing, 'fora');
    expect(overview.single.sessions.single.calendarStatus, 'no_call');
    expect(overview.single.sessions.single.absences, 0);
  });

  test('rejects malformed academic overview data', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'items': [
              {
                'course': _courseJson,
                'sessions': [
                  {..._sessionJson, 'absences': 3},
                ],
              },
            ],
          }),
          200,
        ),
      ),
    );

    await expectLater(
      transport.loadOverview(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

  test('previews and atomically saves a complete schedule', () async {
    final requests = <http.Request>[];
    final response = {
      'course': _courseJson,
      'meetings': [_meetingJson],
      'changes': {
        'meeting_upserts': 1,
        'meeting_deletes': 0,
        'session_upserts': 3,
        'session_deletes': 0,
        'destructive_deletes': 0,
      },
    };
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(jsonEncode(response), 200);
      }),
    );

    final preview = await transport.getSchedule('course-1');
    final saved = await transport.saveSchedule(
      courseId: 'course-1',
      startsOn: DateTime.utc(2026, 8, 4),
      endsOn: DateTime.utc(2026, 12, 1),
      meetings: preview.meetings,
      confirmDestructive: false,
    );

    expect(preview.course.id, 'course-1');
    expect(preview.meetings.single.startMinutes, 1140);
    expect(saved.changes.sessionUpserts, 3);
    expect(requests.map((request) => request.method), ['GET', 'PUT']);
    expect(requests.first.url.path, '/v1/courses/course-1/schedule');
    expect(jsonDecode(requests.last.body), {
      'starts_on': '2026-08-04T00:00:00.000Z',
      'ends_on': '2026-12-01T00:00:00.000Z',
      'meetings': [
        {
          'id': 'tuesday-19',
          'weekday': 2,
          'start_minutes': 1140,
          'lesson_count': 2,
          'call_count': 1,
        },
      ],
      'confirm_destructive': false,
    });
  });

  test(
    'saves automatic and corrected attendance through session endpoints',
    () async {
      final requests = <http.Request>[];
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient((request) async {
          requests.add(request);
          return http.Response(
            jsonEncode({
              'status': requests.length == 1 ? 'chegou_atrasado' : 'pendente',
              'absences': requests.length == 1 ? 1 : null,
              'updated_at': '2026-10-08T18:30:00Z',
            }),
            200,
          );
        }),
      );

      final automatic = await transport.saveAttendance(
        courseId: 'course-1',
        sessionId: 'session-1',
        status: 'chegou_atrasado',
        maximumAbsences: 2,
        useDefaultAbsences: true,
      );
      final correction = await transport.saveAttendance(
        courseId: 'course-1',
        sessionId: 'session-1',
        status: 'pendente',
        maximumAbsences: 2,
        useDefaultAbsences: false,
      );

      expect(requests.map((request) => request.method), ['PUT', 'PUT']);
      expect(
        requests.first.url.path,
        '/v1/courses/course-1/sessions/session-1/attendance',
      );
      expect(jsonDecode(requests.first.body), {'status': 'chegou_atrasado'});
      expect(jsonDecode(requests.last.body), {
        'status': 'pendente',
        'absences': null,
      });
      expect(automatic.absences, 1);
      expect(automatic.updatedAt, DateTime.utc(2026, 10, 8, 18, 30));
      expect(correction.status, 'pendente');
      expect(correction.absences, isNull);
    },
  );

  test('saves a calendar category and validates the response', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (request) async => http.Response(
          jsonEncode({
            'calendar_status': 'no_call',
            'updated_at': '2026-10-08T18:30:00Z',
          }),
          200,
        ),
      ),
    );

    final result = await transport.saveCalendarStatus(
      courseId: 'course-1',
      sessionId: 'session-1',
      calendarStatus: 'no_call',
    );

    expect(result.calendarStatus, 'no_call');
    expect(result.updatedAt, DateTime.utc(2026, 10, 8, 18, 30));
  });

  test(
    'rejects malformed session mutation responses and unsafe session ids',
    () async {
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _Tokens(),
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({
              'status': 'presente',
              'absences': 0,
              'updated_at': 'not-a-date',
            }),
            200,
          ),
        ),
      );

      await expectLater(
        transport.saveAttendance(
          courseId: 'course-1',
          sessionId: 'session-1',
          status: 'presente',
          maximumAbsences: 2,
          useDefaultAbsences: true,
        ),
        throwsA(isA<PythonBackendException>()),
      );
      await expectLater(
        transport.saveCalendarStatus(
          courseId: 'course-1',
          sessionId: 'bad/id',
          calendarStatus: 'scheduled',
        ),
        throwsArgumentError,
      );
    },
  );

  test('rejects a session mutation that changes the requested value', () async {
    final responses = [
      {
        'status': 'ausente',
        'absences': 2,
        'updated_at': '2026-10-08T18:30:00Z',
      },
      {'calendar_status': 'cancelled', 'updated_at': '2026-10-08T18:30:00Z'},
    ];
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(jsonEncode(responses.removeAt(0)), 200),
      ),
    );

    await expectLater(
      transport.saveAttendance(
        courseId: 'course-1',
        sessionId: 'session-1',
        status: 'presente',
        maximumAbsences: 2,
        useDefaultAbsences: true,
      ),
      throwsA(isA<PythonBackendException>()),
    );
    await expectLater(
      transport.saveCalendarStatus(
        courseId: 'course-1',
        sessionId: 'session-1',
        calendarStatus: 'no_call',
      ),
      throwsA(isA<PythonBackendException>()),
    );
  });

  test('preserves the bounded destructive-conflict count', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (_) async => http.Response(
          jsonEncode({
            'error': 'schedule_destructive_conflict',
            'destructive_sessions': 2,
          }),
          409,
        ),
      ),
    );

    await expectLater(
      transport.saveSchedule(
        courseId: 'course-1',
        startsOn: null,
        endsOn: null,
        meetings: const [],
        confirmDestructive: false,
      ),
      throwsA(
        isA<PythonBackendException>()
            .having(
              (error) => error.code,
              'code',
              PythonBackendError.destructiveConflict,
            )
            .having((error) => error.destructiveSessions, 'count', 2),
      ),
    );
  });

  test('rejects malformed schedule responses', () async {
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient((_) async => http.Response(jsonEncode({}), 200)),
    );

    await expectLater(
      transport.getSchedule('course-1'),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'code',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

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
    expect(requests[1].headers['X-Firebase-AppCheck'], 'regular-app-2');
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
        return http.Response(
          jsonEncode({
            'connected': true,
            'created_at': 1000,
            'expires_at': 33400,
          }),
          200,
        );
      }),
    );

    await transport.connectUFMG(
      username: '2025019259',
      password: 'private-password',
    );

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

  test('gives the complete academic sync a longer bounded timeout', () async {
    final client = MockClient((request) async {
      await Future<void>.delayed(const Duration(milliseconds: 15));
      if (request.url.path == '/v1/identity') {
        return http.Response(jsonEncode({'authenticated': true}), 200);
      }
      return http.Response('{}', 200);
    });
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: client,
      timeout: const Duration(milliseconds: 5),
      longRunningTimeout: const Duration(milliseconds: 50),
    );

    await expectLater(
      transport.verifyIdentity(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'short request timeout',
          PythonBackendError.timeout,
        ),
      ),
    );
    await expectLater(
      transport.syncAllAcademicData(),
      throwsA(
        isA<PythonBackendException>().having(
          (error) => error.code,
          'response reached the parser instead of timing out',
          PythonBackendError.invalidResponse,
        ),
      ),
    );
  });

  test('rejects missing credentials before the network boundary', () async {
    final client = MockClient((_) async => fail('must not call backend'));
    final transport = PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(idToken: '', appCheckTokenValue: ''),
      client: client,
    );

    await expectLater(
      transport.verifyIdentity(),
      throwsA(
        isA<PythonBackendException>()
            .having(
              (error) => error.code,
              'code',
              PythonBackendError.credentialsUnavailable,
            )
            .having(
              (error) => error.credential,
              'credential',
              PythonBackendCredential.firebaseIdentity,
            ),
      ),
    );
  });

  test(
    'classifies App Check acquisition failures before the network boundary',
    () async {
      final client = MockClient((_) async => fail('must not call backend'));
      final tokens = _FailingAppCheckTokens();
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: tokens,
        client: client,
      );

      await expectLater(
        transport.verifyIdentity(),
        throwsA(
          isA<PythonBackendException>()
              .having(
                (error) => error.code,
                'code',
                PythonBackendError.credentialsUnavailable,
              )
              .having(
                (error) => error.credential,
                'credential',
                PythonBackendCredential.appCheck,
              )
              .having(
                (error) => error.toString(),
                'sanitized diagnostic',
                allOf(
                  contains('stage=credentials'),
                  contains('path=/v1/identity'),
                  contains('credential=appCheck, cause=StateError'),
                ),
              ),
        ),
      );
      expect(tokens.calls, 1);
    },
  );

  test(
    'classifies Firebase identity acquisition failures before the network boundary',
    () async {
      final client = MockClient((_) async => fail('must not call backend'));
      final transport = PythonBackendTransport(
        endpoint: Uri.parse('https://backend.example'),
        tokens: _FailingIdentityTokens(),
        client: client,
      );

      await expectLater(
        transport.verifyIdentity(),
        throwsA(
          isA<PythonBackendException>()
              .having(
                (error) => error.code,
                'code',
                PythonBackendError.credentialsUnavailable,
              )
              .having(
                (error) => error.credential,
                'credential',
                PythonBackendCredential.firebaseIdentity,
              )
              .having((error) => error.causeType, 'safe cause', 'StateError'),
        ),
      );
    },
  );
}

final class _SilentLogger implements AppLogger {
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {}

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {}
}

const _courseJson = <String, Object?>{
  'id': 'course-1',
  'code': 'DCC203',
  'name': 'POO',
  'workload': 1,
  'term': '2026-2',
  'starts_on': '2026-08-04T00:00:00Z',
  'ends_on': '2026-12-01T00:00:00Z',
  'created_at': '2026-08-01T12:00:00Z',
  'updated_at': '2026-08-01T12:00:00Z',
};

const _meetingJson = <String, Object?>{
  'id': 'tuesday-19',
  'weekday': 2,
  'start_minutes': 1140,
  'end_minutes': 1240,
  'lesson_count': 2,
  'call_count': 1,
  'created_at': '2026-08-01T12:00:00Z',
  'updated_at': '2026-08-01T12:00:00Z',
};

const _sessionJson = <String, Object?>{
  'id': 'session-1',
  'starts_at': '2026-10-08T10:00:00Z',
  'ends_at': '2026-10-08T11:40:00Z',
  'lesson_count': 2,
  'call_count': 1,
  'first_ping': 'no_campus',
  'second_ping': null,
  'attendance_status': 'presente',
  'absences': 0,
  'calendar_status': 'no_call',
  'assessment_title': 'Prova 1',
  'created_at': '2026-08-01T12:00:00Z',
  'updated_at': '2026-10-08T12:00:00Z',
};

final class _Tokens implements PythonBackendTokens {
  _Tokens({this.idToken = 'id', this.appCheckTokenValue = 'app'});

  final String idToken;
  final String appCheckTokenValue;
  final idTokenRefreshes = <bool>[];
  int regularAppCheckCalls = 0;
  int limitedAppCheckCalls = 0;
  int appCheckCalls = 0;

  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    idTokenRefreshes.add(forceRefresh);
    if (idToken.isEmpty) return '';
    return '$idToken-${idTokenRefreshes.length}-${forceRefresh ? 'fresh' : 'cached'}';
  }

  @override
  Future<String> appCheckToken({required bool limitedUse}) async {
    appCheckCalls += 1;
    if (appCheckTokenValue.isEmpty) return '';
    if (limitedUse) {
      limitedAppCheckCalls += 1;
      return '$appCheckTokenValue-$limitedAppCheckCalls';
    }
    regularAppCheckCalls += 1;
    return 'regular-$appCheckTokenValue-$regularAppCheckCalls';
  }
}

final class _FailingAppCheckTokens implements PythonBackendTokens {
  _FailingAppCheckTokens([this.error]);
  final Object? error;
  int calls = 0;

  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async => 'id';

  @override
  Future<String> appCheckToken({required bool limitedUse}) async {
    calls++;
    throw error ?? StateError('App Check attestation failed');
  }
}

final class _DelayedRegularAppCheckTokens implements PythonBackendTokens {
  final regularToken = Completer<String>();
  int regularCalls = 0;

  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async => 'id';

  @override
  Future<String> appCheckToken({required bool limitedUse}) {
    if (limitedUse) return Future.value('limited');
    regularCalls++;
    return regularToken.future;
  }
}

final class _FailingIdentityTokens implements PythonBackendTokens {
  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async {
    throw StateError('Firebase identity acquisition failed');
  }

  @override
  Future<String> appCheckToken({required bool limitedUse}) async => 'app';
}
