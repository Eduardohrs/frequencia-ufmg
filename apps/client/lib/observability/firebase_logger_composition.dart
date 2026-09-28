// coverage:ignore-file
// Production composition for Firebase SDK boundaries.

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

import 'app_logger.dart';
import 'composite_app_logger.dart';
import 'firebase_app_logger.dart';
import 'firebase_operational_log_store.dart';
import 'firestore_app_logger.dart';
import 'resilient_app_logger.dart';

AppLogger createFirebaseLogger() => CompositeAppLogger([
  ResilientAppLogger(
    FirebaseAppLogger(),
    transport: 'firebase_analytics_crashlytics',
    deliveryTimeout: const Duration(seconds: 4),
  ),
  ResilientAppLogger(
    FirestoreAppLogger(
      store: FirebaseOperationalLogStore(FirebaseFirestore.instance),
      currentUserId: () => FirebaseAuth.instance.currentUser?.uid,
      platform: kIsWeb ? 'web' : 'android',
    ),
    transport: 'firestore_operational_logs',
    deliveryTimeout: const Duration(seconds: 4),
  ),
]);
