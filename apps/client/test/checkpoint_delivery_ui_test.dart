import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/first_checkpoint.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/features/attendance/first_checkpoint_page.dart';
import 'fixtures/campus_location_fixture.dart';
import 'first_checkpoint_test.dart'
    show Sessions, Selection, course, session, now;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('native delivery broadcasts preserve account and revision', () async {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    const control = MethodChannel(FirstCheckpointGateway.deliveryChannelName);
    messenger.setMockMethodCallHandler(control, (_) async => null);
    addTearDown(() => messenger.setMockMethodCallHandler(control, null));
    final events = <Map<String, Object?>>[];
    final subscription = FirstCheckpointGateway.deliveryUpdates.listen(
      events.add,
    );
    await Future<void>.delayed(Duration.zero);
    await messenger.handlePlatformMessage(
      FirstCheckpointGateway.deliveryChannelName,
      const StandardMethodCodec().encodeSuccessEnvelope({
        'account_id': 'owner',
        'revision': 4,
      }),
      (_) {},
    );
    await Future<void>.delayed(Duration.zero);
    expect(events.single, {'account_id': 'owner', 'revision': 4});
    await subscription.cancel();
  });
  testWidgets('scheduling remains above the Android system navigation bar', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    tester.view.padding = const FakeViewPadding(bottom: 48);
    tester.view.viewPadding = const FakeViewPadding(bottom: 48);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPadding);
    addTearDown(tester.view.resetViewPadding);
    final logger = CampusTestLogger();
    final calls = <String>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
      call,
    ) async {
      calls.add(call.method);
      return [];
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        null,
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          showTestTools: true,
          courses: [course()],
          sessions: Sessions()..values = [session('s')],
          gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
          permissions: CampusTestPermissions(),
          selection: Selection(),
          logger: logger,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.widgetWithText(FilledButton, 'Agendar primeiro ping');
    await tester.scrollUntilVisible(
      button,
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    expect(tester.getRect(button).bottom, lessThanOrEqualTo(796));
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(calls, contains('schedule'));
  });
  testWidgets(
    'production pings diagnostics links to existing permissions and alarm action',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 6000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final permissions = CampusTestPermissions()
        ..flags.addAll({'exact_alarms': false});
      final logger = CampusTestLogger();
      final calls = <String>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        calls.add(call.method);
        return [];
      });
      addTearDown(
        () => messenger.setMockMethodCallHandler(
          FirstCheckpointGateway.channel,
          null,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: FirstCheckpointPage(
            showTestTools: true,
            courses: [],
            sessions: Sessions(),
            gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
            permissions: permissions,
            selection: Selection(),
            logger: logger,
            now: () => now,
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Diagnóstico'), findsOneWidget);
      await tester.tap(find.text('Configuração do Android'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Revisar'));
      await tester.pumpAndSettle();
      expect(calls, contains('request_alarm_permission'));
      await tester.tap(find.text('Revisar permissões'));
      await tester.pumpAndSettle();
      expect(find.text('Permissões'), findsOneWidget);
      await tester.tap(find.byTooltip('Back'));
      await tester.pumpAndSettle();
      expect(find.text('Diagnóstico'), findsOneWidget);
      await tester.tap(find.text('Testar aviso'));
      await tester.pumpAndSettle();
      expect(calls, contains('test_notification'));
      expect(
        find.text('Aviso de teste enviado. Toque nele para abrir os pings.'),
        findsOneWidget,
      );
      messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
        call,
      ) async {
        if (call.method == 'test_notification') {
          throw PlatformException(
            code: 'checkpoint_failed',
            details: {'cause_message': 'notifications_disabled'},
          );
        }
        return [];
      });
      await tester.tap(find.text('Testar aviso'));
      await tester.pumpAndSettle();
      expect(
        find.text(
          'Não foi possível enviar o aviso. Confira a permissão e o canal de notificações.',
        ),
        findsOneWidget,
      );
      expect(
        find.ancestor(
          of: find.text(
            'Aviso não enviado. Revise as notificações do aplicativo.',
          ),
          matching: find.byType(SnackBar),
        ),
        findsOneWidget,
      );
      expect(
        logger.errors.any(
          (e) => e.$2 == 'checkpoint_diagnostic_test_notification',
        ),
        isTrue,
      );
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('local reports remain visible while catalog is offline', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final pending = Completer<List<SessionRecord>>();
    final repo = Sessions()..pending = pending.future;
    final logger = CampusTestLogger();
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(
      FirstCheckpointGateway.channel,
      (_) async => [
        {
          'course_code': 'OFFLINE',
          'operation_id': 'durable',
          'moment': 'first',
          'status': 'succeeded',
          'first_ping': 'fora',
          'delivery_enabled': true,
          'delivery_status': 'pending',
          'checkpoint_expected_at_ms': now.millisecondsSinceEpoch,
        },
      ],
    );
    addTearDown(
      () => messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        null,
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          showTestTools: true,
          courses: [course()],
          sessions: repo,
          gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
          selection: Selection(),
          logger: logger,
          now: () => now,
        ),
      ),
    );
    await tester.pump();
    expect(find.text('Salvo neste aparelho; aguardando envio'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    pending.completeError(StateError('catalog offline'));
    await tester.pumpAndSettle();
    expect(find.text('Salvo neste aparelho; aguardando envio'), findsOneWidget);
    expect(
      find.text('Não foi possível consultar as capturas. Tente atualizar.'),
      findsOneWidget,
    );
    expect(logger.errors, isNotEmpty);
  });
  testWidgets('delivery queue is visible, retryable and fully logged', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 3000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final updates = StreamController<Map<String, Object?>>.broadcast();
    addTearDown(updates.close);
    final logger = CampusTestLogger();
    final repo = Sessions()..values = [session('s')];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final calls = <MethodCall>[];
    String? delivery = 'pending';
    messenger.setMockMethodCallHandler(FirstCheckpointGateway.channel, (
      call,
    ) async {
      calls.add(call);
      return [
        {
          'course_id': 'poo',
          'course_code': 'ELE631',
          'session_id': 's',
          'campus_id': 'pampulha',
          'campus_name': 'Pampulha',
          'operation_id': 'operation',
          'status': 'succeeded',
          'moment': 'first',
          'starts_at_ms': repo.values.single.startsAt.millisecondsSinceEpoch,
          'ends_at_ms': repo.values.single.endsAt.millisecondsSinceEpoch,
          'checkpoint_expected_at_ms': now.millisecondsSinceEpoch,
          'delivery_enabled': true,
          'delivery_status': delivery,
          'delivery_attempt': 3,
          'delivery_timings': {
            'identity_ms': 2,
            'app_check_ms': 30,
            'http_ms': 400,
          },
          'delivery_request_id': 'request-1',
          'delivery_reason': 'classified',
        },
      ];
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(
        FirstCheckpointGateway.channel,
        null,
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: FirstCheckpointPage(
          showTestTools: true,
          courses: [course()],
          deliveryUpdates: updates.stream,
          sessions: repo,
          gateway: FirstCheckpointGateway(accountId: 'owner', logger: logger),
          selection: Selection(),
          logger: logger,
          now: () => now,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Agendar primeiro ping'));
    await tester.pumpAndSettle();
    final fields =
        calls.lastWhere((c) => c.method == 'schedule').arguments as Map;
    expect(fields['delivery_enabled'], isTrue);
    expect(fields['lesson_count'], 2);
    expect(fields['call_count'], 2);
    for (final entry in {
      'pending': 'Salvo neste aparelho; aguardando envio',
      'sending': 'Enviando frequência',
      'retry': 'Salvo neste aparelho; nova tentativa pendente',
      'applied': 'Frequência sincronizada',
      'already_applied': 'Frequência sincronizada',
      'preserved': 'Registro existente mantido',
      'unresolved':
          'Informação insuficiente; registre a frequência manualmente',
      'discarded': 'Disciplina ou sessão removida; nenhum registro criado',
      'rejected': 'Envio não validado; confira os detalhes de diagnóstico',
      'unknown': 'Salvo neste aparelho; aguardando envio',
    }.entries) {
      delivery = entry.key;
      await tester.tap(find.byTooltip('Atualizar capturas'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text(entry.value));
      await tester.pumpAndSettle();
      expect(find.text(entry.value), findsOneWidget);
    }
    delivery = 'retry';
    await tester.tap(find.byTooltip('Atualizar capturas'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Enviar resultados pendentes'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Enviar resultados pendentes'));
    await tester.pumpAndSettle();
    expect(calls.last.method, 'retry_deliveries');
    final event = logger.events.lastWhere(
      (e) => e.$1 == 'first_checkpoint_report',
    );
    final details = jsonDecode(event.$2!['details']! as String) as Map;
    expect(details['delivery_request_id'], 'request-1');
    expect((details['delivery_timings'] as Map)['http_ms'], 400);
    expect(details['delivery_attempt'], 3);
    final beforeEvents = repo.reads;
    updates.add({'account_id': 'other', 'revision': 1});
    updates.add({'account_id': 'owner', 'revision': 'bad'});
    updates.add({'account_id': 'owner', 'revision': 0});
    await tester.pumpAndSettle();
    expect(repo.reads, beforeEvents);
    updates.add({'account_id': 'owner', 'revision': 1});
    await tester.pumpAndSettle();
    expect(repo.reads, beforeEvents + 1);
    updates.add({'account_id': 'owner', 'revision': 1});
    await tester.pumpAndSettle();
    expect(repo.reads, beforeEvents + 1);
    updates.addError(StateError('native stream unavailable'));
    await tester.pumpAndSettle();
    expect(
      logger.errors.any((e) => e.$2 == 'checkpoint_delivery_updates'),
      isTrue,
    );
    logger.failLogging = true;
    updates.addError(StateError('stream and logger unavailable'));
    await tester.pumpAndSettle();
    logger.failLogging = false;
    final waiting = Completer<List<SessionRecord>>();
    repo.pending = waiting.future;
    await tester.tap(find.byTooltip('Atualizar capturas'));
    await tester.pump();
    updates.add({'account_id': 'owner', 'revision': 2});
    await tester.pump();
    repo.pending = null;
    waiting.complete(repo.values);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
