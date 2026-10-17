import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/android_material_file_cache.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';

void main() {
  test(
    'uses the production platform channel when no test invoker is given',
    () {
      final delegate = _Cache();
      final cache = AndroidMaterialFileCache(
        delegate: delegate,
        namespace: '0123456789abcdef01234567',
      );

      expect(cache.isAvailable, isTrue);
      cache.dispose();
    },
  );

  test(
    'enqueues only the fields required by the native Android worker',
    () async {
      final delegate = _Cache();
      final calls = <(String, Object?)>[];
      final cache = AndroidMaterialFileCache(
        delegate: delegate,
        namespace: '0123456789abcdef01234567',
        invokeMethod: <T>(method, [arguments]) async {
          calls.add((method, arguments));
          return null;
        },
      );

      await cache.enqueue(_download());

      expect(calls, hasLength(1));
      expect(calls.single.$1, 'enqueue');
      expect(calls.single.$2, {
        'id': '2026-2/3701/102/Plano.pdf',
        'name': 'Plano.pdf',
        'source':
            'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
            'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf'
            '?forcedownload=1',
        'expected_size': 11,
        'mime_type': 'application/pdf',
        'namespace': '0123456789abcdef01234567',
      });
      expect(delegate.saved, isEmpty);
    },
  );

  test(
    'cancels matching work before removal and all work before clear',
    () async {
      final delegate = _Cache();
      final calls = <(String, Object?)>[];
      final cache = AndroidMaterialFileCache(
        delegate: delegate,
        namespace: '0123456789abcdef01234567',
        invokeMethod: <T>(method, [arguments]) async {
          calls.add((method, arguments));
          return null;
        },
      );

      await cache.remove('file-id');
      await cache.clear();

      expect(calls.map((call) => call.$1), ['cancel', 'cancelAll']);
      expect(calls[0].$2, {
        'id': 'file-id',
        'namespace': '0123456789abcdef01234567',
      });
      expect(calls[1].$2, {'namespace': '0123456789abcdef01234567'});
      expect(delegate.removed, ['file-id']);
      expect(delegate.clearCalls, 1);
    },
  );

  test('delegates completed-cache operations and disposal', () async {
    final delegate = _Cache()
      ..files.add(
        const CachedMaterialFile(
          id: 'id',
          name: 'Plano.pdf',
          size: 11,
          mimeType: 'application/pdf',
        ),
      );
    final cache = AndroidMaterialFileCache(
      delegate: delegate,
      namespace: '0123456789abcdef01234567',
      invokeMethod: <T>(method, [arguments]) async => null,
    );

    expect(cache.isAvailable, isTrue);
    expect(await cache.list(), delegate.files);
    await cache.open('id');
    expect(delegate.opened, ['id']);
    expect(await cache.save(_download()), delegate.files.last);
    cache.dispose();
    expect(delegate.disposed, isTrue);
  });

  test('rejects invalid namespaces before crossing the platform boundary', () {
    expect(
      () => AndroidMaterialFileCache(
        delegate: _Cache(),
        namespace: '../unsafe',
        invokeMethod: <T>(method, [arguments]) async => null,
      ),
      throwsArgumentError,
    );
  });
}

final class _Cache implements MaterialFileCache {
  final files = <CachedMaterialFile>[];
  final saved = <MaterialDownload>[];
  final opened = <String>[];
  final removed = <String>[];
  int clearCalls = 0;
  bool disposed = false;

  @override
  bool get isAvailable => true;

  @override
  Future<void> clear() async {
    clearCalls++;
    files.clear();
  }

  @override
  void dispose() => disposed = true;

  @override
  Future<List<CachedMaterialFile>> list() async => List.of(files);

  @override
  Future<void> open(String id) async => opened.add(id);

  @override
  Future<void> remove(String id) async {
    removed.add(id);
    files.removeWhere((file) => file.id == id);
  }

  @override
  Future<CachedMaterialFile> save(MaterialDownload download) async {
    saved.add(download);
    final file = CachedMaterialFile(
      id: download.id,
      name: download.name,
      size: download.expectedSize,
      mimeType: download.mimeType,
    );
    files.add(file);
    return file;
  }
}

MaterialDownload _download() => MaterialDownload(
  id: '2026-2/3701/102/Plano.pdf',
  name: 'Plano.pdf',
  source: Uri.parse(
    'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
    'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf'
    '?forcedownload=1',
  ),
  expectedSize: 11,
  mimeType: 'application/pdf',
);
