import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/io_material_file_cache.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  late Directory root;

  setUp(() async {
    root = await Directory.systemTemp.createTemp('material-cache-test-');
  });

  tearDown(() async {
    if (await root.exists()) await root.delete(recursive: true);
  });

  test('downloads, persists, lists and opens a private Moodle file', () async {
    final openedPaths = <String>[];
    final cache = IoMaterialFileCache(
      rootDirectory: () async => root,
      client: MockClient((request) async {
        expect(request.url.host, 'virtual.ufmg.br');
        expect(request.followRedirects, isFalse);
        return http.Response.bytes(utf8.encode('pdf-content'), 200);
      }),
      openFile: (path, mimeType) async {
        openedPaths.add(path);
        expect(mimeType, 'application/pdf');
        return true;
      },
    );
    expect(cache.isAvailable, isTrue);

    final saved = await cache.save(_download());

    expect(saved.name, 'Plano.pdf');
    expect(saved.size, 11);
    expect(await cache.list(), [saved]);
    await cache.open(saved.id);
    expect(openedPaths, hasLength(1));
    expect(await File(openedPaths.single).readAsString(), 'pdf-content');

    final index = await File(
      '${root.path}${Platform.pathSeparator}index.json',
    ).readAsString();
    expect(index, isNot(contains('tokenpluginfile')));
    expect(index, isNot(contains('aaaaaaaaaaaaaaaa')));

    final restored = IoMaterialFileCache(
      rootDirectory: () async => root,
      client: MockClient((_) async => fail('must not redownload')),
      openFile: (_, _) async => true,
    );
    expect(await restored.list(), [saved]);
  });

  test(
    'replaces the same logical file without leaving duplicate bytes',
    () async {
      var body = 'first';
      final cache = _cache(root, (_) async => http.Response(body, 200));

      await cache.save(_download());
      body = 'second-version';
      final saved = await cache.save(_download(name: 'Plano.txt'));

      expect(await cache.list(), [saved]);
      expect(
        root.listSync().whereType<File>().where(
          (file) => !file.path.endsWith('index.json'),
        ),
        hasLength(1),
      );
    },
  );

  test('removes one cached file and then clears the remaining files', () async {
    final cache = _cache(root, (_) async => http.Response('content', 200));
    final first = await cache.save(_download(id: 'first', name: 'A.pdf'));
    await cache.save(_download(id: 'second', name: 'B.pdf'));

    await cache.remove(first.id);
    expect((await cache.list()).map((file) => file.name), ['B.pdf']);

    await cache.clear();
    cache.dispose();
    expect(await cache.list(), isEmpty);
    expect(await root.exists(), isFalse);
  });

  test('drops stale metadata when Android has removed cached bytes', () async {
    final cache = _cache(root, (_) async => http.Response('content', 200));
    await cache.save(_download());
    final dataFile = root.listSync().whereType<File>().singleWhere(
      (file) => !file.path.endsWith('index.json'),
    );
    await dataFile.delete();

    expect(await cache.list(), isEmpty);
    expect(await root.exists(), isFalse);
  });

  test('rejects unsafe URLs before issuing a request', () async {
    final cache = _cache(root, (_) async => fail('must not request'));

    await expectLater(
      cache.save(
        _download(source: Uri.parse('https://example.com/private.pdf')),
      ),
      throwsA(isA<ArgumentError>()),
    );
    expect(root.listSync(), isEmpty);
  });

  test(
    'rejects failed and oversized downloads without partial files',
    () async {
      for (final response in [
        http.Response('unavailable', 503),
        http.Response.bytes(List<int>.filled(21, 1), 200),
      ]) {
        final cache = IoMaterialFileCache(
          rootDirectory: () async => root,
          client: MockClient((_) async => response),
          openFile: (_, _) async => true,
          maxFileBytes: 20,
        );

        await expectLater(cache.save(_download()), throwsA(isA<StateError>()));
        expect(root.listSync(), isEmpty);
      }
    },
  );

  test('reports missing files and rejected platform opens', () async {
    final cache = IoMaterialFileCache(
      rootDirectory: () async => root,
      client: MockClient((_) async => http.Response('content', 200)),
      openFile: (_, _) async => false,
    );

    await expectLater(cache.open('missing'), throwsA(isA<StateError>()));
    final saved = await cache.save(_download());
    await expectLater(cache.open(saved.id), throwsA(isA<StateError>()));
  });

  test('removes a partial streamed response that exceeds the limit', () async {
    final cache = IoMaterialFileCache(
      rootDirectory: () async => root,
      client: _StreamingClient(List<int>.filled(21, 1)),
      openFile: (_, _) async => true,
      maxFileBytes: 20,
    );

    await expectLater(cache.save(_download()), throwsA(isA<StateError>()));
    expect(root.listSync(), isEmpty);
  });

  test('disabled cache is explicit and performs no operations', () async {
    const cache = DisabledMaterialFileCache();

    expect(cache.isAvailable, isFalse);
    expect(await cache.list(), isEmpty);
    await expectLater(cache.save(_download()), throwsUnsupportedError);
    await expectLater(cache.open('id'), throwsUnsupportedError);
    await cache.remove('id');
    await cache.clear();
    cache.dispose();
  });

  test('cached file values have stable equality and hash codes', () {
    const first = CachedMaterialFile(
      id: 'id',
      name: 'File',
      size: 1,
      mimeType: 'text/plain',
    );
    const second = CachedMaterialFile(
      id: 'id',
      name: 'File',
      size: 1,
      mimeType: 'text/plain',
    );

    expect(first, second);
    expect(first.hashCode, second.hashCode);
  });

  test('disposes its HTTP client', () {
    final client = _StreamingClient(const []);
    final cache = IoMaterialFileCache(
      rootDirectory: () async => root,
      client: client,
      openFile: (_, _) async => true,
    );

    cache.dispose();

    expect(client.closed, isTrue);
  });
}

final class _StreamingClient extends http.BaseClient {
  _StreamingClient(this.bytes);

  final List<int> bytes;
  bool closed = false;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async =>
      http.StreamedResponse(Stream.value(bytes), 200);

  @override
  void close() {
    closed = true;
    super.close();
  }
}

IoMaterialFileCache _cache(
  Directory root,
  Future<http.Response> Function(http.Request) handler,
) => IoMaterialFileCache(
  rootDirectory: () async => root,
  client: MockClient(handler),
  openFile: (_, _) async => true,
);

MaterialDownload _download({
  String id = '2026-2/3701/102/Plano.pdf',
  String name = 'Plano.pdf',
  Uri? source,
}) => MaterialDownload(
  id: id,
  name: name,
  source:
      source ??
      Uri.parse(
        'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
        'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/plano.pdf'
        '?forcedownload=1',
      ),
  expectedSize: 11,
  mimeType: 'application/pdf',
);
