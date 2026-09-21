import 'package:firebase_core_platform_interface/firebase_core_platform_interface.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/main.dart' as app;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  TestFirebaseCoreHostApi.setup(_FirebaseCoreHostApi());

  testWidgets('shows the product name', (tester) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      await app.main();
      await tester.pump();

      expect(find.text('Frequência UFMG'), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });
}

class _FirebaseCoreHostApi implements TestFirebaseCoreHostApi {
  @override
  Future<List<PigeonInitializeResponse?>> initializeCore() async => [];

  @override
  Future<PigeonInitializeResponse> initializeApp(
    String appName,
    PigeonFirebaseOptions options,
  ) async {
    return PigeonInitializeResponse(
      name: appName,
      options: options,
      pluginConstants: {},
    );
  }

  @override
  Future<PigeonFirebaseOptions> optionsFromResource() {
    throw UnimplementedError();
  }
}
