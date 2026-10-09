import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/document_store.dart';

void main() {
  test('forwards completed document operations', () async {
    final delegate = _MemoryDocumentStore();
    final store = TimeoutDocumentStore(delegate);

    await store.set('users/1', {'name': 'Eduardo'});
    await store.update('users/1', {'name': 'Eduardo H.'});
    final documents = await store.list('users');
    expect(documents.single.id, '1');
    expect(documents.single.data, {'name': 'Eduardo H.'});
    await store.deleteAll(['users/1']);

    expect(delegate.documents, isEmpty);
  });

  test('limits how long document operations can keep the UI waiting', () {
    final store = TimeoutDocumentStore(
      _PendingDocumentStore(),
      timeout: Duration.zero,
    );

    expect(store.list('users'), throwsA(isA<TimeoutException>()));
    expect(store.set('users/1', const {}), throwsA(isA<TimeoutException>()));
    expect(store.update('users/1', const {}), throwsA(isA<TimeoutException>()));
    expect(store.deleteAll(['users/1']), throwsA(isA<TimeoutException>()));
  });
}

final class _MemoryDocumentStore implements DocumentStore {
  final documents = <String, Map<String, Object?>>{};

  @override
  Future<void> deleteAll(Iterable<String> documentPaths) async {
    for (final path in documentPaths) {
      documents.remove(path);
    }
  }

  @override
  Future<List<StoredDocument>> list(String collectionPath) async => documents
      .entries
      .map(
        (entry) =>
            StoredDocument(id: entry.key.split('/').last, data: entry.value),
      )
      .toList();

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) async {
    documents[documentPath] = data;
  }

  @override
  Future<void> update(String documentPath, Map<String, Object?> data) async {
    documents[documentPath] = {...?documents[documentPath], ...data};
  }
}

final class _PendingDocumentStore implements DocumentStore {
  @override
  Future<void> deleteAll(Iterable<String> documentPaths) =>
      Completer<void>().future;

  @override
  Future<List<StoredDocument>> list(String collectionPath) =>
      Completer<List<StoredDocument>>().future;

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) =>
      Completer<void>().future;

  @override
  Future<void> update(String documentPath, Map<String, Object?> data) =>
      Completer<void>().future;
}
