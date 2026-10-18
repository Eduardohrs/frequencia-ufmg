import 'package:flutter/material.dart';

import '../../data/material_file_cache.dart';

final class MaterialCacheCard extends StatelessWidget {
  const MaterialCacheCard({
    required this.files,
    required this.downloads,
    required this.onOpen,
    required this.onRemove,
    required this.onRetry,
    required this.onClear,
    super.key,
  });

  final List<CachedMaterialFile> files;
  final List<MaterialDownloadProgress> downloads;
  final ValueChanged<CachedMaterialFile> onOpen;
  final ValueChanged<CachedMaterialFile> onRemove;
  final ValueChanged<MaterialDownloadProgress> onRetry;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final totalBytes = files.fold<int>(0, (total, file) => total + file.size);
    return Card(
      margin: EdgeInsets.zero,
      child: ExpansionTile(
        initiallyExpanded: true,
        leading: const Icon(Icons.offline_pin_outlined),
        title: const Text('Arquivos neste dispositivo'),
        subtitle: Text(
          files.isEmpty && downloads.isEmpty
              ? 'Nenhuma cópia offline'
              : downloads.any(_isActive)
              ? '${downloads.where(_isActive).length} em andamento'
              : '${formatMaterialFileSize(totalBytes)} no dispositivo',
        ),
        trailing: files.isEmpty
            ? null
            : IconButton(
                key: const Key('cached-material-clear'),
                tooltip: 'Remover todas as cópias',
                onPressed: onClear,
                icon: const Icon(Icons.delete_sweep_outlined),
              ),
        children: [
          for (final download in downloads)
            ListTile(
              key: Key('material-download-progress-${download.id}'),
              leading: Icon(_downloadIcon(download.state)),
              title: Text(download.name),
              subtitle: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(_downloadLabel(download)),
                  if (_isActive(download))
                    LinearProgressIndicator(value: download.fraction),
                ],
              ),
              trailing: download.state == MaterialDownloadState.failed
                  ? IconButton(
                      key: Key('material-download-retry-${download.id}'),
                      tooltip: 'Tentar novamente',
                      onPressed: () => onRetry(download),
                      icon: const Icon(Icons.refresh),
                    )
                  : null,
            ),
          for (final file in files)
            ListTile(
              leading: const Icon(Icons.insert_drive_file_outlined),
              title: Text(file.name),
              subtitle: Text(formatMaterialFileSize(file.size)),
              onTap: () => onOpen(file),
              trailing: Wrap(
                spacing: 4,
                children: [
                  IconButton(
                    key: Key('cached-material-open-${file.id}'),
                    tooltip: 'Abrir cópia offline',
                    onPressed: () => onOpen(file),
                    icon: const Icon(Icons.open_in_new),
                  ),
                  IconButton(
                    key: Key('cached-material-remove-${file.id}'),
                    tooltip: 'Remover cópia offline',
                    onPressed: () => onRemove(file),
                    icon: const Icon(Icons.delete_outline),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

bool _isActive(MaterialDownloadProgress download) =>
    download.state == MaterialDownloadState.enqueued ||
    download.state == MaterialDownloadState.running;

String _downloadLabel(MaterialDownloadProgress download) =>
    switch (download.state) {
      MaterialDownloadState.enqueued => 'Na fila',
      MaterialDownloadState.running => 'Baixando',
      MaterialDownloadState.succeeded => 'Concluído',
      MaterialDownloadState.failed => _failureLabel(download.failureCode),
      MaterialDownloadState.cancelled => 'Cancelado',
    };

String _failureLabel(String code) => switch (code) {
  'timeout' => 'Falhou: o Moodle demorou para responder',
  'io_failure' => 'Falhou: conexão interrompida',
  'body_too_large' || 'declared_too_large' => 'Falhou: arquivo acima do limite',
  'directory_failure' => 'Falhou: armazenamento indisponível',
  'foreground_failure' => 'Falhou: execução em segundo plano bloqueada',
  'cancelled' => 'Cancelado',
  _ when code.startsWith('upstream_') =>
    'Falhou: resposta HTTP ${code.substring(9)}',
  _ => 'Falhou: motivo indisponível',
};

IconData _downloadIcon(MaterialDownloadState state) => switch (state) {
  MaterialDownloadState.enqueued => Icons.schedule_outlined,
  MaterialDownloadState.running => Icons.downloading_outlined,
  MaterialDownloadState.succeeded => Icons.check_circle_outline,
  MaterialDownloadState.failed => Icons.error_outline,
  MaterialDownloadState.cancelled => Icons.cancel_outlined,
};

String formatMaterialFileSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
