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
  bool _disposed = false;
  bool isRestoring = false;

  bool get isRunning => _active != null;
  static const stages = [
    'Disciplinas e horários',
    'Datas e materiais',
    'Planos de ensino',
  ];
  String get title {
    if (error != null) return 'Não foi possível concluir a sincronização';
    if (!isRunning && result != null) {
      return result!.exceptions.isEmpty
          ? 'Sincronização concluída'
          : 'Concluída com avisos para revisar';
    }
    if (progressUnavailable) return 'Sincronizando • progresso indisponível';
    if (!receivedProgress) return 'Iniciando sincronização…';
    return progress!.completed == 3
        ? 'Finalizando sincronização…'
        : stages[progress!.completed];
  }

  Future<void> restore() async {
    if (gateway case final BackendResumableAcademicSyncGateway resumable) {
      try {
        final id = await resumable.pendingAcademicSyncId();
        if (id != null && _active == null && !_disposed) {
          isRestoring = true;
          try {
            await _begin(id);
          } finally {
            isRestoring = false;
          }
        }
      } catch (failure, stack) {
        _progressFailure(
          progress?.operationId ?? 'restore',
          failure,
          stack,
          stage: 'restore',
        );
      }
    }
  }

  Future<PythonUnifiedAcademicSyncResult> start({bool force = false}) {
    return _begin(_idGenerator(), force: force);
  }

  Future<PythonUnifiedAcademicSyncResult> _begin(
    String id, {
    bool force = false,
  }) {
    if (_active case final active?) return active;
    result = null;
    error = null;
    visible = true;
    progressUnavailable = false;
    receivedProgress = false;
    progress = AcademicSyncProgress(
      operationId: id,
      completed: 0,
      status: 'running',
    );
    _active = _execute(id, force: force);
    _notify();
    return _active!;
  }

  Future<PythonUnifiedAcademicSyncResult> _execute(
    String id, {
    bool force = false,
  }) async {
    try {
      _watch(id);
      final completed = await runAuditedOperation(
        logger: logger,
        operation: AuditedOperation.academicSync,
        action: () => gateway.syncWithProgress(id, force: force),
      );
      result = completed;
      progress = AcademicSyncProgress(
        operationId: id,
        completed: 3,
        status: completed.exceptions.isEmpty ? 'succeeded' : 'partial',
        reviewRequired: completed.exceptions.length,
      );
      return completed;
    } catch (failure) {
      error = failure;
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
