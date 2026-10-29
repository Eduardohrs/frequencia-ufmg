import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

/// Opt-in one-shot diagnostic. It never creates attendance records.
class BackgroundProofPanel extends StatefulWidget {
  const BackgroundProofPanel({required this.logger, super.key});
  final AppLogger logger;
  @override
  State<BackgroundProofPanel> createState() => _BackgroundProofPanelState();
}

class _BackgroundProofPanelState extends State<BackgroundProofPanel> {
  static const _channel = MethodChannel(
    'br.ufmg.frequencia.frequencia_ufmg/background_proof',
  );
  bool _busy = false;
  String? _message;

  Future<void> _run(String action) async {
    setState(() => _busy = true);
    final requestId = newCorrelationId('backgroundProof');
    unawaited(
      widget.logger
          .logEvent(
            'background_proof_action_started',
            parameters: {
              'operation_id': requestId,
              'action': action,
              'details': jsonEncode({'stage': action}),
            },
          )
          .catchError((Object error) {
            debugPrint(
              'background_proof_log_delivery_failed type=${error.runtimeType}',
            );
          }),
    );
    try {
      final report =
          await _channel.invokeMapMethod<String, Object?>(action) ?? {};
      unawaited(
        widget.logger
            .logEvent(
              'background_proof_report',
              parameters: {
                'action': action,
                'details': jsonEncode({...report, 'request_id': requestId}),
                if (report['operation_id'] case final String operationId)
                  'operation_id': operationId,
              },
            )
            .catchError((Object error) {
              debugPrint(
                'background_proof_log_delivery_failed type=${error.runtimeType}',
              );
            }),
      );
      final status = report['status'];
      final message = switch (status) {
        null => 'Nenhum teste agendado.',
        'scheduled' =>
          'Agendado para daqui a pelo menos 2 minutos. Saia do app e bloqueie a tela; depois volte e consulte o resultado.',
        'running' =>
          'O Android iniciou o teste. Aguarde a leitura da localização.',
        'succeeded' when report['background_proven'] == true =>
          'Captura em segundo plano confirmada. Precisão: ${report['accuracy_m']} m.',
        'succeeded' =>
          'Localização recebida com o app visível. Isso ainda não comprova captura em segundo plano.',
        _ =>
          'Teste não confirmado: $status. Revise as permissões e consulte os logs.',
      };
      if (mounted) setState(() => _message = message);
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(
              error,
              stack,
              context: 'background_proof_$action',
              parameters: {
                'operation_id': requestId,
                'details': jsonEncode({'stage': action}),
              },
            )
            .catchError((Object logError) {
              debugPrint(
                'background_proof_log_delivery_failed type=${logError.runtimeType}',
              );
            }),
      );
      if (mounted) {
        setState(
          () => _message =
              'Não foi possível consultar ou agendar o teste. Tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Teste de localização em segundo plano',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          const Text(
            'Teste opcional, sem registrar presença. O Android pode adiar a execução. Requer localização precisa e acesso permitido o tempo todo.',
          ),
          Wrap(
            spacing: 8,
            children: [
              TextButton(
                onPressed: _busy ? null : () => _run('schedule'),
                child: const Text('Agendar teste'),
              ),
              TextButton(
                onPressed: _busy ? null : () => _run('read'),
                child: const Text('Consultar resultado'),
              ),
            ],
          ),
          if (_busy) const LinearProgressIndicator(),
          if (_message case final message?)
            Semantics(liveRegion: true, child: Text(message)),
        ],
      ),
    ),
  );
}
