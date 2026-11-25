import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/academic_sync_progress.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/features/ufmg/academic_sync_controller.dart';
import 'package:frequencia_ufmg/features/ufmg/academic_sync_banner.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'fixtures/academic_sync_fixture.dart';

void main() {
  test(
    'a reopened app reconnects to the existing job instead of inventing a new operation',
    () async {
      final gateway = _ResumableGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      final restoring = controller.restore();
      await Future<void>.delayed(Duration.zero);
      expect(gateway.restoreOperationId, 'sync-existing123');
      // Restore is GET-only: it must never call syncWithProgress (no new POST).
      expect(gateway.calls, 0);
      expect(controller.isRunning, isTrue);
      gateway.restoreResponse.complete(syncResult());
      await restoring;
      expect(controller.title, 'Sincronização concluída');
      controller.dispose();
      await gateway.updates.close();
    },
  );
  test('missing or unavailable recovery does not start another job', () async {
    for (final failing in [false, true]) {
      final gateway = _ResumableGateway()
        ..missing = true
        ..failing = failing;
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      await controller.restore();
      expect(gateway.calls, 0);
      controller.dispose();
      await gateway.updates.close();
    }
  });

  test(
    'validates progress documents without inventing time-based percentages',
    () {
      const valid = {
        'operationId': 'sync-test123',
        'status': 'running',
        'completed': 1,
        'reviewRequired': 0,
      };
      expect(AcademicSyncProgress.fromMap(valid).completed, 1);
      for (final change in <Map<String, Object?>>[
        {'operationId': 1},
        {'operationId': 'x'},
        {'completed': -1},
        {'completed': 4},
        {'completed': '1'},
        {'status': 'unknown'},
        {'status': 'succeeded'},
        {'reviewRequired': null},
        {'reviewRequired': -1},
        {'reviewRequired': 51},
      ]) {
        expect(
          () => AcademicSyncProgress.fromMap({...valid, ...change}),
          throwsFormatException,
        );
      }
    },
  );

  test(
    'coalesces starts, accepts only matching monotonic progress and retains result',
    () async {
      final gateway = ProgressGateway();
      final logger = _Logger();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
        idGenerator: () => 'sync-test123',
      );
      final first = controller.start();
      expect(controller.title, 'Iniciando sincronização…');
      expect(identical(first, controller.start()), isTrue);
      controller.dismiss();
      expect(controller.visible, isTrue);
      await Future<void>.delayed(Duration.zero);
      expect(gateway.calls, 1);
      for (var completed = 0; completed <= 3; completed++) {
        gateway.updates.add(
          AcademicSyncProgress(
            operationId: 'sync-test123',
            completed: completed,
            status: 'running',
          ),
        );
        expect(
          controller.title,
          completed < 3
              ? AcademicSyncController.stages[completed]
              : 'Finalizando sincronização…',
        );
      }
      gateway.updates.add(
        const AcademicSyncProgress(
          operationId: 'another-id',
          completed: 0,
          status: 'running',
        ),
      );
      gateway.updates.add(
        const AcademicSyncProgress(
          operationId: 'sync-test123',
          completed: 1,
          status: 'running',
        ),
      );
      expect(controller.progress!.completed, 3);
      gateway.response.complete(syncResult(partial: true));
      await first;
      expect(controller.title, 'Confira as pendências da sincronização');
      expect(controller.result!.exceptions.single.courseCode, 'ESA019');
      controller.dismiss();
      expect(controller.visible, isFalse);
      expect(logger.events, contains('academic_sync_succeeded'));
      controller.dispose();
      await gateway.updates.close();
    },
  );

  test(
    'progress delivery errors never stop the sync, including synchronous listener failure',
    () async {
      for (final throwsOnWatch in [false, true]) {
        final gateway = ProgressGateway()..throwsOnWatch = throwsOnWatch;
        final logger = _Logger()..failRecording = true;
        final controller = AcademicSyncController(
          gateway: gateway,
          logger: logger,
        );
        final future = controller.start();
        await Future<void>.delayed(Duration.zero);
        if (!throwsOnWatch) {
          gateway.updates.addError(StateError('offline'), StackTrace.current);
        }
        expect(controller.title, 'Sincronizando • progresso indisponível');
        expect(gateway.operationId, startsWith('sync-'));
        gateway.response.complete(syncResult());
        await future;
        expect(controller.title, 'Sincronização concluída');
        expect(
          logger.errors,
          contains(
            throwsOnWatch
                ? 'academic_sync_progress_subscribe'
                : 'academic_sync_progress_listen',
          ),
        );
        controller.dispose();
        await gateway.updates.close();
      }
    },
  );

  test(
    'failure terminates and owner disposal does not notify a dead screen',
    () async {
      final gateway = ProgressGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      final future = controller.start();
      await Future<void>.delayed(Duration.zero);
      final expectation = expectLater(future, throwsStateError);
      gateway.response.completeError(StateError('upstream unavailable'));
      await expectation;
      expect(controller.isRunning, isFalse);
      expect(controller.title, contains('Não foi possível'));
      controller.dispose();
      await gateway.updates.close();

      final running = ProgressGateway();
      final owner = AcademicSyncController(gateway: running, logger: _Logger());
      final pending = owner.start();
      owner.dispose();
      running.response.complete(syncResult());
      await pending;
      await running.updates.close();
    },
  );

  test(
    'slow or failed listener cleanup never holds the completed operation',
    () async {
      final gateway = _CancelGateway();
      final logger = _Logger();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
      );
      final future = controller.start();
      gateway.response.complete(syncResult());
      await future;
      expect(controller.isRunning, isFalse);
      expect(controller.title, 'Sincronização concluída');
      gateway.cancel.completeError(StateError('cleanup failed'));
      await Future<void>.delayed(Duration.zero);
      expect(logger.errors, contains('academic_sync_progress_cancel'));
      logger.failEvents = true;
      controller.logInteraction('log unavailable');
      await Future<void>.delayed(Duration.zero);
      controller.dispose();
      await gateway.source.close();
      await gateway.updates.close();
    },
  );

  test(
    'received stages survive persisted logging with correlation and bounded duplicates',
    () async {
      final store = _LogStore();
      final gateway = ProgressGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: FirestoreAppLogger(
          store: store,
          currentUserId: () => 'user-1',
          platform: 'web',
        ),
        idGenerator: () => 'sync-test123',
      );
      final pending = controller.start();
      const stage = AcademicSyncProgress(
        operationId: 'sync-test123',
        completed: 1,
        status: 'running',
      );
      gateway.updates.add(stage);
      gateway.updates.add(stage);
      gateway.response.complete(syncResult());
      await pending;
      final received = store.documents.where(
        (value) => value['event'] == 'academic_sync_progress_received',
      );
      expect(received, hasLength(1));
      expect(received.single['correlationId'], 'sync-test123');
      expect(received.single['action'], '1/3:running');
      expect(received.single['operation'], 'academic_sync');
      controller.dispose();
      await gateway.updates.close();
    },
  );

  testWidgets(
    'failed background operation shows retained stages and a recovery message',
    (tester) async {
      final gateway = ProgressGateway();
      var openedConnection = false;
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AcademicSyncBanner(
              controller: controller,
              onReview: () => openedConnection = true,
            ),
          ),
        ),
      );
      final pending = expectLater(controller.start(), throwsStateError);
      await tester.pump();
      gateway.response.completeError(StateError('upstream unavailable'));
      await tester.pumpAndSettle();
      await pending;
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('As etapas já concluídas foram mantidas'),
        findsNothing,
      );
      await tester.tap(find.text('Abrir conexão'));
      await tester.pumpAndSettle();
      expect(openedConnection, isTrue);
      controller.dispose();
      await gateway.updates.close();
    },
  );

  testWidgets(
    'discreet indicator reveals real stages and result without locking navigation',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final gateway = ProgressGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      var reviewed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AcademicSyncBanner(
              controller: controller,
              onReview: () => reviewed = true,
            ),
          ),
        ),
      );
      expect(find.byKey(const Key('academic-sync-indicator')), findsNothing);
      final future = controller.start();
      await tester.pump();
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      expect(find.text('0 de 3 etapas concluídas'), findsOneWidget);
      gateway.updates.add(
        AcademicSyncProgress(
          operationId: gateway.operationId!,
          completed: 1,
          status: 'running',
        ),
      );
      await tester.pump();
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byType(LinearProgressIndicator),
            )
            .value,
        closeTo(1 / 3, .001),
      );
      gateway.updates.addError(
        StateError('progress unavailable'),
        StackTrace.current,
      );
      await tester.pump();
      expect(
        tester
            .widget<LinearProgressIndicator>(
              find.byType(LinearProgressIndicator),
            )
            .value,
        isNull,
      );
      gateway.response.complete(syncResult(partial: true));
      await tester.pumpAndSettle();
      await future;
      // P2-15: o sheet fecha sozinho quando a sincronização termina com ele
      // aberto (antes ficava preso em "3 de 3 etapas concluídas").
      expect(find.text('0 de 3 etapas concluídas'), findsNothing);
      expect(find.text('Ver resultado'), findsNothing);
      expect(controller.visible, isTrue);
      // O banner continua disponível e reabre o sheet já com o resultado.
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      expect(find.text('3 de 3 etapas concluídas'), findsOneWidget);
      await tester.tap(find.text('Ver resultado'));
      await tester.pumpAndSettle();
      expect(reviewed, isTrue);
      await tester.pump();
      expect(find.byKey(const Key('academic-sync-indicator')), findsOneWidget);
      expect(tester.takeException(), isNull);
      controller.dispose();
      await gateway.updates.close();
    },
  );

  testWidgets(
    'sheet opened after completion stays open and offers the result',
    (tester) async {
      final gateway = ProgressGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      var reviewed = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: AcademicSyncBanner(
              controller: controller,
              onReview: () => reviewed = true,
            ),
          ),
        ),
      );
      final future = controller.start();
      await tester.pump();
      gateway.response.complete(syncResult(partial: true));
      await tester.pumpAndSettle();
      await future;
      // Sheet aberto depois da conclusão: não deve fechar sozinho.
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      expect(find.text('3 de 3 etapas concluídas'), findsOneWidget);
      expect(find.text('Ver resultado'), findsOneWidget);
      await tester.tap(find.text('Ver resultado'));
      await tester.pumpAndSettle();
      expect(reviewed, isTrue);
      expect(tester.takeException(), isNull);
      controller.dispose();
      await gateway.updates.close();
    },
  );

  test(
    'disposing mid-run and reopening restores the saved job without a second POST',
    () async {
      final gateway = _ResumableGateway();
      final logger = _Logger();
      final first = AcademicSyncController(
        gateway: gateway,
        logger: logger,
        idGenerator: () => 'sync-first123',
      );
      final pending = first.start();
      await Future<void>.delayed(Duration.zero);
      expect(gateway.calls, 1);
      first.dispose(); // screen recreated while the job runs
      gateway.response.complete(syncResult());
      await pending;
      // A brand-new controller (new screen) re-finds the saved job GET-only.
      final reopened = AcademicSyncController(gateway: gateway, logger: logger);
      final restoring = reopened.restore();
      await Future<void>.delayed(Duration.zero);
      expect(gateway.restoreCalls, 1);
      expect(gateway.restoreOperationId, 'sync-existing123');
      expect(gateway.calls, 1); // still exactly one syncWithProgress (one POST)
      gateway.restoreResponse.complete(syncResult());
      await restoring;
      // No spinner without state: the reopened controller reaches a terminal title.
      expect(reopened.isRunning, isFalse);
      expect(reopened.error, isNull);
      expect(reopened.title, 'Sincronização concluída');
      reopened.dispose();
      await gateway.updates.close();
    },
  );

  test(
    'a job finishing after the last poll becomes a recoverable server-side state and retry finds the result',
    () async {
      final gateway = _ResumableGateway();
      final logger = _Logger();
      final deadline = Completer<PythonUnifiedAcademicSyncResult>();
      gateway.restoreResults.add(deadline.future);
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
      );
      final restoring = controller.restore();
      await Future<void>.delayed(Duration.zero);
      gateway.updates.add(
        const AcademicSyncProgress(
          operationId: 'sync-existing123',
          completed: 1,
          status: 'running',
        ),
      );
      gateway.emitPoll(1, 'running');
      gateway.emitPoll(90, 'running');
      deadline.completeError(
        const PythonBackendException(
          PythonBackendError.jobUnobserved,
          requestContext:
              'stage=job_wait operation_id=sync-existing123 '
              'reason=observation_expired server_job_not_cancelled=true '
              'attempts=90 elapsed_ms=1800000',
        ),
      );
      await restoring;
      expect(controller.observationLost, isTrue);
      expect(controller.visible, isTrue);
      expect(controller.error, isNull);
      expect(controller.isRunning, isFalse);
      expect(controller.title, contains('Processando no servidor'));
      expect(controller.title, contains('Datas e materiais'));
      expect(controller.lastStage, 'Datas e materiais');
      final deadlineEvent =
          logger.eventParameters['academic_sync_observation_deadline']!;
      expect(deadlineEvent['code'], 'jobUnobserved');
      expect(deadlineEvent['attempts'], 90);
      expect(deadlineEvent['elapsed_ms'], isA<int>());
      expect(deadlineEvent['operation_id'], 'sync-existing123');
      // Structured events never carry credentials or headers.
      for (final parameters in logger.eventParameters.values) {
        final serialized = parameters.toString();
        expect(serialized, isNot(contains('Bearer')));
        expect(serialized, isNot(contains('token')));
        expect(serialized, isNot(contains('password')));
        expect(serialized, isNot(contains('cookie')));
      }
      // Retry re-finds the saved job (GET only) and observes the terminal state.
      gateway.restoreResults.add(
        Future<PythonUnifiedAcademicSyncResult>.value(syncResult()),
      );
      await controller.retry();
      expect(controller.observationLost, isFalse);
      expect(controller.result, isNotNull);
      expect(controller.title, 'Sincronização concluída');
      expect(gateway.calls, 0); // restore/retry never created another job
      expect(gateway.restoreCalls, 2);
      expect(logger.events, contains('academic_sync_terminal_observed'));
      expect(
        logger.eventParameters['academic_sync_terminal_observed']!['status'],
        'succeeded',
      );
      controller.dispose();
      await gateway.updates.close();
    },
  );

  test('poll events are bounded to the first and every 15th attempt', () async {
    final gateway = ProgressGateway();
    final logger = _Logger();
    final controller = AcademicSyncController(
      gateway: gateway,
      logger: logger,
      idGenerator: () => 'sync-poll123',
    );
    final pending = controller.start();
    await Future<void>.delayed(Duration.zero);
    for (var attempt = 1; attempt <= 20; attempt++) {
      gateway.emitPoll(attempt, 'running');
    }
    expect(
      logger.events.where((event) => event == 'academic_sync_poll').length,
      2,
    );
    expect(logger.eventParameters['academic_sync_poll']!['attempt'], 15);
    expect(
      logger.eventParameters['academic_sync_poll']!['operation_id'],
      'sync-poll123',
    );
    gateway.response.complete(syncResult());
    await pending;
    expect(logger.events, contains('academic_sync_started'));
    controller.dispose();
    await gateway.updates.close();
  });

  test(
    'transient poll failures are recorded bounded with the operation id and never restart the job',
    () async {
      final gateway = ProgressGateway();
      final logger = _Logger();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
        idGenerator: () => 'sync-pollfail123',
      );
      final pending = controller.start();
      await Future<void>.delayed(Duration.zero);
      for (var attempt = 1; attempt <= 20; attempt++) {
        gateway.emitPollFailure(attempt, 'unavailable');
      }
      final failures = logger.events.where(
        (event) => event == 'academic_sync_poll_failed',
      );
      expect(failures.length, 2); // attempts 1 and 15 only
      expect(
        logger.eventParameters['academic_sync_poll_failed']!['attempt'],
        15,
      );
      expect(
        logger.eventParameters['academic_sync_poll_failed']!['code'],
        'unavailable',
      );
      expect(
        logger.eventParameters['academic_sync_poll_failed']!['operation_id'],
        'sync-pollfail123',
      );
      expect(gateway.calls, 1); // still exactly one job creation (one POST)
      gateway.response.complete(syncResult());
      await pending;
      expect(logger.events, contains('academic_sync_terminal_observed'));
      controller.dispose();
      await gateway.updates.close();
    },
  );

  test(
    'pause and resume log structured events with the operation id and resume re-finds the job once',
    () async {
      final gateway = _ResumableGateway();
      final logger = _Logger();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
      );
      final restoring = controller.restore();
      await Future<void>.delayed(Duration.zero);
      controller.onPaused();
      expect(logger.events, contains('academic_sync_paused'));
      expect(
        logger.eventParameters['academic_sync_paused']!['operation_id'],
        'sync-existing123',
      );
      // The Firestore watch stays alive across the pause.
      gateway.updates.add(
        const AcademicSyncProgress(
          operationId: 'sync-existing123',
          completed: 2,
          status: 'running',
        ),
      );
      expect(controller.receivedProgress, isTrue);
      // Resuming while still running must not start a second operation.
      await controller.onResumed();
      expect(logger.events, contains('academic_sync_resumed'));
      expect(
        logger.eventParameters['academic_sync_resumed']!['operation_id'],
        'sync-existing123',
      );
      expect(gateway.restoreCalls, 1);
      gateway.restoreResponse.complete(syncResult());
      await restoring;
      expect(controller.title, 'Sincronização concluída');
      // Resuming when idle re-finds the saved job again, still GET-only.
      await controller.onResumed();
      expect(gateway.restoreCalls, 2);
      expect(gateway.calls, 0);
      controller.dispose();
      await gateway.updates.close();
    },
  );

  test(
    'a transient failure surfaces an error and restore then recovers the saved partial result',
    () async {
      final gateway = _ResumableGateway();
      final logger = _Logger();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: logger,
        idGenerator: () => 'sync-transient1',
      );
      final failed = controller.start();
      await Future<void>.delayed(Duration.zero);
      gateway.response.completeError(
        const PythonBackendException(PythonBackendError.unavailable),
      );
      await expectLater(failed, throwsA(isA<PythonBackendException>()));
      expect(controller.error, isA<PythonBackendException>());
      expect(controller.title, contains('Não foi possível'));
      expect(logger.events, contains('academic_sync_failed'));
      expect(
        logger.eventParameters['academic_sync_failed']!['code'],
        'unavailable',
      );
      // The saved job is still on the server: restore (GET only) recovers it.
      gateway.restoreResults.add(
        Future<PythonUnifiedAcademicSyncResult>.value(
          syncResult(partial: true),
        ),
      );
      await controller.restore();
      expect(controller.error, isNull);
      expect(controller.result, isNotNull);
      // A partial result still surfaces its issues.
      expect(controller.title, 'Confira as pendências da sincronização');
      expect(controller.result!.exceptions.single.courseCode, 'ESA019');
      expect(gateway.calls, 1);
      controller.dispose();
      await gateway.updates.close();
    },
  );

  testWidgets(
    'observation-lost banner offers retry and result without blocking navigation',
    (tester) async {
      final gateway = _ResumableGateway();
      final controller = AcademicSyncController(
        gateway: gateway,
        logger: _Logger(),
      );
      var navigated = false;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                AcademicSyncBanner(
                  controller: controller,
                  onReview: () => navigated = true,
                ),
                TextButton(
                  key: const Key('behind-banner'),
                  onPressed: () => navigated = true,
                  child: const Text('Navegar'),
                ),
              ],
            ),
          ),
        ),
      );
      // First restore observes a partial result.
      gateway.restoreResults.add(
        Future<PythonUnifiedAcademicSyncResult>.value(
          syncResult(partial: true),
        ),
      );
      await controller.restore();
      await tester.pumpAndSettle();
      expect(controller.result, isNotNull);
      // The next observation hits the local deadline while the server job runs.
      final deadline = Completer<PythonUnifiedAcademicSyncResult>();
      gateway.restoreResults.add(deadline.future);
      final retrying = controller.retry();
      await tester.pump();
      gateway.updates.add(
        const AcademicSyncProgress(
          operationId: 'sync-existing123',
          completed: 1,
          status: 'running',
        ),
      );
      await tester.pump();
      deadline.completeError(
        const PythonBackendException(PythonBackendError.jobUnobserved),
      );
      await retrying;
      await tester.pumpAndSettle();
      expect(controller.observationLost, isTrue);
      expect(find.textContaining('Processando no servidor'), findsOneWidget);
      expect(find.text('Datas e materiais'), findsOneWidget);
      expect(find.byKey(const Key('retry-sync-banner')), findsOneWidget);
      // The previously observed result is still offered.
      expect(find.byKey(const Key('open-sync-result')), findsOneWidget);
      // Non-modal banner: the control behind it is still tappable.
      await tester.tap(find.byKey(const Key('behind-banner')));
      await tester.pump();
      expect(navigated, isTrue);
      // Retry from the banner re-finds the job and observes the result.
      gateway.restoreResults.add(
        Future<PythonUnifiedAcademicSyncResult>.value(syncResult()),
      );
      await tester.tap(find.byKey(const Key('retry-sync-banner')));
      await tester.pumpAndSettle();
      expect(controller.observationLost, isFalse);
      expect(controller.result, isNotNull);
      expect(gateway.calls, 0); // never a second POST
      expect(gateway.restoreCalls, 3);
      // The details sheet also offers the recoverable retry action.
      final deadlineAgain = Completer<PythonUnifiedAcademicSyncResult>();
      gateway.restoreResults.add(deadlineAgain.future);
      final retryingAgain = controller.retry();
      await tester.pump();
      deadlineAgain.completeError(
        const PythonBackendException(PythonBackendError.jobUnobserved),
      );
      await retryingAgain;
      await tester.pumpAndSettle();
      expect(controller.observationLost, isTrue);
      await tester.tap(find.byKey(const Key('academic-sync-indicator')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('retry-sync-sheet')), findsOneWidget);
      gateway.restoreResults.add(
        Future<PythonUnifiedAcademicSyncResult>.value(syncResult()),
      );
      await tester.tap(find.byKey(const Key('retry-sync-sheet')));
      await tester.pumpAndSettle();
      expect(controller.observationLost, isFalse);
      expect(controller.result, isNotNull);
      expect(gateway.restoreCalls, 5);
      expect(gateway.calls, 0);
      expect(tester.takeException(), isNull);
      controller.dispose();
      await gateway.updates.close();
    },
  );
}

class _Logger implements AppLogger {
  final events = <String>[];
  final eventParameters = <String, Map<String, Object>>{};
  final errors = <String>[];
  bool failRecording = false;
  bool failEvents = false;
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (failEvents) throw StateError('logger unavailable');
    events.add(name);
    if (parameters != null) eventParameters[name] = parameters;
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errors.add(context);
    if (failRecording) throw StateError('logger unavailable');
  }
}

class _CancelGateway extends ProgressGateway {
  final cancel = Completer<void>();
  late final source = StreamController<AcademicSyncProgress>(
    onCancel: () => cancel.future,
  );
  @override
  Stream<AcademicSyncProgress> watchSyncProgress(String operationId) =>
      source.stream;
}

class _LogStore implements OperationalLogStore {
  final documents = <Map<String, Object?>>[];
  @override
  Future<void> add(String userId, Map<String, Object?> document) async {
    expect(userId, 'user-1');
    documents.add(document);
  }
}

class _ResumableGateway extends ProgressGateway
    implements BackendResumableAcademicSyncGateway {
  bool missing = false;
  bool failing = false;
  @override
  Future<String?> pendingAcademicSyncId() async {
    if (failing) throw StateError('read unavailable');
    return missing ? null : 'sync-existing123';
  }
}
