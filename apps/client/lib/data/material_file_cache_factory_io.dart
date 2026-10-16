// coverage:ignore-file
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import 'io_material_file_cache.dart';
import 'material_file_cache.dart';

MaterialFileCache createPlatformMaterialFileCache(String? userId) {
  if (!Platform.isAndroid || userId == null || userId.isEmpty) {
    return const DisabledMaterialFileCache();
  }
  final namespace = sha256
      .convert(utf8.encode(userId))
      .toString()
      .substring(0, 24);
  return IoMaterialFileCache(
    rootDirectory: () async {
      final support = await getApplicationSupportDirectory();
      return Directory(
        '${support.path}${Platform.pathSeparator}moodle_materials'
        '${Platform.pathSeparator}$namespace',
      );
    },
    client: http.Client(),
    openFile: (path, mimeType) async {
      final result = await OpenFilex.open(path, type: mimeType);
      return result.type == ResultType.done;
    },
  );
}
