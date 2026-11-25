import 'dart:async';

import 'package:flutter/material.dart';
import 'academic_sync_controller.dart';

class AcademicSyncBanner extends StatelessWidget {
  const AcademicSyncBanner({
    required this.controller,
    required this.onReview,
    this.detailsContext,
    super.key,
  });
  final AcademicSyncController controller;
  final VoidCallback onReview;
  final BuildContext? detailsContext;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      if (!controller.visible) return const SizedBox.shrink();
      return SafeArea(
        top: false,
        bottom: true,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Align(
            alignment: Alignment.center,
            heightFactor: 1,
            child: SizedBox(
              width: 360,
              child: Material(
                elevation: 4,
                color: Theme.of(context).colorScheme.surfaceContainer,
                borderRadius: BorderRadius.circular(18),
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  key: const Key('academic-sync-indicator'),
                  onTap: () => _details(detailsContext ?? context),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 0,
                    ),
                    child: controller.observationLost
                        ? _observationLost(context)
                        : Row(
                            children: [
                              SizedBox(
                                height: 48,
                                child: Icon(
                                  controller.error != null
                                      ? Icons.error_outline
                                      : controller.isRunning
                                      ? Icons.sync
                                      : Icons.info_outline,
                                ),
                              ),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  controller.title,
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              if (!controller.isRunning)
                                IconButton(
                                  key: const Key('dismiss-sync-banner'),
                                  tooltip:
                                      'Dispensar este aviso de sincronização',
                                  onPressed: controller.dismiss,
                                  icon: const Icon(Icons.close, size: 18),
                                ),
                            ],
                          ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    },
  );

  /// Recoverable state shown while the server job is still queued/running
  /// after the local observation deadline expired. Non-modal: normal
  /// navigation stays possible.
  Widget _observationLost(BuildContext context) {
    final stage = controller.lastStage;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const SizedBox(height: 48, child: Icon(Icons.cloud_sync)),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                controller.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        if (stage != null) ...[
          const SizedBox(height: 4),
          Text(stage, style: Theme.of(context).textTheme.bodySmall),
        ],
        const SizedBox(height: 8),
        Wrap(
          alignment: WrapAlignment.end,
          children: [
            if (controller.result != null)
              TextButton(
                key: const Key('open-sync-result'),
                onPressed: () => _details(detailsContext ?? context),
                child: const Text('Ver resultado'),
              ),
            TextButton(
              key: const Key('retry-sync-banner'),
              onPressed: () => unawaited(controller.retry()),
              child: const Text('Tentar novamente'),
            ),
          ],
        ),
      ],
    );
  }

  void _details(BuildContext context) {
    controller.logInteraction('sync_progress_details');
    var wasRunning = controller.isRunning;
    showModalBottomSheet<void>(
      context: context,
      useRootNavigator: true,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
          final running = controller.isRunning;
          if (wasRunning && !running) {
            // P2-15: a sincronização terminou enquanto o sheet estava aberto;
            // fecha sozinho em vez de ficar preso em 100%. O resultado
            // continua no banner, que reabre o sheet com "Ver resultado".
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (context.mounted && Navigator.of(context).canPop()) {
                Navigator.of(context).pop();
              }
            });
          }
          wasRunning = running;
          final completed = controller.progress?.completed ?? 0;
          return SafeArea(
            child: SingleChildScrollView(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      controller.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 16),
                    LinearProgressIndicator(
                      semanticsLabel:
                          '$completed de 3 etapas da sincronização concluídas',
                      value:
                          controller.isRunning && controller.progressUnavailable
                          ? null
                          : completed / 3,
                    ),
                    const SizedBox(height: 8),
                    Text('$completed de 3 etapas concluídas'),
                    for (
                      var index = 0;
                      index < AcademicSyncController.stages.length;
                      index++
                    )
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          index < completed
                              ? Icons.check_circle_outline
                              : Icons.radio_button_unchecked,
                        ),
                        title: Text(AcademicSyncController.stages[index]),
                      ),
                    if (controller.observationLost)
                      OutlinedButton(
                        key: const Key('retry-sync-sheet'),
                        onPressed: () => unawaited(controller.retry()),
                        child: const Text('Tentar novamente'),
                      ),
                    if (controller.result != null || controller.error != null)
                      FilledButton(
                        onPressed: () {
                          controller.logInteraction('sync_review_result');
                          Navigator.pop(context);
                          onReview();
                        },
                        child: Text(
                          controller.error != null
                              ? 'Abrir conexão'
                              : 'Ver resultado',
                        ),
                      ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
