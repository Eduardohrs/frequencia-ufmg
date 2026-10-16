import 'material_file_cache.dart';
import 'material_file_cache_factory_stub.dart'
    if (dart.library.io) 'material_file_cache_factory_io.dart'
    as platform;

MaterialFileCache createMaterialFileCache(String? userId) =>
    platform.createPlatformMaterialFileCache(userId);
