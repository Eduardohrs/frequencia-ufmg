import 'package:flutter/services.dart';

import 'material_file_cache.dart';

typedef PlatformMethodInvoker =
    Future<T?> Function<T>(String method, [Object? arguments]);

final class AndroidMaterialFileCache
    implements MaterialFileCache, BackgroundMaterialDownloadQueue {
  AndroidMaterialFileCache({
    required MaterialFileCache delegate,
    required String namespace,
    PlatformMethodInvoker? invokeMethod,
  }) : _delegate = delegate,
       _namespace = namespace,
       _invokeMethod = invokeMethod ?? _channel.invokeMethod {
    if (!_namespacePattern.hasMatch(namespace)) {
      throw ArgumentError.value(namespace, 'namespace');
    }
  }

  static const _channel = MethodChannel(
    'br.ufmg.frequencia.frequencia_ufmg/material_downloads',
  );
  static final _namespacePattern = RegExp(r'^[0-9a-f]{24}$');

  final MaterialFileCache _delegate;
  final String _namespace;
  final PlatformMethodInvoker _invokeMethod;

  @override
  bool get isAvailable => _delegate.isAvailable;

  @override
  Future<void> enqueue(MaterialDownload download) =>
      _invokeMethod<void>('enqueue', <String, Object>{
        'id': download.id,
        'name': download.name,
        'source': download.source.toString(),
        'expected_size': download.expectedSize,
        'mime_type': download.mimeType,
        'namespace': _namespace,
      });

  @override
  Future<List<MaterialDownloadProgress>> listDownloads() async {
    final raw = await _invokeMethod<List<Object?>>('listQueue', {
      'namespace': _namespace,
    });
    return [
      for (final item in raw ?? const [])
        if (item is Map)
          MaterialDownloadProgress(
            id: item['id'] as String,
            name: item['name'] as String,
            state: _downloadState(item['state'] as String?),
            downloaded: (item['downloaded'] as num?)?.toInt() ?? 0,
            total: (item['total'] as num?)?.toInt() ?? 0,
            failureCode: item['failureCode'] as String? ?? '',
            stage: item['stage'] as String? ?? 'native_worker',
            attempt: (item['attempt'] as num?)?.toInt() ?? 0,
            elapsedMs: (item['elapsedMs'] as num?)?.toInt() ?? 0,
            httpStatus: (item['httpStatus'] as num?)?.toInt() ?? 0,
            workId: item['workId'] as String? ?? '',
          ),
    ];
  }

  @override
  Future<void> dismissDownload(String id) => _invokeMethod<void>(
    'dismiss',
    <String, Object>{'id': id, 'namespace': _namespace},
  );

  @override
  Future<List<CachedMaterialFile>> list() => _delegate.list();

  @override
  Future<CachedMaterialFile> save(MaterialDownload download) =>
      _delegate.save(download);

  @override
  Future<void> open(String id) => _delegate.open(id);

  @override
  Future<void> remove(String id) async {
    await _invokeMethod<void>('cancel', <String, Object>{
      'id': id,
      'namespace': _namespace,
    });
    await _delegate.remove(id);
  }

  @override
  Future<void> clear() async {
    await _invokeMethod<void>('cancelAll', <String, Object>{
      'namespace': _namespace,
    });
    await _delegate.clear();
  }

  @override
  void dispose() => _delegate.dispose();
}

MaterialDownloadState _downloadState(String? value) => switch (value) {
  'running' => MaterialDownloadState.running,
  'succeeded' => MaterialDownloadState.succeeded,
  'failed' => MaterialDownloadState.failed,
  'cancelled' => MaterialDownloadState.cancelled,
  _ => MaterialDownloadState.enqueued,
};
