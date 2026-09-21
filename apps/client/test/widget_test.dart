import 'package:firebase_core_platform_interface/test.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/main.dart' as app;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  TestFirebaseCoreHostApi.setUp(_FirebaseCoreHostApi());

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
  Future<List<CoreInitializeResponse>> initializeCore() async => [];

  @override
  Future<CoreInitializeResponse> initializeApp(
    String appName,
    CoreFirebaseOptions options,
  ) async {
    return CoreInitializeResponse(
      name: appName,
      options: options,
      pluginConstants: {},
    );
  }

  @override
  Future<CoreFirebaseOptions> optionsFromResource() async {
    return CoreFirebaseOptions(
      apiKey: 'test',
      projectId: 'test',
      appId: 'test',
      messagingSenderId: 'test',
    );
  }
}
