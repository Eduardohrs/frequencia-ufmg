import 'auth_user.dart';

abstract interface class AuthGateway {
  AuthUser? get currentUser;

  Stream<AuthUser?> get authStateChanges;

  Future<void> signInWithGoogle();

  Future<void> signOut();
}
