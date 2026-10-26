import 'package:flutter/material.dart';
import 'academic_sync_controller.dart';

class AcademicSyncBanner extends StatelessWidget {
  const AcademicSyncBanner({
    required this.controller,
    required this.onReview,
    super.key,
  });
  final AcademicSyncController controller;
  final VoidCallback onReview;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      if (!controller.visible) return const SizedBox.shrink();
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Align(
            alignment: Alignment.bottomRight,
            child: SizedBox(
              width: 360,
              child: Material(
                elevation: 4,
                color: Theme.of(context).colorScheme.surfaceContainer,
                borderRadius: BorderRadius.circular(18),
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  key: const Key('academic-sync-indicator'),
                  onTap: () => _details(context),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    child: Row(
                      children: [
                        Icon(
                          controller.error != null
                              ? Icons.error_outline
                              : controller.isRunning
                              ? Icons.sync
                              : Icons.check_circle_outline,
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
                            tooltip: 'Ocultar sincronização',
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

  void _details(BuildContext context) {
    controller.logInteraction('sync_progress_details');
    showModalBottomSheet<void>(
      context: context,
      useRootNavigator: true,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
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
                    if (controller.isRunning)
                      const Text(
                        'Você pode continuar usando o aplicativo. Mantenha-o aberto para acompanhar o resultado.',
                      ),
                    if (controller.error != null)
                      const Text(
                        'As etapas já concluídas foram mantidas. Confira seus dados antes de tentar novamente.',
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
