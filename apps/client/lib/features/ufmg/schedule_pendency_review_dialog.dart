import 'dart:async';

import 'package:flutter/material.dart';

import '../../backend/python_backend_transport.dart';
import '../../design/app_feedback.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

/// Diálogo que leva o aviso de conflito de horário até a resolução:
/// mostra disciplina, horário atual/novo e motivo, e permite manter ou aplicar.
class SchedulePendencyReviewDialog extends StatefulWidget {
  const SchedulePendencyReviewDialog({
    required this.gateway,
    required this.logger,
    super.key,
  });

  final BackendSchedulePendencyGateway gateway;
  final AppLogger logger;

  @override
  State<SchedulePendencyReviewDialog> createState() =>
      _SchedulePendencyReviewDialogState();
}

class _SchedulePendencyReviewDialogState
    extends State<SchedulePendencyReviewDialog> {
  bool _loading = true;
  String? _error;
  List<PythonSchedulePendency> _pendencies = const [];
  final Set<String> _deciding = <String>{};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSync,
        action: widget.gateway.listSchedulePendencies,
      );
      if (!mounted) return;
      setState(() {
        _pendencies = items;
        _loading = false;
      });
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'schedule_pendency_list')
            .catchError((_) => null),
      );
      if (!mounted) return;
      setState(() {
        _error = 'Não foi possível carregar as pendências de horário.';
        _loading = false;
      });
    }
  }

  Future<void> _decide(
    PythonSchedulePendency pendency,
    PythonScheduleDecision decision,
  ) async {
    if (_deciding.contains(pendency.id)) return;
    setState(() => _deciding.add(pendency.id));
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSync,
        action: () => widget.gateway.decideSchedulePendency(
          pendency.id,
          decision: decision,
        ),
      );
      if (!mounted) return;
      await _load();
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'schedule_pendency_decide')
            .catchError((_) => null),
      );
      if (!mounted) return;
      setState(() => _error = 'Não foi possível registrar a decisão.');
    } finally {
      if (mounted) setState(() => _deciding.remove(pendency.id));
    }
  }

  String _decisionLabel(String? decision) => switch (decision) {
    'manter_atual' => 'Horário atual mantido',
    'aplicar_mudanca' => 'Mudança aplicada',
    _ => 'Decisão registrada',
  };

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const AppDialogHeader(
        icon: Icons.schedule_outlined,
        title: 'Pendências de horário',
        subtitle:
            'Decida se mantém o horário atual ou aplica a mudança da UFMG.',
      ),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Center(child: CircularProgressIndicator()),
                ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.all(8),
                  child: Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              if (!_loading && _pendencies.isEmpty && _error == null)
                const Text('Nenhuma pendência de horário no momento.'),
              for (final pendency in _pendencies) ...[
                Text(
                  '${pendency.courseCode} · ${pendency.courseName}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 4),
                Text('Atual: ${pendency.currentSchedule}'),
                Text('Novo: ${pendency.newSchedule}'),
                Text('Motivo: ${pendency.reason}'),
                const SizedBox(height: 8),
                if (pendency.isResolved)
                  Text(
                    _decisionLabel(pendency.decision),
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.primary,
                    ),
                  )
                else
                  Wrap(
                    spacing: 8,
                    children: [
                      OutlinedButton(
                        key: Key('pendency-keep-${pendency.id}'),
                        onPressed: _deciding.contains(pendency.id)
                            ? null
                            : () => _decide(
                                pendency,
                                PythonScheduleDecision.manterAtual,
                              ),
                        child: const Text('Manter horário atual'),
                      ),
                      FilledButton(
                        key: Key('pendency-apply-${pendency.id}'),
                        onPressed: _deciding.contains(pendency.id)
                            ? null
                            : () => _decide(
                                pendency,
                                PythonScheduleDecision.aplicarMudanca,
                              ),
                        child: const Text('Aplicar mudança'),
                      ),
                    ],
                  ),
                const SizedBox(height: 16),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('pendency-review-refresh'),
          onPressed: _loading ? null : _load,
          child: const Text('Atualizar'),
        ),
        FilledButton(
          key: const Key('pendency-review-close'),
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Fechar'),
        ),
      ],
    );
  }
}
