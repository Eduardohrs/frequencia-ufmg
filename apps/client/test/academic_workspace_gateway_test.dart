import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, Object?> _date({String source = 'manual'}) => {
  'id': '$source-one',
  'source': source,
  'source_id': 'one',
  'course_id': 'poo',
  'course_code': 'ELE631',
  'title': 'Prazo',
  'kind': 'assignment',
  'due_at': '2026-11-01T12:00:00Z',
  'created_at': '2026-10-28T12:00:00Z',
  'updated_at': '2026-10-28T12:00:00Z',
};
Map<String, Object?> _activity() => {
  'source_id': '20',
  'title': 'Protótipo',
  'kind': 'assign',
  'url': 'https://virtual.ufmg.br/20262/mod/assign/view.php?id=20',
  'relevance': 'other',
};
Map<String, Object?> _detail() => {
  ..._activity(),
  'description': 'Prepare o protótipo',
  'dates_text': 'Vencimento: 01/11',
  'has_due_date': true,
  'submission_state': 'not_submitted',
  'submission_text': 'Nenhum envio feito',
  'attachments': [],
  'files': [],
  'term': '2026-2',
  'moodle_course_id': '3701',
};
PythonBackendTransport _transport(Object? Function(http.Request) body) =>
    PythonBackendTransport(
      endpoint: Uri.parse('https://backend.example'),
      tokens: _Tokens(),
      client: MockClient(
        (request) async => http.Response(jsonEncode(body(request)), 200),
      ),
    );
void main() {
  test(
    'full snapshot survives serialization and rejects credentials or a different course',
    () async {
      final value = <String, Object?>{
        'course_id': 'poo',
        'term': '2026-2',
        'synced_at': '2026-10-28T12:00:00Z',
        'activities': [
          {
            ..._detail(),
            'attachments': [
              {
                'name': 'teacher.pdf',
                'url':
                    'https://virtual.ufmg.br/20262/pluginfile.php/1/mod_assign/introattachment/0/teacher.pdf',
              },
            ],
          },
        ],
      };
      final snapshot = await _transport(
        (_) => value,
      ).workspace.loadCourseActivitySnapshot('poo');
      expect(snapshot.activities.single.title, 'Protótipo');
      expect(snapshot.details.single.attachmentNames, ['teacher.pdf']);
      expect(
        PythonCourseActivitySnapshot.fromJson(
          snapshot.toJson(),
        ).details.single.description,
        'Prepare o protótipo',
      );
      expect(
        jsonEncode(snapshot.toJson()),
        isNot(contains('pluginfile.php/1')),
      );
      for (final invalid in [
        {...value, 'course_id': 'other'},
        {...value, 'course_id': '../poo'},
        {...value, 'term': 'bad'},
        {
          ...value,
          'activities': [_detail(), _detail()],
        },
        {
          ...value,
          'activities': [
            {..._detail(), 'term': '2026-1'},
          ],
        },
        {
          ...value,
          'activities': [
            {
              ..._detail(),
              'files': [
                {'name': 'x', 'url': 'secret'},
              ],
            },
          ],
        },
      ]) {
        await expectLater(
          _transport(
            (_) => invalid,
          ).workspace.loadCourseActivitySnapshot('poo'),
          throwsA(isA<PythonBackendException>()),
        );
      }
      expect(
        PythonActivitySyncSummary.fromJson({
          'updated': 2,
          'failed': 1,
          'failed_courses': [],
        }).message,
        contains('cópias anteriores preservadas'),
      );
      for (final invalid in [
        <String, Object?>{},
        {'updated': -1, 'failed': 0, 'failed_courses': []},
        {'updated': 1, 'failed': 0, 'failed_courses': 'bad'},
      ]) {
        expect(
          () => PythonActivitySyncSummary.fromJson(invalid),
          throwsFormatException,
        );
      }
    },
  );
  test(
    'activity detail decodes teacher files for the existing direct-download flow',
    () async {
      final detail = await _transport(
        (_) => {
          ..._detail(),
          'attachments': [
            {'name': 'instructions.pdf'},
          ],
          'files': [
            {
              'name': 'instructions.pdf',
              'url':
                  'https://virtual.ufmg.br/20262/tokenpluginfile.php/syntheticprivate123456/1/mod_assign/introattachment/0/instructions.pdf?forcedownload=1',
              'size': 0,
              'mime_type': 'application/pdf',
            },
          ],
        },
      ).workspace.loadCourseActivity('poo', '20');
      expect(detail.files.single.name, 'instructions.pdf');
      expect(detail.attachmentCount, 1);
    },
  );
  test(
    'full plan rows are checked before rendering and preserve metaturma origin',
    () async {
      final rows = <String, Object?>{
        'criteria': [
          {'description': 'Notas', 'value': '100'},
        ],
        'schedule': [
          {'subject': 'Aula', 'date': '2026-11-01', 'starts_at': '19:00'},
        ],
        'assessments': [
          {
            'title': 'Prova',
            'scheduled_at': '2026-11-01T19:00:00-03:00',
            'value': '30',
          },
        ],
      };
      Future<Map<String, Object?>?> load(Map<String, Object?> plan) =>
          _transport(
            (_) => {
              'plan': {'plan': plan},
            },
          ).workspace.loadCoursePlan('poo');
      expect(await load(rows), rows);
      for (final section in rows.keys) {
        for (final invalid in [
          5,
          [5],
          [{}],
          [
            {'description': '', 'value': 5},
          ],
        ]) {
          await expectLater(
            load({...rows, section: invalid}),
            throwsA(isA<PythonBackendException>()),
          );
        }
      }
      expect(
        PythonMoodleActivity.fromJson({
          ..._activity(),
          'origin': 'metaturma',
        }).origin,
        'metaturma',
      );
      expect(
        () =>
            PythonMoodleActivity.fromJson({..._activity(), 'origin': 'other'}),
        throwsFormatException,
      );
    },
  );
  test(
    'workspace endpoints validate their responses and preserve date mutation fields',
    () async {
      final requests = <http.Request>[];
      final transport = _transport((request) {
        requests.add(request);
        final p = request.url.path;
        if (p.endsWith('/plan')) {
          return {
            'plan': {
              'plan': {'criteria': [], 'schedule': [], 'assessments': []},
            },
          };
        }
        if (p.endsWith('/activities')) {
          return {
            'activities': [_activity()],
          };
        }
        if (p.endsWith('/activities/20')) return _detail();
        if (request.method == 'PUT') return {'date': _date()};
        if (request.method == 'DELETE') return {'deleted': true};
        return {
          'dates': [_date()],
        };
      });
      final gateway = transport.workspace;
      expect((await gateway.listCourseDates('poo')).single.title, 'Prazo');
      await gateway.saveCourseDate(
        'poo',
        'manual-one',
        title: 'Prazo',
        dueAt: DateTime.utc(2026, 11, 1, 12),
        kind: 'assignment',
      );
      expect(
        jsonDecode(requests.last.body)['due_at'],
        '2026-11-01T12:00:00.000Z',
      );
      await gateway.deleteCourseDate('poo', 'manual-one');
      expect(await gateway.loadCoursePlan('poo'), contains('criteria'));
      expect((await gateway.listCourseActivities('poo')).single.id, '20');
      final detail = await gateway.loadCourseActivity('poo', '20');
      expect(detail.submissionState, 'not_submitted');
      expect(detail.files, isEmpty);
      expect(
        requests.every((r) => r.headers['X-Academic-Contract'] == '2'),
        isTrue,
      );
      for (final response in [
        {'plan': null},
        {
          'plan': {
            'plan': {'criteria': [], 'schedule': [], 'assessments': []},
          },
        },
      ]) {
        await _transport((_) => response).workspace.loadCoursePlan('poo');
      }
      expect(
        PythonMoodleDate.fromJson({
          ..._date(source: 'moodle'),
          'manual_override': true,
        }).id,
        'moodle-one',
      );
      expect(
        () =>
            PythonMoodleDate.fromJson({..._date(), 'manual_override': 'wrong'}),
        throwsFormatException,
      );
    },
  );
  test(
    'malformed workspace responses and unsafe paths fail without leaking into UI',
    () async {
      final operations =
          <Future<dynamic> Function(BackendAcademicWorkspaceGateway)>[
            (g) => g.listCourseDates('poo'),
            (g) => g.listCourseActivities('poo'),
            (g) => g.loadCoursePlan('poo'),
            (g) => g.loadCourseActivity('poo', '20'),
            (g) => g.saveCourseDate(
              'poo',
              'manual-one',
              title: 'x',
              dueAt: DateTime.utc(2026),
              kind: 'event',
            ),
            (g) => g.deleteCourseDate('poo', 'manual-one'),
          ];
      for (final operation in operations) {
        await expectLater(
          operation(_transport((_) => {'unexpected': true}).workspace),
          throwsA(isA<PythonBackendException>()),
        );
      }
      expect(
        () => _transport((_) => {}).workspace.listCourseDates('../other'),
        throwsArgumentError,
      );
      await expectLater(
        _transport(
          (_) => {
            'plan': {
              'plan': {'criteria': 'wrong', 'schedule': [], 'assessments': []},
            },
          },
        ).workspace.loadCoursePlan('poo'),
        throwsA(isA<PythonBackendException>()),
      );
      for (final invalid in [
        <String, Object?>{},
        {..._activity(), 'url': 'https://other.example/view.php?id=20'},
        {..._activity(), 'source_id': '../20'},
      ]) {
        expect(
          () => PythonMoodleActivity.fromJson(invalid),
          throwsFormatException,
        );
      }
      for (final invalid in [
        {..._detail(), 'description': 5},
        {..._detail(), 'has_due_date': 'true'},
        {..._detail(), 'term': 'invalid'},
      ]) {
        expect(
          () => PythonMoodleActivityDetail.fromJson(invalid),
          throwsFormatException,
        );
      }
    },
  );
  test(
    'partial imports expose unmatched events and failed courses with balanced counts',
    () async {
      final issue = {
        'source_id': '7',
        'title': 'Atividade sem disciplina',
        'term': '2026-2',
        'reason': 'course_not_found',
        'moodle_course_id': '3702',
        'match_count': 0,
      };
      final failure = {
        'course_id': 'poo',
        'course_code': 'ELE631',
        'stage': 'dates_persistence',
        'reason': 'FirestoreUnavailable',
        'event_count': 1,
      };
      final summary = {
        'total': 3,
        'matched': 2,
        'unmatched': 1,
        'created': 1,
        'updated': 0,
        'unchanged': 0,
        'failed': 1,
        'removed': 1,
        'unmatched_events': [issue],
        'failed_courses': [failure],
      };
      final result = await _transport((_) => summary).importMoodleDates();
      expect(result.failed, 1);
      expect(result.removed, 1);
      expect(result.unmatchedEvents.single['title'], issue['title']);
      expect(result.failedCourses.single['course_id'], 'poo');
      for (final value in [
        'wrong',
        [{}],
        [
          {...issue, 'extra': 'x'},
        ],
        [
          {...issue, 'match_count': -1},
        ],
        [
          {...issue, 'title': ''},
        ],
        [
          {...issue, 'title': 5},
        ],
      ]) {
        await expectLater(
          _transport(
            (_) => {...summary, 'unmatched_events': value},
          ).importMoodleDates(),
          throwsA(isA<PythonBackendException>()),
        );
      }
    },
  );
}

class _Tokens implements PythonBackendTokens {
  @override
  Future<String> firebaseIdToken({required bool forceRefresh}) async => 'id';
  @override
  Future<String> appCheckToken({required bool limitedUse}) async => 'app';
}
