// coverage:ignore-file
// This file is a deliberately thin boundary around the Firebase SDK. Repository
// behavior is tested through DocumentStore fakes; Firebase itself is tested by
// its package and by the project's Firestore emulator rules suite.

import 'package:cloud_firestore/cloud_firestore.dart';

import 'document_store.dart';

final class FirebaseDocumentStore implements DocumentStore {
  FirebaseDocumentStore(this._firestore);

  final FirebaseFirestore _firestore;

  @override
  Future<List<StoredDocument>> list(String collectionPath) async {
    final snapshot = await _firestore.collection(collectionPath).get();
    return snapshot.docs
        .map(
          (document) => StoredDocument(id: document.id, data: document.data()),
        )
        .toList(growable: false);
  }

  @override
  Future<void> set(String documentPath, Map<String, Object?> data) =>
      _firestore.doc(documentPath).set(data);

  @override
  Future<void> delete(String documentPath) =>
      _firestore.doc(documentPath).delete();
}
