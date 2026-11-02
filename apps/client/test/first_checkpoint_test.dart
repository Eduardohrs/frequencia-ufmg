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
  int reads = 0;
  @override
  Future<List<SessionRecord>> listSessions(String id) async {
    reads++;
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
                    'test/fixtures/checkpoint_delivery_report.json',
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
            'delivery_enabled': true,
            'delivery_status': 'retry',
            'delivery_attempt': 8,
            'delivery_request_id': 'upload-operation',
            'delivery_http_status': 503,
            'delivery_stage': 'http',
            'delivery_timings': {
              'identity_ms': 3,
              'app_check_ms': 250,
              'http_ms': 25000,
              'failure': {
                'cause_type': 'ExecutionException',
                'root_cause_type': 'SocketTimeoutException',
                'root_cause_message': List.filled(
                  20,
                  'upstream response timeout c/s; ',
                ).join(),
              },
            },
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
      expect(persisted['fields_omitted'], isNull);
      expect(persisted['first_ping'], 'no_campus');
      expect(persisted['foreground_service_active'], isTrue);
      expect(persisted['accuracy_m'], report['accuracy_m']);
      expect(persisted['operation_id'], report['operation_id']);
      expect(persisted['delivery_request_id'], 'upload-operation');
      expect(persisted['delivery_http_status'], 503);
      expect(persisted['delivery_attempt'], 8);
      expect(
        ((persisted['delivery_timings'] as Map)['failure']
            as Map)['root_cause_message'],
        ((report['delivery_timings'] as Map)['failure']
            as Map)['root_cause_message'],
      );
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
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancelar primeiro ping'));
      await tester.pumpAndSettle();
      expect(find.text('Cancelado'), findsOneWidget);
      await tester.ensureVisible(find.text('Limpar resultados encerrados'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Limpar resultados encerrados'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Atualizar pings'));
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
    await tester.tap(find.byTooltip('Atualizar pings'));
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
  testWidgets(
    'alarm access action and permission failure are explicit and logged',
    (tester) async {
      final logger = CampusTestLogger();
      final actions = <String>[];
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        actions.add(call.method);
        if (call.method == 'schedule') {
          throw PlatformException(
            code: 'checkpoint_failed',
            details: {'cause_message': 'exact_alarm_permission_required'},
          );
        }
        return [];
      });
      await tester.pumpWidget(
        MaterialApp(
          home: FirstCheckpointPage(
            courses: [course()],
            sessions: Sessions()..values = [session('s')],
            gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
            selection: Selection(),
            logger: logger,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Revisar Alarmes e lembretes'));
      await tester.pumpAndSettle();
      expect(actions, contains('request_alarm_permission'));
      await tester.tap(find.text('Agendar primeiro ping'));
      await tester.pumpAndSettle();
      expect(
        find.text('Permita Alarmes e lembretes para agendar os pings.'),
        findsOneWidget,
      );
      expect(logger.errors, isNotEmpty);
      messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        (_) async => [
          {
            'status': 'exact_alarm_permission_required',
            'course_code': 'C',
            'campus_name': 'Pampulha',
          },
          {
            'status': 'scheduled',
            'course_code': 'D',
            'campus_name': 'Pampulha',
          },
        ],
      );
      await tester.tap(find.byTooltip('Atualizar pings'));
      await tester.pumpAndSettle();
      expect(find.text('Alarmes e lembretes não autorizado'), findsOneWidget);
      await tester.drag(find.byType(ListView), const Offset(0, -600));
      await tester.pumpAndSettle();
      expect(find.text('Agendado para o horário da aula'), findsOneWidget);
    },
  );
  testWidgets(
    'second moment and paired local results are visible and fully logged without writes',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 2600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final logger = CampusTestLogger();
      final repo = Sessions()..values = [session('s')];
      final one = repo.values.single;
      Map<String, Object?> evidence(String moment, String ping) {
        final expected =
            (moment == 'first'
                    ? one.startsAt.add(const Duration(minutes: 20))
                    : one.endsAt.subtract(const Duration(minutes: 20)))
                .millisecondsSinceEpoch;
        return {
          'course_id': 'poo',
          'course_code': 'ELE631',
          'session_id': 's',
          'campus_id': 'pampulha',
          'campus_name': 'Pampulha',
          'starts_at_ms': one.startsAt.millisecondsSinceEpoch,
          'ends_at_ms': one.endsAt.millisecondsSinceEpoch,
          'operation_id': moment,
          'moment': moment,
          'scheduled_at_ms': now.millisecondsSinceEpoch,
          'checkpoint_expected_at_ms': expected,
          'captured_at_ms': expected + 1000,
          'status': 'succeeded',
          (moment == 'first' ? 'first_ping' : 'second_ping'): ping,
        };
      }

      var reports = <Map<String, Object?>>[];
      final calls = <MethodCall>[];
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        calls.add(call);
        return reports;
      });
      await tester.pumpWidget(
        MaterialApp(
          home: FirstCheckpointPage(
            courses: [course()],
            sessions: repo,
            gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
            selection: Selection(),
            logger: logger,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      final readsBeforeSelection = repo.reads;
      await tester.tap(find.text('Fim da aula'));
      await tester.pumpAndSettle();
      expect(repo.reads, readsBeforeSelection);
      await tester.tap(find.text('Agendar segundo ping'));
      await tester.pumpAndSettle();
      expect((calls.last.arguments as Map)['moment'], 'second');
      for (final item in [
        ('no_campus', 'no_campus', 'Presente'),
        ('fora', 'fora', 'Ausente'),
        ('fora', 'no_campus', 'Chegou atrasado'),
        ('no_campus', 'fora', 'Saiu mais cedo'),
        ('indisponivel', 'indisponivel', 'Pendente'),
      ]) {
        reports = [
          evidence('first', item.$1),
          evidence('second', item.$2),
          {'course_id': 'missing'},
          {...evidence('first', item.$1), 'campus_id': null},
          {...evidence('first', item.$1), 'starts_at_ms': 0},
          {...evidence('first', item.$1), 'ends_at_ms': 0},
        ];
        await tester.tap(find.byTooltip('Atualizar pings'));
        await tester.pumpAndSettle();
        expect(find.text(item.$3), findsOneWidget);
        expect(find.text('ELE631 · Resultado local'), findsOneWidget);
      }
      final row = logger.events.lastWhere(
        (e) => e.$1 == 'attendance_checkpoint_classified',
      );
      final details = jsonDecode(row.$2!['details']! as String) as Map;
      expect(details['call_count'], 2);
      expect(details['lesson_count'], 2);
      expect(details['first_operation_id'], 'first');
      expect(details['second_operation_id'], 'second');
      expect(details['attendance_status'], 'pendente');
      expect(details['complete'], true);
      reports = [
        {...evidence('first', 'fora'), 'status': 'scheduled'},
        {...evidence('second', 'fora'), 'status': 'scheduled'},
      ];
      await tester.tap(find.byTooltip('Atualizar pings'));
      await tester.pumpAndSettle();
      expect(find.text('Aguardando os dois resultados'), findsOneWidget);
      await tester.tap(find.text('Cancelar segundo ping'));
      await tester.pumpAndSettle();
      expect((calls.last.arguments as Map)['operation_id'], 'second');
      repo.values = [session('s', attendance: SituacaoFrequencia.present)];
      logger.failLogging = true;
      await tester.tap(find.byTooltip('Atualizar pings'));
      await tester.pumpAndSettle();
      expect(find.text('Registro da disciplina preservado'), findsOneWidget);
      await tester.tap(find.text('Início da aula'));
      await tester.pumpAndSettle();
      expect(repo.values.single.attendanceStatus, SituacaoFrequencia.present);
      expect(tester.takeException(), isNull);
    },
  );
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
