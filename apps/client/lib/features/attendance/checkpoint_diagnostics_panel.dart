import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import '../../data/attendance_permissions.dart';
import '../../data/checkpoint_diagnostics.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/error_log_details.dart';

class CheckpointDiagnosticsPanel extends StatefulWidget {
  const CheckpointDiagnosticsPanel({
    required this.permissions,
    required this.reports,
    required this.logger,
    required this.now,
    required this.onReviewPermissions,
    required this.onReviewAlarms,
    this.onTestNotification,
    super.key,
  });
  final AttendancePermissionsGateway permissions;
  final List<Map<String, Object?>> reports;
  final AppLogger logger;
  final DateTime Function() now;
  final Future<void> Function() onReviewPermissions, onReviewAlarms;
  final Future<void> Function()? onTestNotification;
  @override
  State<CheckpointDiagnosticsPanel> createState() =>
      _CheckpointDiagnosticsPanelState();
}

class _CheckpointDiagnosticsPanelState extends State<CheckpointDiagnosticsPanel>
    with WidgetsBindingObserver {
  AttendancePermissionStatus? _status;
  bool _busy = false, _failed = false;
  int _revision = 0;
  CheckpointDiagnostics get _diagnostics =>
      CheckpointDiagnostics(widget.reports);
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_refresh());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant CheckpointDiagnosticsPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.reports, widget.reports)) {
      _log('checkpoint_diagnostic_reports', _diagnostics.logFields);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_refresh());
  }

  void _log(String event, Map<String, Object?> fields, {String? operationId}) {
    unawaited(
      widget.logger
          .logEvent(
            event,
            parameters: {
              'operation_id':
                  operationId ?? newCorrelationId('checkpointDiagnostic'),
              'details': jsonEncode(fields),
            },
          )
          .catchError((Object error) {
            debugPrint(
              'checkpoint_diagnostic_log_delivery_failed type=${error.runtimeType}',
            );
          }),
    );
  }

  void _error(
    Object error,
    StackTrace stack,
    String stage, {
    required String operationId,
    required int durationMs,
  }) {
    unawaited(
      widget.logger
          .recordError(
            error,
            stack,
            context: 'checkpoint_diagnostic_$stage',
            parameters: {
              'operation_id': operationId,
              'details': jsonEncode({
                'stage': stage,
                'duration_ms': durationMs,
                ..._diagnostics.logFields,
              }),
            },
          )
          .catchError((Object error) {
            debugPrint(
              'checkpoint_diagnostic_log_delivery_failed type=${error.runtimeType}',
            );
          }),
    );
  }

  Future<void> _refresh() async {
    final revision = ++_revision;
    final operationId = newCorrelationId('checkpointDiagnostic');
    final watch = Stopwatch()..start();
    _log('checkpoint_diagnostic_started', {
      'stage': 'permissions',
    }, operationId: operationId);
    setState(() => _busy = true);
    try {
      final status = await widget.permissions.read().timeout(
        const Duration(seconds: 10),
      );
      _log('checkpoint_diagnostic_snapshot', {
        'stage': 'permissions',
        'duration_ms': watch.elapsedMilliseconds,
        'current_snapshot': mounted && revision == _revision,
        ...status.logFields,
        ..._diagnostics.logFields,
      }, operationId: operationId);
      if (!mounted || revision != _revision) return;
      setState(() {
        _status = status;
        _failed = false;
      });
    } catch (error, stack) {
      _error(
        error,
        stack,
        'permissions',
        operationId: operationId,
        durationMs: watch.elapsedMilliseconds,
      );
      if (mounted && revision == _revision) setState(() => _failed = true);
    } finally {
      if (mounted && revision == _revision) setState(() => _busy = false);
    }
  }

  Future<void> _review(String action, Future<void> Function() callback) async {
    final operationId = newCorrelationId('checkpointDiagnostic');
    final watch = Stopwatch()..start();
    _log('checkpoint_diagnostic_action_selected', {
      'action': action,
    }, operationId: operationId);
    try {
      await callback();
      _log('checkpoint_diagnostic_action_succeeded', {
        'action': action,
        'duration_ms': watch.elapsedMilliseconds,
      }, operationId: operationId);
      if (mounted) await _refresh();
    } catch (error, stack) {
      _error(
        error,
        stack,
        action,
        operationId: operationId,
        durationMs: watch.elapsedMilliseconds,
      );
    }
  }

  String _date(Object? value) {
    final d = DateTime.fromMillisecondsSinceEpoch(value as int).toLocal();
    return '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  String _location(AttendancePermissionStatus s) => !s.locationServices
      ? 'Localização desligada'
      : !s.foregroundLocation
      ? 'Sem acesso à localização'
      : !s.preciseLocation
      ? 'Localização aproximada'
      : !s.backgroundLocation
      ? 'Somente durante o uso'
      : 'Permitida sempre';
  @override
  Widget build(BuildContext context) {
    final d = _diagnostics, s = _status;
    final ready =
        s != null &&
        s.locationReady &&
        s.batteryUnrestricted &&
        s.exactAlarms == true;
    final next = d.next;
    final nextText = next == null
        ? 'Nenhum ping agendado'
        : '${next['course_code'] ?? 'Disciplina'} • ${_date(next['checkpoint_expected_at_ms'])}';
    final nextState = next?['status'] == 'running'
        ? 'Captura em andamento'
        : next != null &&
              (next['checkpoint_expected_at_ms'] as int) <=
                  widget.now().millisecondsSinceEpoch
        ? 'Aguardando execução'
        : 'Próximo ping';
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ListTile(
              title: const Text('Diagnóstico'),
              subtitle: Text(
                _failed
                    ? 'Não foi possível verificar o Android'
                    : s == null
                    ? 'Verificando configuração…'
                    : ready
                    ? 'Configuração pronta para os pings'
                    : 'Revisar configuração do Android',
              ),
              trailing: IconButton(
                tooltip: 'Atualizar diagnóstico',
                onPressed: _busy ? null : _refresh,
                icon: const Icon(Icons.refresh),
              ),
            ),
            if (_busy) const LinearProgressIndicator(),
            ListTile(
              leading: const Icon(Icons.schedule_outlined),
              title: Text(nextState),
              subtitle: Text(nextText),
            ),
            ListTile(
              leading: const Icon(Icons.cloud_upload_outlined),
              title: Text('${d.pendingUploads} resultado(s) aguardando envio'),
              subtitle: const Text(
                'O envio depende de conexão e das condições do Android.',
              ),
            ),
            if (s != null && !_failed)
              ExpansionTile(
                title: const Text('Configuração do Android'),
                children: [
                  ListTile(
                    title: const Text('Localização'),
                    subtitle: Text(_location(s)),
                  ),
                  ListTile(
                    title: const Text('Bateria do aplicativo'),
                    subtitle: Text(
                      s.batteryUnrestricted
                          ? 'Sem restrições'
                          : 'Otimizada ou restrita',
                    ),
                  ),
                  ListTile(
                    title: const Text('Economia geral'),
                    subtitle: Text(s.powerSaveMode ? 'Ligada' : 'Desligada'),
                  ),
                  ListTile(
                    title: const Text('Notificações'),
                    subtitle: Text(
                      s.notifications
                          ? 'Permitidas'
                          : 'Desativadas — os avisos podem não aparecer',
                    ),
                  ),
                  ListTile(
                    title: const Text('Alarmes e lembretes'),
                    subtitle: Text(
                      s.exactAlarms == null
                          ? 'Não verificado nesta versão'
                          : s.exactAlarms!
                          ? 'Permitidos'
                          : 'Não permitidos',
                    ),
                    trailing: TextButton(
                      onPressed: _busy
                          ? null
                          : () => _review('alarms', widget.onReviewAlarms),
                      child: const Text('Revisar'),
                    ),
                  ),
                ],
              ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: _busy
                    ? null
                    : () => _review('permissions', widget.onReviewPermissions),
                child: const Text('Revisar permissões'),
              ),
            ),
            if (widget.onTestNotification case final test?)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: _busy
                      ? null
                      : () => _review('test_notification', test),
                  child: const Text('Testar aviso'),
                ),
              ),
            if (d.lastProblem case final problem?)
              ExpansionTile(
                title: const Text('Último problema registrado'),
                subtitle: Text(
                  '${problem['course_code'] ?? 'Disciplina'} • ${const {'retry', 'rejected'}.contains(problem['delivery_status'])
                      ? 'Envio não concluído'
                      : problem['delivery_status'] == 'unresolved'
                      ? 'Evidência insuficiente'
                      : 'Captura não concluída'}',
                ),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: SelectableText(
                      sanitizeDiagnosticDetails(jsonEncode(d.problemDetails))!,
                    ),
                  ),
                ],
              )
            else
              const ListTile(title: Text('Nenhum problema registrado')),
          ],
        ),
      ),
    );
  }
}
