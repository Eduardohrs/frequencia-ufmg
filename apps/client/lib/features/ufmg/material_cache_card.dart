import 'package:flutter/material.dart';

import '../../data/material_file_cache.dart';

final class MaterialCacheCard extends StatelessWidget {
  const MaterialCacheCard({
    required this.files,
    required this.onOpen,
    required this.onRemove,
    required this.onClear,
    super.key,
  });

  final List<CachedMaterialFile> files;
  final ValueChanged<CachedMaterialFile> onOpen;
  final ValueChanged<CachedMaterialFile> onRemove;
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
          files.isEmpty
              ? 'Nenhuma cópia offline'
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

String formatMaterialFileSize(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
}
