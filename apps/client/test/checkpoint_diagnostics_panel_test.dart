import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/features/attendance/checkpoint_diagnostics_panel.dart';
import 'fixtures/campus_location_fixture.dart';

class Permissions extends CampusTestPermissions {
  Future<AttendancePermissionStatus>? pending;
  @override
  Future<AttendancePermissionStatus> read() => pending ?? super.read();
}

final now = DateTime.utc(2026, 11, 2, 12);
void main() {
  testWidgets(
    'diagnostic shows local queue, settings, recoveries and bounded failure evidence at phone and desktop widths',
    (tester) async {
      for (final width in [390.0, 1200.0]) {
        tester.view.physicalSize = Size(width, 4000);
        tester.view.devicePixelRatio = 1;
        final permissions = Permissions()
          ..flags.addAll({'battery_unrestricted': true, 'exact_alarms': true});
        final logger = CampusTestLogger();
        int alarms = 0, reviews = 0;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: CheckpointDiagnosticsPanel(
                  key: ValueKey(width),
                  permissions: permissions,
                  logger: logger,
                  now: () => now,
                  reports: [
                    {
                      'status': 'scheduled',
                      'course_code': 'POO',
                      'checkpoint_expected_at_ms': now
                          .add(const Duration(hours: 1))
                          .millisecondsSinceEpoch,
                    },
                    {
                      'status': 'succeeded',
                      'course_code': 'POO',
                      'delivery_enabled': true,
                      'delivery_status': 'retry',
                      'delivery_request_id': 'request-id',
                      'delivery_stage': 'http',
                      'delivery_timings': {
                        'http_ms': 25000,
                        'failure': {
                          'root_cause_type': 'SocketTimeoutException',
                          'token': 'hidden',
                        },
                      },
                    },
                  ],
                  onReviewPermissions: () async {
                    reviews++;
                  },
                  onReviewAlarms: () async {
                    alarms++;
                  },
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('Configuração pronta para os pings'), findsOneWidget);
        expect(find.text('1 resultado(s) aguardando envio'), findsOneWidget);
        expect(find.text('Próximo ping'), findsOneWidget);
        await tester.tap(find.text('Configuração do Android'));
        await tester.pumpAndSettle();
        for (final text in [
          'Permitida sempre',
          'Sem restrições',
          'Permitidas',
          'Permitidos',
          'Desligada',
        ]) {
          expect(find.text(text), findsOneWidget);
        }
        await tester.ensureVisible(find.text('Revisar'));
        await tester.tap(find.text('Revisar'));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Revisar permissões'));
        await tester.tap(find.text('Revisar permissões'));
        await tester.pumpAndSettle();
        expect(alarms, 1);
        expect(reviews, 1);
        await tester.ensureVisible(find.text('Último problema registrado'));
        await tester.tap(find.text('Último problema registrado'));
        await tester.pumpAndSettle();
        final details = tester
            .widget<SelectableText>(find.byType(SelectableText))
            .data!;
        expect(details, contains('request-id'));
        expect(details, contains('SocketTimeoutException'));
        expect(details, isNot(contains('hidden')));
        expect(
          logger.events.any((e) => e.$1 == 'checkpoint_diagnostic_snapshot'),
          isTrue,
        );
        final snapshot = logger.events.lastWhere(
          (e) => e.$1 == 'checkpoint_diagnostic_snapshot',
        );
        final correlation = snapshot.$2!['operation_id'];
        expect(
          logger.events.any(
            (e) =>
                e.$1 == 'checkpoint_diagnostic_started' &&
                e.$2!['operation_id'] == correlation,
          ),
          isTrue,
        );
        expect(
          jsonDecode(snapshot.$2!['details'] as String)['duration_ms'],
          isNonNegative,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      }
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    },
  );
  testWidgets(
    'permission conditions are distinct and results update without a network subscription',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final permissions = Permissions();
      final logger = CampusTestLogger();
      List<Map<String, Object?>> reports = [];
      Future<void> render() async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: CheckpointDiagnosticsPanel(
                  permissions: permissions,
                  reports: reports,
                  logger: logger,
                  now: () => now,
                  onReviewPermissions: () async {},
                  onReviewAlarms: () async {},
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
      }

      await render();
      expect(find.text('Nenhum ping agendado'), findsOneWidget);
      expect(find.text('Nenhum problema registrado'), findsOneWidget);
      await tester.tap(find.text('Configuração do Android'));
      await tester.pumpAndSettle();
      expect(find.text('Não verificado nesta versão'), findsOneWidget);
      expect(find.text('Otimizada ou restrita'), findsOneWidget);
      for (final entry in {
        'location_services': 'Localização desligada',
        'foreground_location': 'Sem acesso à localização',
        'precise_location': 'Localização aproximada',
        'background_location': 'Somente durante o uso',
      }.entries) {
        permissions.flags[entry.key] = false;
        await tester.tap(find.byTooltip('Atualizar diagnóstico'));
        await tester.pumpAndSettle();
        expect(find.text(entry.value), findsOneWidget);
        permissions.flags[entry.key] = true;
      }
      permissions.flags.addAll({
        'exact_alarms': false,
        'power_save_mode': true,
        'notifications': false,
      });
      await tester.tap(find.byTooltip('Atualizar diagnóstico'));
      await tester.pumpAndSettle();
      for (final text in [
        'Não permitidos',
        'Ligada',
        'Desativadas — os avisos podem não aparecer',
      ]) {
        expect(find.text(text), findsOneWidget);
      }
      reports = [
        {
          'status': 'scheduled',
          'checkpoint_expected_at_ms': now
              .subtract(const Duration(minutes: 1))
              .millisecondsSinceEpoch,
        },
        {'status': 'location_timeout'},
      ];
      await render();
      expect(find.text('Aguardando execução'), findsOneWidget);
      expect(find.text('Disciplina • Captura não concluída'), findsOneWidget);
      reports = [
        {
          'status': 'running',
          'checkpoint_expected_at_ms': now.millisecondsSinceEpoch,
        },
        {'status': 'succeeded', 'delivery_status': 'unresolved'},
      ];
      await render();
      expect(find.text('Captura em andamento'), findsOneWidget);
      expect(find.text('Disciplina • Evidência insuficiente'), findsOneWidget);
      expect(
        logger.events.any((e) => e.$1 == 'checkpoint_diagnostic_reports'),
        isTrue,
      );
      expect(
        jsonDecode(
          logger.events
                  .lastWhere((e) => e.$1 == 'checkpoint_diagnostic_reports')
                  .$2!['details']
              as String,
        )['pending_uploads'],
        0,
      );
    },
  );
  testWidgets(
    'failed reads and actions are diagnosable without losing local data even if logger fails',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 4000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final permissions = Permissions()
        ..error = StateError('snapshot unavailable');
      final logger = CampusTestLogger();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CheckpointDiagnosticsPanel(
              permissions: permissions,
              reports: [
                {'status': 'succeeded', 'delivery_enabled': true},
              ],
              logger: logger,
              now: () => now,
              onReviewPermissions: () async =>
                  throw StateError('settings failed'),
              onReviewAlarms: () async {},
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Não foi possível verificar o Android'), findsOneWidget);
      expect(find.text('1 resultado(s) aguardando envio'), findsOneWidget);
      expect(logger.errors.single.$2, 'checkpoint_diagnostic_permissions');
      await tester.tap(find.text('Revisar permissões'));
      await tester.pumpAndSettle();
      expect(logger.errors.last.$2, 'checkpoint_diagnostic_permissions');
      logger.failLogging = true;
      await tester.tap(find.byTooltip('Atualizar diagnóstico'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Revisar permissões'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      permissions.error = null;
      await tester.tap(find.byTooltip('Atualizar diagnóstico'));
      await tester.pumpAndSettle();
      expect(find.text('Revisar configuração do Android'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'a lost platform reply times out without hiding the local queue',
    (tester) async {
      final permissions = Permissions()
        ..pending = Completer<AttendancePermissionStatus>().future;
      final logger = CampusTestLogger();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CheckpointDiagnosticsPanel(
              permissions: permissions,
              reports: [
                {'status': 'succeeded', 'delivery_enabled': true},
              ],
              logger: logger,
              now: () => now,
              onReviewPermissions: () async {},
              onReviewAlarms: () async {},
            ),
          ),
        ),
      );
      await tester.pump(const Duration(seconds: 11));
      await tester.pumpAndSettle();
      expect(find.text('Não foi possível verificar o Android'), findsOneWidget);
      expect(find.text('1 resultado(s) aguardando envio'), findsOneWidget);
      expect(logger.errors.single.$1, isA<TimeoutException>());
      final start = logger.events.singleWhere(
        (e) => e.$1 == 'checkpoint_diagnostic_started',
      );
      expect(
        logger.errors.single.$3!['operation_id'],
        start.$2!['operation_id'],
      );
    },
  );
  testWidgets('lifecycle ignores stale snapshots and disposed reads', (
    tester,
  ) async {
    final first = Completer<AttendancePermissionStatus>();
    final second = Completer<AttendancePermissionStatus>();
    final permissions = Permissions()..pending = first.future;
    final logger = CampusTestLogger();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CheckpointDiagnosticsPanel(
            permissions: permissions,
            reports: [],
            logger: logger,
            now: () => now,
            onReviewPermissions: () async {},
            onReviewAlarms: () async {},
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('Verificando configuração…'), findsOneWidget);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    permissions.pending = second.future;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    first.completeError(StateError('stale'));
    await tester.pump();
    expect(find.text('Não foi possível verificar o Android'), findsNothing);
    permissions.pending = null;
    second.complete(await permissions.read());
    await tester.pumpAndSettle();
    final third = Completer<AttendancePermissionStatus>();
    permissions.pending = third.future;
    await tester.tap(find.byTooltip('Atualizar diagnóstico'));
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    third.completeError(StateError('disposed'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final fourth = Completer<AttendancePermissionStatus>();
    permissions.pending = fourth.future;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: CheckpointDiagnosticsPanel(
            permissions: permissions,
            reports: [],
            logger: logger,
            now: () => now,
            onReviewPermissions: () async {},
            onReviewAlarms: () async {},
          ),
        ),
      ),
    );
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    permissions.pending = null;
    fourth.complete(await permissions.read());
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
