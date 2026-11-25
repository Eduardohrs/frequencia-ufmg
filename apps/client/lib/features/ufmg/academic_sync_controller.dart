import 'academic_sync_feedback.dart';
import 'dart:async';
import 'dart:math';
import 'package:flutter/foundation.dart';
import '../../backend/academic_sync_progress.dart';
import '../../backend/python_backend_transport.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

final class AcademicSyncController extends ChangeNotifier {
  AcademicSyncController({
    required this.gateway,
    required this.logger,
    String Function()? idGenerator,
  }) : _idGenerator = idGenerator ?? _newId;

  final BackendAcademicSyncProgressGateway gateway;
  final AppLogger logger;
  final String Function() _idGenerator;
  Future<PythonUnifiedAcademicSyncResult>? _active;
  StreamSubscription<AcademicSyncProgress>? _subscription;
  AcademicSyncProgress? progress;
  PythonUnifiedAcademicSyncResult? result;
  Object? error;
  bool visible = false;
  bool progressUnavailable = false;
  bool receivedProgress = false;
  bool observationLost = false;
  bool _disposed = false;
  bool isRestoring = false;
  final Stopwatch _elapsed = Stopwatch();
  int _pollAttempt = 0;
  String? _operationId;

  bool get isRunning => _active != null;
  static const stages = [
    'Disciplinas e horários',
    'Datas e materiais',
    'Planos de ensino',
  ];

  /// Last stage reported by the server, when progress was received.
  String? get lastStage {
    final current = progress;
    if (current == null || !receivedProgress || progressUnavailable) {
      return null;
    }
    return _stageLabel(current);
  }

  static String _stageLabel(AcademicSyncProgress value) =>
      value.completed >= stages.length
      ? 'Finalizando sincronização…'
      : stages[value.completed];

  String get title {
    if (observationLost) {
      final stage = lastStage;
      return stage == null
          ? 'Processando no servidor…'
          : 'Processando no servidor • $stage';
    }
    if (error != null) return 'Não foi possível concluir a sincronização';
    if (!isRunning && result != null) {
      return unifiedSyncIssues(result!).isEmpty
          ? 'Sincronização concluída'
          : 'Confira as pendências da sincronização';
    }
    if (progressUnavailable) return 'Sincronizando • progresso indisponível';
    if (!receivedProgress) return 'Iniciando sincronização…';
    return _stageLabel(progress!);
  }

  Future<void> restore() async {
    if (gateway case final BackendResumableAcademicSyncGateway resumable) {
      try {
        final id = await resumable.pendingAcademicSyncId();
        if (id != null && _active == null && !_disposed) {
          isRestoring = true;
          try {
            await _begin(id, restore: true);
          } finally {
            isRestoring = false;
          }
        }
      } catch (failure, stack) {
        final unobserved =
            failure is PythonBackendException &&
            failure.code == PythonBackendError.jobUnobserved;
        if (!unobserved) {
          _progressFailure(
            progress?.operationId ?? 'restore',
            failure,
            stack,
            stage: 'restore',
          );
        }
      }
    }
  }

  /// Re-finds the saved server job (GET only, never another POST) after the
  /// local observation deadline expired.
  Future<void> retry() async {
    logInteraction('sync_retry_observation');
    await restore();
  }

  Future<PythonUnifiedAcademicSyncResult> start({bool force = false}) {
    return _begin(_idGenerator(), force: force);
  }

  Future<PythonUnifiedAcademicSyncResult> _begin(
    String id, {
    bool force = false,
    bool restore = false,
  }) {
    if (_active case final active?) return active;
    // A restore re-attaches to the saved job: any previously observed result
    // stays available for "Ver resultado" while the job is re-observed.
    if (!restore) result = null;
    error = null;
    observationLost = false;
    visible = true;
    progressUnavailable = false;
    receivedProgress = false;
    _pollAttempt = 0;
    _operationId = id;
    _elapsed
      ..reset()
      ..start();
    progress = AcademicSyncProgress(
      operationId: id,
      completed: 0,
      status: 'running',
    );
    _active = _execute(id, force: force, restore: restore);
    _notify();
    return _active!;
  }

  Future<PythonUnifiedAcademicSyncResult> _execute(
    String id, {
    bool force = false,
    bool restore = false,
  }) async {
    _logSyncEvent('academic_sync_started', {
      'mode': restore ? 'restore' : 'start',
      'attempts': 0,
      'elapsed_ms': 0,
    });
    try {
      _watch(id);
      final completed = await runAuditedOperation(
        logger: logger,
        operation: AuditedOperation.academicSync,
        action: () => restore
            ? gateway.restoreAcademicSync(
                id,
                onPoll: _onPoll,
                onPollFailure: _onPollFailure,
              )
            : gateway.syncWithProgress(
                id,
                force: force,
                onPoll: _onPoll,
                onPollFailure: _onPollFailure,
              ),
      );
      result = completed;
      observationLost = false;
      final issues = unifiedSyncIssues(completed);
      visible = issues.isNotEmpty;
      final status = issues.isEmpty ? 'succeeded' : 'partial';
      progress = AcademicSyncProgress(
        operationId: id,
        completed: 3,
        status: status,
        reviewRequired: issues.length,
      );
      _logSyncEvent('academic_sync_terminal_observed', {
        'status': status,
        'attempts': _pollAttempt,
        'elapsed_ms': _elapsed.elapsedMilliseconds,
      });
      return completed;
    } catch (failure) {
      if (failure is PythonBackendException &&
          failure.code == PythonBackendError.jobUnobserved) {
        // The server job is still queued/running: keep an explainable,
        // recoverable state instead of an endless spinner or a fake error.
        observationLost = true;
        visible = true;
        _logSyncEvent('academic_sync_observation_deadline', {
          'code': failure.code.name,
          'attempts': _pollAttempt,
          'elapsed_ms': _elapsed.elapsedMilliseconds,
          'stage': lastStage ?? 'unknown',
          'status': progress?.status ?? 'unknown',
        });
      } else {
        error = failure;
        _logSyncEvent('academic_sync_failed', {
          'code': _safeCode(failure),
          'stage': lastStage ?? 'unknown',
          'elapsed_ms': _elapsed.elapsedMilliseconds,
        });
      }
      rethrow;
    } finally {
      _stopWatching(id);
      _active = null;
      if (!receivedProgress && !progressUnavailable) {
        _recordEvent(
          'academic_sync_progress_not_received',
          'no_server_updates',
        );
      }
      _notify();
    }
  }

  void _onPoll(int attempt, String status) {
    _pollAttempt = attempt;
    // Bounded telemetry: first poll plus every 15th attempt only.
    if (attempt == 1 || attempt % 15 == 0) {
      _logSyncEvent('academic_sync_poll', {
        'attempt': attempt,
        'status': status,
        'stage': lastStage ?? status,
        'elapsed_ms': _elapsed.elapsedMilliseconds,
      });
    }
  }

  void _onPollFailure(int attempt, String code) {
    // Bounded telemetry: first failure plus every 15th attempt only.
    if (attempt == 1 || attempt % 15 == 0) {
      _logSyncEvent('academic_sync_poll_failed', {
        'attempt': attempt,
        'code': code,
        'stage': lastStage ?? code,
        'elapsed_ms': _elapsed.elapsedMilliseconds,
      });
    }
  }

  /// App went to background. The Firestore progress watch stays alive; only
  /// the structured pause event is recorded.
  void onPaused() {
    _logSyncEvent('academic_sync_paused', {
      'running': isRunning,
      'stage': lastStage ?? 'unknown',
    });
  }

  /// App returned to the foreground: log it and re-find the saved job when
  /// nothing is running, without creating another one.
  Future<void> onResumed() async {
    _logSyncEvent('academic_sync_resumed', {
      'running': isRunning,
      'stage': lastStage ?? 'unknown',
    });
    if (!isRunning && !_disposed) {
      await restore();
    }
  }

  void _watch(String id) {
    try {
      _subscription = gateway.watchSyncProgress(id).listen(
        (value) {
          if (value.operationId != id ||
              value.completed < progress!.completed) {
            return;
          }
          if (receivedProgress &&
              value.completed == progress!.completed &&
              value.status == progress!.status) {
            return;
          }
          progress = value;
          receivedProgress = true;
          _recordEvent(
            'academic_sync_progress_received',
            '${value.completed}/3:${value.status}',
          );
          _notify();
        },
        onError: (Object failure, StackTrace stack) =>
            _progressFailure(id, failure, stack),
      );
    } catch (failure, stack) {
      _progressFailure(id, failure, stack, stage: 'subscribe');
    }
  }

  void _progressFailure(
    String id,
    Object failure,
    StackTrace stack, {
    String stage = 'listen',
  }) {
    progressUnavailable = true;
    unawaited(
      logger
          .recordError(
            failure,
            stack,
            context: 'academic_sync_progress_$stage',
            parameters: {'operation_id': id},
          )
          .catchError((_) {}),
    );
    _notify();
  }

  void _stopWatching(String id) {
    unawaited(
      _subscription?.cancel().catchError((Object failure, StackTrace stack) {
        _progressFailure(id, failure, stack, stage: 'cancel');
      }),
    );
    _subscription = null;
  }

  void dismiss() {
    if (isRunning) return;
    logInteraction('sync_indicator_dismiss');
    visible = false;
    _notify();
  }

  void logInteraction(String action) => _recordEvent('ui_interaction', action);

  void _recordEvent(String event, String action) {
    unawaited(
      logger
          .logEvent(
            event,
            parameters: {
              'operation': 'academic_sync',
              'screen': 'academic_sync',
              'action': action,
              'operation_id': ?progress?.operationId,
            },
          )
          .catchError((_) {}),
    );
  }

  /// Structured sync telemetry. Only safe fields (operation id, stage,
  /// attempt, elapsed time, safe code) — never credentials or headers.
  void _logSyncEvent(String event, Map<String, Object> fields) {
    final parameters = <String, Object>{
      'operation': 'academic_sync',
      'screen': 'academic_sync',
      ...fields,
    };
    final operationId = progress?.operationId ?? _operationId;
    if (operationId != null) parameters['operation_id'] = operationId;
    unawaited(
      logger.logEvent(event, parameters: parameters).catchError((_) {}),
    );
  }

  static String _safeCode(Object failure) => failure is PythonBackendException
      ? failure.code.name
      : failure.runtimeType.toString();

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _stopWatching(progress?.operationId ?? 'not-started');
    super.dispose();
  }

  static String _newId() =>
      'sync-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}-'
      '${Random.secure().nextInt(1 << 30).toRadixString(36)}';
}
