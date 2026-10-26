import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/academic_sync_progress.dart';
import 'package:frequencia_ufmg/features/ufmg/academic_sync_controller.dart';
import 'package:frequencia_ufmg/features/ufmg/academic_sync_banner.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'fixtures/academic_sync_fixture.dart';

void main() {
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
      expect(controller.title, 'Concluída com avisos para revisar');
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
        findsOneWidget,
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
      gateway.response.complete(syncResult());
      await tester.pumpAndSettle();
      await future;
      await tester.tap(find.text('Ver resultado'));
      await tester.pumpAndSettle();
      expect(reviewed, isTrue);
      await tester.tap(find.byTooltip('Ocultar sincronização'));
      await tester.pump();
      expect(find.byKey(const Key('academic-sync-indicator')), findsNothing);
      expect(tester.takeException(), isNull);
      controller.dispose();
      await gateway.updates.close();
    },
  );
}

class _Logger implements AppLogger {
  final events = <String>[];
  final errors = <String>[];
  bool failRecording = false;
  bool failEvents = false;
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (failEvents) throw StateError('logger unavailable');
    events.add(name);
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
