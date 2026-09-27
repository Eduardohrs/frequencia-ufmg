final class StoredDocument {
  const StoredDocument({required this.id, required this.data});

  final String id;
  final Map<String, Object?> data;
}

abstract interface class DocumentStore {
  Future<List<StoredDocument>> list(String collectionPath);

  Future<void> set(String documentPath, Map<String, Object?> data);

  Future<void> delete(String documentPath);
}
