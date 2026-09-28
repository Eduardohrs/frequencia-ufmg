// coverage:ignore-file
// Thin production boundary over the Firestore SDK.

import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';

import 'operational_log_store.dart';

final class FirebaseOperationalLogStore implements OperationalLogStore {
  FirebaseOperationalLogStore(this._firestore);

  final FirebaseFirestore _firestore;
  final Set<String> _cleanedUsers = {};

  @override
  Future<void> add(String userId, Map<String, Object?> document) async {
    final firestoreDocument = Map<String, Object?>.of(document);
    firestoreDocument['occurredAt'] = FieldValue.serverTimestamp();
    firestoreDocument['expiresAt'] = Timestamp.fromDate(
      document['expiresAt']! as DateTime,
    );
    final logs = _firestore.collection('users').doc(userId).collection('logs');
    await logs.add(firestoreDocument);
    if (!_cleanedUsers.add(userId)) return;
    unawaited(
      _deleteExpired(logs).catchError((Object _) {
        _cleanedUsers.remove(userId);
      }),
    );
  }

  Future<void> _deleteExpired(
    CollectionReference<Map<String, dynamic>> logs,
  ) async {
    const batchSize = 100;
    while (true) {
      final expired = await logs
          .where('expiresAt', isLessThanOrEqualTo: Timestamp.now())
          .limit(batchSize)
          .get();
      if (expired.docs.isEmpty) return;
      final batch = _firestore.batch();
      for (final document in expired.docs) {
        batch.delete(document.reference);
      }
      await batch.commit();
      if (expired.docs.length < batchSize) return;
    }
  }
}
