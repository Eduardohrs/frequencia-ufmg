// coverage:ignore-file
import 'material_file_cache.dart';

MaterialFileCache createPlatformMaterialFileCache(String? userId) =>
    const DisabledMaterialFileCache();
