import 'dart:io';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/first_checkpoint.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/data/campus_location.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/attendance/first_checkpoint_page.dart';
import 'fixtures/campus_location_fixture.dart';

final now = DateTime.utc(2026, 10, 29, 15);
CourseRecord course() => CourseRecord(
  id: 'poo',
  code: 'ELE631',
  name: 'POO',
  workload: 60,
  term: '2026-2',
  createdAt: now,
  updatedAt: now,
);
SessionRecord session(
  String id, {
  SessionCalendarStatus status = SessionCalendarStatus.scheduled,
  DateTime? start,
  SituacaoFrequencia? attendance,
}) => SessionRecord(
  id: id,
  startsAt: start ?? now.add(const Duration(minutes: 10)),
  endsAt: now.add(const Duration(hours: 3)),
  lessonCount: QuantidadeAulas.two,
  callCount: NumeroChamadas.two,
  attendanceStatus: attendance,
  calendarStatus: status,
  createdAt: now,
  updatedAt: now,
);

class Sessions implements SessionRepository {
  List<SessionRecord> values = [];
  Future<List<SessionRecord>>? pending;
  Object? error;
  @override
  Future<List<SessionRecord>> listSessions(String id) async {
    if (error case final e?) throw e;
    return pending ?? values;
  }

  @override
  Future<void> saveSession(String id, SessionRecord s) async =>
      throw StateError('No attendance writes');
  @override
  Future<void> deleteSession(String c, String s) async =>
      throw StateError('No delete');
}

class Selection implements CampusSelectionGateway {
  String? value;
  bool fail = false;
  @override
  Future<String?> read() async {
    if (fail) throw StateError('selection unreadable');
    return value;
  }

  @override
  Future<void> save(String id) async {
    value = id;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(
    () => messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      null,
    ),
  );
  test(
    'full first checkpoint report survives real log document serialization',
    () async {
      final report =
          Map<String, Object?>.from(
            jsonDecode(
                  File(
                    'test/fixtures/background_location_report.json',
                  ).readAsStringSync(),
                )
                as Map,
          )..addAll({
            'first_ping': 'no_campus',
            'foreground_service_active': true,
            'checkpoint_expected_at_ms': 1793297997235,
            'lateness_ms': 95,
            'course_id': 'poo',
            'session_id': 'session-1',
          });
      final store = CheckpointLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'owner',
        platform: 'android',
      );
      final gateway = FirstCheckpointGateway(
        accountId: 'owner',
        logger: logger,
      );
      messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        (_) async => [report],
      );
      await gateway.perform('read');
      await Future<void>.delayed(Duration.zero);
      final persisted =
          jsonDecode(
                store.rows.singleWhere(
                      (row) => row['event'] == 'first_checkpoint_report',
                    )['details']
                    as String,
              )
              as Map;
      expect(persisted['first_ping'], 'no_campus');
      expect(persisted['foreground_service_active'], isTrue);
      expect(persisted['accuracy_m'], report['accuracy_m']);
      expect(persisted['operation_id'], report['operation_id']);
      messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        (_) async => throw PlatformException(
          code: 'checkpoint_failed',
          details: {
            'stage': 'schedule',
            'cause_message': 'battery_optimization_required',
          },
        ),
      );
      await expectLater(
        gateway.perform('schedule'),
        throwsA(isA<PlatformException>()),
      );
      await Future<void>.delayed(Duration.zero);
      expect(
        store.rows.last['errorDetails'].toString(),
        contains('battery_optimization_required'),
      );
    },
  );
  test(
    'real method channel scopes account and terminal reports retain full JSON',
    () async {
      final logger = CampusTestLogger();
      Map<dynamic, dynamic>? arguments;
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        if (call.method == 'deactivate') return null;
        arguments = call.arguments as Map;
        return [
          {
            'status': 'succeeded',
            'operation_id': 'native-op',
            'first_ping': 'no_campus',
            'accuracy_m': 25.0,
            'last_field': 'retained',
          },
        ];
      });
      final gateway = FirstCheckpointGateway(
        accountId: 'owner',
        logger: logger,
      );
      final reports = await gateway.perform('read');
      expect(arguments!['account_id'], 'owner');
      expect(reports.single['last_field'], 'retained');
      final details =
          jsonDecode(
                logger.events
                        .firstWhere((e) => e.$1 == 'first_checkpoint_report')
                        .$2!['details']
                    as String,
              )
              as Map;
      expect(details['operation_id'], 'native-op');
      expect(details['accuracy_m'], 25.0);
      expect(
        FirstCheckpointGateway.rectangles(CampusAreas.defaultArea).length,
        3,
      );
      await FirstCheckpointGateway.deactivate();
      messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        (_) async => null,
      );
      expect(await gateway.perform('read'), isEmpty);
    },
  );
  test('logging failure cannot suppress result or transport failure', () async {
    final logger = CampusTestLogger()..failLogging = true;
    final gateway = FirstCheckpointGateway(accountId: 'owner', logger: logger);
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => [],
    );
    expect(await gateway.perform('read'), isEmpty);
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => throw PlatformException(
        code: 'permission_revoked',
        details: {'stage': 'read'},
      ),
    );
    await expectLater(
      gateway.perform('read'),
      throwsA(isA<PlatformException>()),
    );
    await Future<void>.delayed(Duration.zero);
  });
  testWidgets(
    'schedule eligible session, read result, cancel and resume without attendance mutation',
    (tester) async {
      final repo = Sessions()
        ..values = [
          session('later', start: now.add(const Duration(hours: 1))),
          session('first'),
          session('cancel', status: SessionCalendarStatus.cancelled),
          session('past', start: now.subtract(const Duration(hours: 1))),
          session('manual', attendance: SituacaoFrequencia.present),
        ];
      final logger = CampusTestLogger();
      final selection = Selection();
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        calls.add(call);
        return call.method == 'read'
            ? []
            : [
                {
                  'course_code': 'ELE631',
                  'checkpoint_expected_at_ms': now.millisecondsSinceEpoch,
                  'campus_name': 'Pampulha',
                  'operation_id': 'op',
                  'status': call.method == 'cancel' ? 'cancelled' : 'scheduled',
                },
              ];
      });
      await tester.pumpWidget(
        MaterialApp(
          home: FirstCheckpointPage(
            courses: [course()],
            sessions: repo,
            gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
            selection: selection,
            logger: logger,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Agendar primeiro ping'));
      await tester.pumpAndSettle();
      expect((calls.last.arguments as Map)['session_id'], 'first');
      expect((calls.last.arguments as Map)['campus_id'], 'pampulha');
      await tester.ensureVisible(find.text('Cancelar primeiro ping'));
      await tester.tap(find.text('Cancelar primeiro ping'));
      await tester.pumpAndSettle();
      expect(find.text('Cancelado'), findsOneWidget);
      await tester.ensureVisible(find.text('Limpar resultados encerrados'));
      await tester.tap(find.text('Limpar resultados encerrados'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Atualizar primeiros pings'));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(DropdownButtonFormField<int>));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('ELE631').last);
      await tester.pumpAndSettle();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(repo.values.first.firstPing, isNull);
    },
  );
  testWidgets('all terminal outcomes are visible including malformed success', (
    tester,
  ) async {
    final logger = CampusTestLogger();
    final reports = <Map<String, Object?>>[
      for (final status in [
        'running',
        'cancelled',
        'checkpoint_outside_window',
        'superseded',
        'permission_denied',
      ])
        {'status': status, 'course_code': 'C', 'campus_name': 'Pampulha'},
      for (final value in ['no_campus', 'fora', 'indisponivel'])
        {
          'status': 'succeeded',
          'first_ping': value,
          'accuracy_m': 12.34,
          'lateness_ms': 2000,
          'course_code': 'C',
          'campus_name': 'Pampulha',
        },
    ];
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => reports,
    );
    tester.view.physicalSize = const Size(1200, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          courses: const [],
          sessions: Sessions(),
          gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
          selection: Selection(),
          logger: logger,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Nenhuma sessão elegível para agendar.'), findsOneWidget);
    expect(find.text('Horário perdido — sem evidência válida'), findsOneWidget);
    await tester.drag(find.byType(ListView), const Offset(0, -900));
    await tester.pumpAndSettle();
    expect(find.text('Primeiro ping: fora do campus'), findsOneWidget);
    expect(find.text('Localização indisponível (succeeded)'), findsOneWidget);
  });
  testWidgets('load and prepare failures are recoverable and logged', (
    tester,
  ) async {
    final logger = CampusTestLogger()..failLogging = true;
    final repo = Sessions()..error = StateError('offline');
    final selection = Selection()..fail = true;
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => [],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          courses: [course()],
          sessions: repo,
          gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
          selection: selection,
          logger: logger,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('Não foi possível consultar'), findsOneWidget);
    repo.error = null;
    repo.values = [session('s')];
    await tester.tap(find.byTooltip('Atualizar primeiros pings'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Agendar primeiro ping'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Não foi possível concluir'), findsOneWidget);
    logger.failLogging = false;
    selection.fail = false;
    selection.value = 'direito';
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => throw PlatformException(code: 'denied'),
    );
    await tester.tap(find.text('Agendar primeiro ping'));
    await tester.pumpAndSettle();
    expect(logger.errors, isNotEmpty);
  });
  testWidgets('disposed loading cannot set state on a dead page', (
    tester,
  ) async {
    final pending = Completer<List<SessionRecord>>();
    final repo = Sessions()..pending = pending.future;
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => [],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          courses: [course()],
          sessions: repo,
          gateway: FirstCheckpointGateway(
            accountId: 'owner',
            logger: CampusTestLogger(),
          ),
          selection: Selection(),
          logger: CampusTestLogger(),
        ),
      ),
    );
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpWidget(const MaterialApp(home: SizedBox()));
    pending.complete([]);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}

class CheckpointLogStore implements OperationalLogStore {
  final rows = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async =>
      rows.add(document);
}
