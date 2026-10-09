final class StoredDocument {
  const StoredDocument({required this.id, required this.data});

  final String id;
  final Map<String, Object?> data;
}

abstract interface class DocumentStore {
  Future<List<StoredDocument>> list(String collectionPath);

  Future<void> set(String documentPath, Map<String, Object?> data);

  Future<void> update(String documentPath, Map<String, Object?> data);

  Future<void> deleteAll(Iterable<String> documentPaths);
}

final class TimeoutDocumentStore implements DocumentStore {
  TimeoutDocumentStore(
    this._delegate, {
    Duration timeout = const Duration(seconds: 30),
  }) : _timeout = timeout;

  final DocumentStore _delegate;
  final Duration _timeout;

  @override
  Future<List<StoredDocument>> list(String collectionPath) =>
      _delegate.list(collectionPath).timeout(_timeout);

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) =>
      _delegate.set(documentPath, data).timeout(_timeout);

  @override
  Future<void> update(String documentPath, Map<String, Object?> data) =>
      _delegate.update(documentPath, data).timeout(_timeout);

  @override
  Future<void> deleteAll(Iterable<String> documentPaths) =>
      _delegate.deleteAll(documentPaths).timeout(_timeout);
}
