// coverage:ignore-file
// Production composition for Firebase SDK boundaries. Behavior is covered by
// repository tests with an in-memory DocumentStore.

import 'package:cloud_firestore/cloud_firestore.dart';

import '../observability/app_logger.dart';
import 'academic_repositories.dart';
import 'document_store.dart';
import 'firebase_document_store.dart';

CourseRepository createFirebaseCourseRepository(
  String userId,
  AppLogger logger,
) => FirestoreCourseRepository(
  userId: userId,
  store: TimeoutDocumentStore(
    FirebaseDocumentStore(FirebaseFirestore.instance),
  ),
  logger: logger,
);
