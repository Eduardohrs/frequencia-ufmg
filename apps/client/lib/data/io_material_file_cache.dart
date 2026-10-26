import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

import 'material_file_cache.dart';
import 'material_download_failure.dart';

typedef MaterialCacheRoot = Future<Directory> Function();
typedef MaterialFileOpener =
    Future<bool> Function(String path, String mimeType);

final class IoMaterialFileCache implements MaterialFileCache {
  IoMaterialFileCache({
    required MaterialCacheRoot rootDirectory,
    required http.Client client,
    required MaterialFileOpener openFile,
    this.maxFileBytes = 100 * 1024 * 1024,
  }) : _rootDirectory = rootDirectory,
       _client = client,
       _openFile = openFile;

  final MaterialCacheRoot _rootDirectory;
  final http.Client _client;
  final MaterialFileOpener _openFile;
  final int maxFileBytes;

  @override
  bool get isAvailable => true;

  @override
  Future<List<CachedMaterialFile>> list() async {
    final root = await _rootDirectory();
    if (!await root.exists()) return const [];
    final records = await _readRecords(root);
    final usable = <_CacheRecord>[];
    for (final record in records) {
      if (await File(_filePath(root, record.storedName)).exists()) {
        usable.add(record);
      }
    }
    if (usable.length != records.length) await _writeRecords(root, usable);
    return usable.map((record) => record.file).toList(growable: false);
  }

  @override
  Future<CachedMaterialFile> save(MaterialDownload download) async {
    _validateDownload(download);
    final root = await _rootDirectory();
    await root.create(recursive: true);
    final records = await _readRecords(root);
    final storedName =
        '${_stableHash(download.id)}${_safeExtension(download.name)}';
    final target = File(_filePath(root, storedName));
    final partial = File('${target.path}.part');
    IOSink? sink;
    try {
      final request = http.Request('GET', download.source)
        ..followRedirects = false;
      final response = await _client.send(request);
      if (response.statusCode != HttpStatus.ok) {
        throw StateError('material download failed');
      }
      if ((response.contentLength ?? 0) > maxFileBytes) {
        throw StateError('material is too large');
      }
      sink = partial.openWrite();
      var received = 0;
      await for (final chunk in response.stream) {
        received += chunk.length;
        if (received > maxFileBytes) throw StateError('material is too large');
        sink.add(chunk);
      }
      await sink.close();
      sink = null;
      final declared = response.contentLength;
      final encoding = response.headers['content-encoding'];
      if (declared != null &&
          (encoding == null || encoding == 'identity') &&
          received != declared) {
        throw MaterialDownloadFailure(
          fileId: download.id,
          fileName: download.name,
          code: 'incomplete_body',
          received: received,
          total: declared,
          httpStatus: response.statusCode,
        );
      }
      if (await target.exists()) await target.delete();
      await partial.rename(target.path);
      for (final existing in records) {
        if (existing.file.id == download.id &&
            existing.storedName != storedName) {
          final replacedFile = File(_filePath(root, existing.storedName));
          if (await replacedFile.exists()) await replacedFile.delete();
        }
      }
      final record = _CacheRecord(
        file: CachedMaterialFile(
          id: download.id,
          name: download.name,
          size: received,
          mimeType: download.mimeType,
        ),
        storedName: storedName,
      );
      final replaced = [
        for (final existing in records)
          if (existing.file.id != download.id) existing,
        record,
      ];
      await _writeRecords(root, replaced);
      return record.file;
    } catch (_) {
      await sink?.close();
      if (await partial.exists()) await partial.delete();
      rethrow;
    }
  }

  @override
  Future<void> open(String id) async {
    final root = await _rootDirectory();
    final records = await _readRecords(root);
    _CacheRecord? found;
    for (final record in records) {
      if (record.file.id == id) found = record;
    }
    if (found == null) throw StateError('cached material is missing');
    final path = _filePath(root, found.storedName);
    if (!await File(path).exists() ||
        !await _openFile(path, found.file.mimeType)) {
      throw StateError('cached material could not be opened');
    }
  }

  @override
  Future<void> remove(String id) async {
    final root = await _rootDirectory();
    if (!await root.exists()) return;
    final records = await _readRecords(root);
    final kept = <_CacheRecord>[];
    for (final record in records) {
      if (record.file.id == id) {
        final file = File(_filePath(root, record.storedName));
        if (await file.exists()) await file.delete();
      } else {
        kept.add(record);
      }
    }
    await _writeRecords(root, kept);
  }

  @override
  Future<void> clear() async {
    final root = await _rootDirectory();
    if (!await root.exists()) return;
    await root.delete(recursive: true);
  }

  @override
  void dispose() => _client.close();

  Future<List<_CacheRecord>> _readRecords(Directory root) async {
    final index = File(_filePath(root, 'index.json'));
    if (!await index.exists()) return const [];
    final decoded = jsonDecode(await index.readAsString());
    if (decoded is! Map<String, Object?> ||
        decoded['version'] != 1 ||
        decoded['files'] is! List<Object?>) {
      throw const FormatException('invalid material cache index');
    }
    return (decoded['files']! as List<Object?>)
        .map(_CacheRecord.fromJson)
        .toList(growable: false);
  }

  Future<void> _writeRecords(Directory root, List<_CacheRecord> records) async {
    if (records.isEmpty) {
      final index = File(_filePath(root, 'index.json'));
      if (await index.exists()) await index.delete();
      if (await root.exists() && root.listSync().isEmpty) await root.delete();
      return;
    }
    await root.create(recursive: true);
    final index = File(_filePath(root, 'index.json'));
    final temporary = File('${index.path}.part');
    await temporary.writeAsString(
      jsonEncode({
        'version': 1,
        'files': records.map((record) => record.toJson()).toList(),
      }),
      flush: true,
    );
    if (await index.exists()) await index.delete();
    await temporary.rename(index.path);
  }
}

final class _CacheRecord {
  const _CacheRecord({required this.file, required this.storedName});

  factory _CacheRecord.fromJson(Object? value) {
    if (value is! Map<String, Object?> ||
        value.keys.toSet().difference(_keys).isNotEmpty ||
        value.length != _keys.length ||
        value['id'] is! String ||
        value['name'] is! String ||
        value['size'] is! int ||
        value['mime_type'] is! String ||
        value['stored_name'] is! String) {
      throw const FormatException('invalid material cache record');
    }
    final storedName = value['stored_name']! as String;
    if (!RegExp(r'^[0-9a-f]{16}(\.[A-Za-z0-9]{1,10})?$').hasMatch(storedName)) {
      throw const FormatException('invalid cached material path');
    }
    return _CacheRecord(
      file: CachedMaterialFile(
        id: value['id']! as String,
        name: value['name']! as String,
        size: value['size']! as int,
        mimeType: value['mime_type']! as String,
      ),
      storedName: storedName,
    );
  }

  static const _keys = {'id', 'name', 'size', 'mime_type', 'stored_name'};

  final CachedMaterialFile file;
  final String storedName;

  Map<String, Object> toJson() => {
    'id': file.id,
    'name': file.name,
    'size': file.size,
    'mime_type': file.mimeType,
    'stored_name': storedName,
  };
}

void _validateDownload(MaterialDownload download) {
  if (download.id.isEmpty ||
      download.id.length > 512 ||
      download.name.isEmpty ||
      download.name.length > 255 ||
      download.expectedSize < 0 ||
      download.source.scheme != 'https' ||
      download.source.host != 'virtual.ufmg.br' ||
      download.source.hasPort ||
      download.source.userInfo.isNotEmpty ||
      download.source.hasFragment ||
      download.source.pathSegments.length < 8 ||
      download.source.pathSegments[1] != 'tokenpluginfile.php' ||
      download.source.queryParametersAll.length != 1 ||
      download.source.queryParameters['forcedownload'] != '1') {
    throw ArgumentError('invalid Moodle material download');
  }
}

String _safeExtension(String name) {
  final dot = name.lastIndexOf('.');
  if (dot <= 0 || dot == name.length - 1) return '';
  final extension = name.substring(dot);
  return RegExp(r'^\.[A-Za-z0-9]{1,10}$').hasMatch(extension) ? extension : '';
}

String _filePath(Directory root, String name) =>
    '${root.path}${Platform.pathSeparator}$name';

String _stableHash(String value) {
  return sha256.convert(utf8.encode(value)).toString().substring(0, 16);
}
