final class MaterialDownload {
  const MaterialDownload({
    required this.id,
    required this.name,
    required this.source,
    required this.expectedSize,
    required this.mimeType,
  });

  final String id;
  final String name;
  final Uri source;
  final int expectedSize;
  final String mimeType;
}

final class CachedMaterialFile {
  const CachedMaterialFile({
    required this.id,
    required this.name,
    required this.size,
    required this.mimeType,
  });

  final String id;
  final String name;
  final int size;
  final String mimeType;

  @override
  bool operator ==(Object other) =>
      other is CachedMaterialFile &&
      id == other.id &&
      name == other.name &&
      size == other.size &&
      mimeType == other.mimeType;

  @override
  int get hashCode => Object.hash(id, name, size, mimeType);
}

abstract interface class MaterialFileCache {
  bool get isAvailable;

  Future<List<CachedMaterialFile>> list();

  Future<CachedMaterialFile> save(MaterialDownload download);

  Future<void> open(String id);

  Future<void> remove(String id);

  Future<void> clear();

  void dispose();
}

final class DisabledMaterialFileCache implements MaterialFileCache {
  const DisabledMaterialFileCache();

  @override
  bool get isAvailable => false;

  @override
  Future<List<CachedMaterialFile>> list() async => const [];

  @override
  Future<CachedMaterialFile> save(MaterialDownload download) =>
      Future.error(UnsupportedError('material cache is unavailable'));

  @override
  Future<void> open(String id) =>
      Future.error(UnsupportedError('material cache is unavailable'));

  @override
  Future<void> remove(String id) async {}

  @override
  Future<void> clear() async {}

  @override
  void dispose() {}
}
