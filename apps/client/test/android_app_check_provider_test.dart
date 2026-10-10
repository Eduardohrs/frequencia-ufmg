import 'package:firebase_app_check/firebase_app_check.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/firebase_python_backend.dart';

void main() {
  test('distributed debug APK uses Play Integrity by default', () {
    final provider = selectAndroidAppCheckProvider(debugProviderEnabled: false);

    expect(provider, isA<AndroidPlayIntegrityProvider>());
  });

  test('local development can explicitly opt into the debug provider', () {
    final provider = selectAndroidAppCheckProvider(debugProviderEnabled: true);

    expect(provider, isA<AndroidDebugProvider>());
  });
}
