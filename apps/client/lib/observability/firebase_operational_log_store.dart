// coverage:ignore-file
// Thin production boundary over the Firestore SDK.

import 'package:cloud_firestore/cloud_firestore.dart';

import 'operational_log_store.dart';

final class FirebaseOperationalLogStore implements OperationalLogStore {
  FirebaseOperationalLogStore(this._firestore);

  final FirebaseFirestore _firestore;

  @override
  Future<void> add(String userId, Map<String, Object?> document) {
    final firestoreDocument = Map<String, Object?>.of(document);
    firestoreDocument['occurredAt'] = FieldValue.serverTimestamp();
    firestoreDocument['expiresAt'] = Timestamp.fromDate(
      document['expiresAt']! as DateTime,
    );
    return _firestore
        .collection('users')
        .doc(userId)
        .collection('logs')
        .add(firestoreDocument);
  }
}
