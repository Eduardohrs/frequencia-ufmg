import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/course_activity_snapshot_cache.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';
import 'package:frequencia_ufmg/features/activities/course_workspace_page.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:timezone/data/latest.dart' as tz;

final now = DateTime.utc(2026, 10, 28, 12);
final course = CourseRecord(
  id: 'poo',
  code: 'ELE631',
  name: 'POO',
  workload: 60,
  term: '2026-2',
  createdAt: now,
  updatedAt: now,
);
final activity = PythonMoodleActivity(
  id: '20',
  title: 'Protótipo',
  kind: 'assign',
  url: Uri.parse('https://virtual.ufmg.br/20262/mod/assign/view.php?id=20'),
);
PythonMoodleDate date(String id, String title) => PythonMoodleDate(
  id: id,
  courseId: 'poo',
  courseCode: 'ELE631',
  title: title,
  dueAt: now.add(const Duration(days: 2)),
  kind: 'assignment',
);

void main() {
  tz.initializeTimeZones();
  testWidgets(
    'failure opening synchronization leaves the saved activity available',
    (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: CourseWorkspacePage(
            course: course,
            gateway: _Gateway(),
            logger: FirestoreAppLogger(
              store: _Logs(),
              currentUserId: () => 'owner',
              platform: 'web',
            ),
            now: () => now,
            onConnect: () async => throw StateError('route unavailable'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sincronizar Moodle'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('A cópia salva continua disponível'),
        findsOneWidget,
      );
      expect(find.text('Protótipo'), findsOneWidget);
    },
  );
  testWidgets(
    'a fresh page opens the saved activity after restart with backend and Moodle unavailable',
    (tester) async {
      SharedPreferencesAsyncPlatform.instance =
          InMemorySharedPreferencesAsync.empty();
      final logs = _Logs();
      final gateway = _Gateway();
      await tester.pumpWidget(_app(gateway, logs, userId: 'owner'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Última sincronização:'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      final offline = _Gateway()
        ..readError = StateError('server unavailable')
        ..detailError = StateError('server unavailable');
      await tester.pumpWidget(_app(offline, logs, userId: 'owner'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Cópia local:'), findsOneWidget);
      expect(find.text('Protótipo'), findsOneWidget);
      await tester.tap(find.text('Protótipo'));
      await tester.pumpAndSettle();
      expect(find.text('Enunciado completo'), findsOneWidget);
      expect(offline.detailCalls, 0);
      await tester.tap(find.byTooltip('Fechar atividade'));
      await tester.pumpAndSettle();
      expect(
        logs.documents.any(
          (d) => d['event'] == 'course_activity_open_succeeded',
        ),
        isTrue,
      );
      final saved = await CourseActivitySnapshotCache().read(
        'owner',
        'poo',
        '2026-2',
      );
      expect(saved!.details.single.description, 'Enunciado completo');
      await tester.pumpWidget(const SizedBox());
      await tester.pumpAndSettle();
      await tester.pumpWidget(_app(offline, logs, userId: 'different'));
      await tester.pumpAndSettle();
      expect(find.text('Protótipo'), findsNothing);
      expect(find.textContaining('Não foi possível atualizar'), findsOneWidget);
    },
  );
  testWidgets(
    'cache failures are diagnosed without blocking the saved server snapshot',
    (tester) async {
      final logs = _Logs();
      await tester.pumpWidget(
        _app(_Gateway(), logs, userId: 'owner', cache: _BrokenSnapshotCache()),
      );
      await tester.pumpAndSettle();
      expect(find.text('Protótipo'), findsOneWidget);
      expect(
        find.textContaining(
          'Não foi possível salvar esta cópia no dispositivo',
        ),
        findsOneWidget,
      );
      final errors = logs.documents
          .where((d) => d['event'] == 'app_exception')
          .map((d) => jsonDecode(d['errorDetails']! as String))
          .toList();
      expect(
        errors.any(
          (d) =>
              d['context'] == 'activity_snapshot_cache_read' ||
              d['stage'] == 'activity_snapshot_cache_read',
        ),
        isTrue,
      );
      expect(
        logs.documents.where((d) => d['event'] == 'app_exception'),
        hasLength(2),
      );
    },
  );
  testWidgets(
    'plan dates use local readable dates and retain unknown source labels',
    (tester) async {
      final gateway = _Gateway()
        ..plan = {
          'criteria': [],
          'schedule': [
            {
              'subject': 'Data a definir',
              'date': 'A definir',
              'starts_at': '19:00',
            },
          ],
          'assessments': [
            {
              'title': 'Prova',
              'scheduled_at': '2026-11-02T22:00:00Z',
              'value': '30',
            },
          ],
        };
      await tester.pumpWidget(_app(gateway, _Logs()));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Plano'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Avaliações (1)'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cronograma (1)'));
      await tester.pumpAndSettle();
      expect(find.text('02/11/2026 19:00 · Valor: 30'), findsOneWidget);
      expect(find.text('A definir · 19:00'), findsOneWidget);
    },
  );
  testWidgets(
    'attachment authorization failure leaves assignment content usable',
    (tester) async {
      final gateway = _Gateway()
        ..detail = PythonMoodleActivityDetail(
          activity: activity,
          description: 'Texto preservado',
          datesText: '',
          hasDueDate: false,
          submissionState: 'unknown',
          submissionText: '',
          files: [],
          attachmentCount: 1,
          term: '2026-2',
        );
      await tester.pumpWidget(_app(gateway, _Logs()));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Protótipo'));
      await tester.pumpAndSettle();
      expect(find.text('Texto preservado'), findsOneWidget);
      expect(gateway.detailCalls, 0);
      await tester.tap(find.text('instructions.pdf'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Não foi possível autorizar os anexos.'),
        findsOneWidget,
      );
      await tester.tap(find.byTooltip('Fechar atividade'));
      await tester.pumpAndSettle();
    },
  );
  testWidgets(
    'course workspace reads activities, edits independent deadlines and shows full plan',
    (tester) async {
      final gateway = _Gateway();
      final store = _Logs();
      await tester.pumpWidget(_app(gateway, store));
      await tester.pumpAndSettle();
      expect(find.text('Protótipo'), findsOneWidget);
      await tester.tap(find.text('Protótipo'));
      await tester.pumpAndSettle();
      expect(find.text('Enunciado completo'), findsOneWidget);
      expect(find.text('Nenhum envio feito'), findsOneWidget);
      await tester.tap(find.byTooltip('Fechar atividade'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Prazos'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('workspace-add-date')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.text('Informe um título'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('workspace-date-title')),
        'Prazo pessoal',
      );
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Questionário').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('workspace-pick-date')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('workspace-pick-time')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.text('Prazo pessoal'), findsOneWidget);
      expect(gateway.dates.last.id, startsWith('manual-'));
      await tester.tap(find.text('Prova importada'));
      await tester.pumpAndSettle();
      expect(
        find.text('Sua correção será preservada nas próximas sincronizações.'),
        findsOneWidget,
      );
      await tester.enterText(
        find.byKey(const Key('workspace-date-title')),
        'Correção pessoal',
      );
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(gateway.dates.first.title, 'Correção pessoal');
      await tester.tap(find.byTooltip('Excluir prazo'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();
      expect(find.text('Prazo pessoal'), findsOneWidget);
      await tester.tap(find.byTooltip('Excluir prazo'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Excluir'));
      await tester.pumpAndSettle();
      expect(gateway.dates, hasLength(1));
      await tester.tap(find.text('Plano'));
      await tester.pumpAndSettle();
      expect(find.text('Soma das notas'), findsOneWidget);
      await tester.tap(find.text('Avaliações (1)'));
      await tester.pumpAndSettle();
      expect(find.text('Prova 1'), findsOneWidget);
      await tester.tap(find.text('Cronograma (1)'));
      await tester.pumpAndSettle();
      expect(find.text('Revisão'), findsOneWidget);
      final successes = store.documents.where(
        (d) => d['event'] == 'course_workspace_mutation_succeeded',
      );
      expect(successes, hasLength(3));
      expect(
        successes.every(
          (d) => jsonDecode(d['details']! as String)['course_id'] == 'poo',
        ),
        isTrue,
      );
    },
  );
  testWidgets(
    'failed section can retry while dates stay usable and a failed save keeps data',
    (tester) async {
      final gateway = _Gateway()..readError = StateError('offline');
      final store = _Logs();
      await tester.pumpWidget(_app(gateway, store));
      await tester.pumpAndSettle();
      expect(find.textContaining('Não foi possível atualizar'), findsOneWidget);
      gateway.readError = null;
      await tester.tap(find.text('Tentar novamente'));
      await tester.pumpAndSettle();
      expect(find.text('Protótipo'), findsOneWidget);
      gateway.detailError = StateError('source timeout');
      await tester.tap(find.text('Protótipo'));
      await tester.pumpAndSettle();
      expect(find.text('Enunciado completo'), findsOneWidget);
      await tester.tap(find.byTooltip('Fechar atividade'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Prazos'));
      await tester.pumpAndSettle();
      gateway.saveError = StateError('denied');
      await tester.tap(find.text('Prova importada'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('workspace-date-title')),
        'Não salvar',
      );
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.text('Prova importada'), findsOneWidget);
      expect(find.textContaining('Não foi possível salvar'), findsOneWidget);
      gateway.plan = null;
      await tester.tap(find.text('Plano'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Nenhum plano de ensino importado'),
        findsOneWidget,
      );
      final errors = store.documents
          .where((d) => d['event'] == 'app_exception')
          .toList();
      expect(errors, hasLength(2));
      expect(
        jsonDecode(errors.first['errorDetails']! as String)['stage'],
        'activities',
      );
    },
  );
  for (final mode in ['web', 'web-denied', 'saved', 'queue', 'failure']) {
    testWidgets(
      'activity attachments use direct download and preserve offline behavior: $mode',
      (tester) async {
        final file = PythonMoodleMaterialFile(
          name: 'instructions.pdf',
          url: Uri.parse(
            'https://virtual.ufmg.br/20262/tokenpluginfile.php/syntheticprivate123456/1/mod_assign/introattachment/0/instructions.pdf?forcedownload=1',
          ),
          size: 0,
          mimeType: 'application/pdf',
        );
        final gateway = _Gateway()
          ..detail = PythonMoodleActivityDetail(
            activity: activity,
            description: '',
            datesText: 'Vencimento: 1/11',
            hasDueDate: true,
            submissionState: 'unknown',
            submissionText: '',
            files: [file],
            attachmentCount: 1,
            term: '2026-2',
          );
        final store = _Logs();
        final cache = mode == 'queue'
            ? _QueueCache()
            : _FileCache(
                available: !mode.startsWith('web'),
                fail: mode == 'failure',
              );
        final opened = <Uri>[];
        await tester.pumpWidget(
          _app(
            gateway,
            store,
            files: cache,
            open: (uri) async {
              opened.add(uri);
              return mode != 'web-denied';
            },
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.text('Protótipo'));
        await tester.pumpAndSettle();
        expect(
          find.text('Situação do envio não informada pelo Moodle.'),
          findsOneWidget,
        );
        await tester.ensureVisible(find.text('instructions.pdf'));
        await tester.tap(find.text('instructions.pdf'));
        await tester.pumpAndSettle();
        if (mode.startsWith('web')) {
          expect(opened.single, file.url);
        } else if (mode == 'queue') {
          expect((cache as _QueueCache).queued.single.source, file.url);
        } else if (mode == 'saved') {
          expect(cache.saved.single.expectedSize, 0);
        }
        expect(
          store.documents.toString(),
          isNot(contains('syntheticprivate123456')),
        );
        final failed = mode == 'failure' || mode == 'web-denied';
        expect(
          store.documents.any(
            (d) =>
                d['event'] ==
                (failed
                    ? 'app_exception'
                    : 'course_activity_download_scheduled'),
          ),
          isTrue,
        );
        await tester.tap(find.byTooltip('Fechar atividade'));
        await tester.pumpAndSettle();
      },
    );
  }

  testWidgets(
    'reconnect is explicit and empty sections remain distinct from failures',
    (tester) async {
      final gateway = _Gateway()..readError = StateError('expired');
      final store = _Logs();
      var connections = 0;
      await tester.pumpWidget(
        MaterialApp(
          home: CourseWorkspacePage(
            course: course,
            gateway: gateway,
            logger: FirestoreAppLogger(
              store: store,
              currentUserId: () => 'owner',
              platform: 'web',
            ),
            now: () => now,
            onConnect: () async {
              connections++;
              gateway.readError = null;
              gateway.activities = [];
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Conexão UFMG'));
      await tester.pumpAndSettle();
      expect(connections, 1);
      expect(
        find.text('Nenhuma atividade disponível nesta disciplina.'),
        findsOneWidget,
      );
      gateway.dates.clear();
      await tester.tap(find.text('Prazos'));
      await tester.pumpAndSettle();
      expect(find.text('Nenhum prazo cadastrado.'), findsOneWidget);
      await tester.tap(find.byKey(const Key('workspace-add-date')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();
      gateway.plan = {'criteria': [], 'schedule': [], 'assessments': []};
      await tester.tap(find.text('Plano'));
      await tester.pumpAndSettle();
      expect(find.text('Não informados no plano.'), findsOneWidget);
    },
  );
}

Widget _app(
  _Gateway gateway,
  _Logs store, {
  MaterialFileCache? files,
  Future<bool> Function(Uri)? open,
  String? userId,
  CourseActivitySnapshotCache? cache,
}) => MaterialApp(
  home: CourseWorkspacePage(
    course: course,
    gateway: gateway,
    logger: FirestoreAppLogger(
      store: store,
      currentUserId: () => 'owner',
      platform: 'web',
    ),
    now: () => now,
    materialFileCache: files,
    userId: userId,
    snapshotCache: cache,
    openExternalUri: open,
  ),
);

class _Gateway implements BackendAcademicWorkspaceGateway {
  final dates = [date('moodle-1', 'Prova importada')];
  Object? readError, detailError, saveError;
  int detailCalls = 0;
  List<PythonMoodleActivity> activities = [activity];
  PythonMoodleActivityDetail? detail;
  Map<String, Object?>? plan = {
    'criteria': [
      {'description': 'Soma das notas', 'value': '100'},
    ],
    'schedule': [
      {'subject': 'Revisão', 'date': '2026-11-01', 'starts_at': '19:00'},
    ],
    'assessments': [
      {'title': 'Prova 1', 'scheduled_at': '2026-11-02', 'value': '30'},
    ],
  };
  @override
  Future<PythonCourseActivitySnapshot> loadCourseActivitySnapshot(
    String id,
  ) async {
    if (readError != null) throw readError!;
    return PythonCourseActivitySnapshot.fromJson({
      'course_id': id,
      'term': '2026-2',
      'synced_at': '2026-10-28T12:00:00Z',
      'activities': [
        for (final a in activities)
          {
            'source_id': a.id,
            'title': a.title,
            'kind': a.kind,
            'url': a.url.toString(),
            'origin': a.origin,
            'description': detail?.description ?? 'Enunciado completo',
            'dates_text': detail?.datesText ?? '',
            'has_due_date': detail?.hasDueDate ?? false,
            'submission_state': detail?.submissionState ?? 'not_submitted',
            'submission_text': detail?.submissionText ?? 'Nenhum envio feito',
            'term': '2026-2',
            'attachments': [
              for (var i = 0; i < (detail?.attachmentCount ?? 0); i++)
                {'name': 'instructions.pdf'},
            ],
            'files': [],
          },
      ],
    });
  }

  @override
  Future<List<PythonMoodleActivity>> listCourseActivities(String id) async {
    if (readError != null) throw readError!;
    return activities;
  }

  @override
  Future<PythonMoodleActivityDetail> loadCourseActivity(
    String courseId,
    String id,
  ) async {
    detailCalls++;
    if (detailError != null) throw detailError!;
    return detail ??
        PythonMoodleActivityDetail(
          activity: activity,
          description: 'Enunciado completo',
          datesText: '',
          hasDueDate: false,
          submissionState: 'not_submitted',
          submissionText: 'Nenhum envio feito',
          files: [],
          attachmentCount: 0,
          term: '2026-2',
        );
  }

  @override
  Future<List<PythonMoodleDate>> listCourseDates(String id) async =>
      List.of(dates);
  @override
  Future<Map<String, Object?>?> loadCoursePlan(String id) async => plan;
  @override
  Future<void> saveCourseDate(
    String courseId,
    String id, {
    required String title,
    required DateTime dueAt,
    required String kind,
  }) async {
    if (saveError != null) throw saveError!;
    final i = dates.indexWhere((d) => d.id == id);
    if (i >= 0) {
      dates[i] = date(id, title);
    } else {
      dates.add(date(id, title));
    }
  }

  @override
  Future<void> deleteCourseDate(String courseId, String id) async {
    dates.removeWhere((d) => d.id == id);
  }
}

class _Logs implements OperationalLogStore {
  final documents = <Map<String, Object?>>[];
  @override
  Future<void> add(String id, Map<String, Object?> document) async =>
      documents.add(document);
}

class _FileCache implements MaterialFileCache {
  _FileCache({this.available = true, this.fail = false});
  final bool available, fail;
  final saved = <MaterialDownload>[];
  @override
  bool get isAvailable => available;
  @override
  Future<CachedMaterialFile> save(MaterialDownload download) async {
    if (fail) throw StateError('download rejected');
    saved.add(download);
    return CachedMaterialFile(
      id: download.id,
      name: download.name,
      size: 10,
      mimeType: download.mimeType,
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => throw UnimplementedError();
  @override
  void dispose() {}
}

class _QueueCache extends _FileCache
    implements BackgroundMaterialDownloadQueue {
  final queued = <MaterialDownload>[];
  @override
  Future<void> enqueue(MaterialDownload download) async {
    queued.add(download);
  }
}

class _BrokenSnapshotCache extends CourseActivitySnapshotCache {
  @override
  Future<PythonCourseActivitySnapshot?> read(
    String user,
    String course,
    String term,
  ) async => throw StateError('local read unavailable');
  @override
  Future<void> write(
    String user,
    PythonCourseActivitySnapshot snapshot,
  ) async => throw StateError('local storage full');
}
