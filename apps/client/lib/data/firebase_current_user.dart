// coverage:ignore-file
// Thin production boundary over the Firebase Auth SDK.

import 'package:firebase_auth/firebase_auth.dart';

String? currentFirebaseUserId() => FirebaseAuth.instance.currentUser?.uid;
