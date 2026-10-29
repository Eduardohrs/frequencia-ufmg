import 'dart:async';
import 'dart:convert';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/features/attendance/background_proof_panel.dart';
import 'fixtures/campus_location_fixture.dart';

void main() {
  const channel = MethodChannel(
    'br.ufmg.frequencia.frequencia_ufmg/background_proof',
  );
  testWidgets(
    'schedules explicit diagnostic then reads result without recording attendance',
    (tester) async {
      final calls = <String>[];
      final logger = CampusTestLogger();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            calls.add(call.method);
            return {
              'status': call.method == 'schedule' ? 'scheduled' : 'succeeded',
              'operation_id': 'proof-test',
              'background_proven': call.method == 'read',
              'screen_locked_capture': true,
              'accuracy_m': 12.0,
            };
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: BackgroundProofPanel(logger: logger)),
        ),
      );
      await tester.pumpAndSettle();
      expect(calls, isEmpty);
      await tester.tap(find.text('Agendar teste'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Agendado'), findsOneWidget);
      await tester.tap(find.text('Consultar resultado'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Captura em segundo plano confirmada'),
        findsOneWidget,
      );
      expect(calls, ['schedule', 'read']);
      expect(
        jsonDecode(logger.events.last.$2!['details'] as String)['accuracy_m'],
        12.0,
      );
      expect(logger.events.last.$2!['operation_id'], 'proof-test');
    },
  );
  testWidgets('empty report and provider errors remain diagnosable', (
    tester,
  ) async {
    final logger = CampusTestLogger();
    var fail = false;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (_) async {
          if (fail) {
            throw PlatformException(
              code: 'background_proof_failed',
              details: {'stage': 'read'},
            );
          }
          return <String, Object>{};
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: BackgroundProofPanel(logger: logger)),
      ),
    );
    await tester.tap(find.text('Consultar resultado'));
    await tester.pumpAndSettle();
    expect(find.text('Nenhum teste agendado.'), findsOneWidget);
    fail = true;
    await tester.tap(find.text('Agendar teste'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Não foi possível consultar ou agendar'),
      findsOneWidget,
    );
    expect(logger.errors.single.$2, 'background_proof_schedule');
    expect(
      logger.errors.single.$3!['operation_id'],
      endsWith('-backgroundProof'),
    );
  });
  for (final status in ['running', 'succeeded', 'location_timeout']) {
    testWidgets(
      'explains $status without claiming unproven background capture',
      (tester) async {
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              channel,
              (_) async => {'status': status, 'background_proven': false},
            );
        addTearDown(
          () => TestDefaultBinaryMessengerBinding
              .instance
              .defaultBinaryMessenger
              .setMockMethodCallHandler(channel, null),
        );
        final logger = CampusTestLogger()..failLogging = true;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(body: BackgroundProofPanel(logger: logger)),
          ),
        );
        await tester.tap(find.text('Consultar resultado'));
        await tester.pumpAndSettle();
        expect(
          find.textContaining(switch (status) {
            'running' => 'O Android iniciou',
            'succeeded' => 'Isso ainda não comprova',
            _ => 'Teste não confirmado: location_timeout',
          }),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
      },
    );
  }
  testWidgets(
    'logging outage does not break recovery and late replies do not set disposed state',
    (tester) async {
      final logger = CampusTestLogger()..failLogging = true;
      var pending = Completer<Object?>();
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (_) => pending.future);
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      Future<void> show() => tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: BackgroundProofPanel(logger: logger)),
        ),
      );
      await show();
      await tester.tap(find.text('Consultar resultado'));
      await tester.pump();
      await tester.pumpWidget(const SizedBox());
      pending.complete(null);
      await tester.pumpAndSettle();
      pending = Completer<Object?>();
      await show();
      await tester.tap(find.text('Consultar resultado'));
      await tester.pumpWidget(const SizedBox());
      pending.completeError(PlatformException(code: 'provider_error'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'serialized production telemetry retains timing, permission, lock state and job identity',
    (tester) async {
      final store = ProofLogStore();
      final logger = FirestoreAppLogger(
        store: store,
        currentUserId: () => 'owner',
        platform: 'android',
      );
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(
            channel,
            (_) async => {
              'operation_id': 'proof-serialized',
              'status': 'location_timeout',
              'stage': 'location_fix',
              'background_permission': true,
              'screen_locked_start': true,
              'duration_ms': 45000,
              'provider': 'gps',
              'queue_wait_ms': 123000,
            },
          );
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: BackgroundProofPanel(logger: logger)),
        ),
      );
      await tester.tap(find.text('Consultar resultado'));
      await tester.pumpAndSettle();
      final row = store.rows.last;
      expect(store.rows.first['event'], 'background_proof_action_started');
      final details = jsonDecode(row['details'] as String) as Map;
      expect(details['stage'], 'location_fix');
      expect(details['background_permission'], true);
      expect(details['screen_locked_start'], true);
      expect(details['duration_ms'], 45000);
      expect(details['queue_wait_ms'], 123000);
      expect(details['provider'], 'gps');
      expect(row['correlationId'], 'proof-serialized');
    },
  );
}

class ProofLogStore implements OperationalLogStore {
  final rows = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async =>
      rows.add(document);
}
