import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_core_platform_interface/test.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/material_download_failure.dart';
import 'package:frequencia_ufmg/observability/firebase_app_logger.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  TestFirebaseCoreHostApi.setUp(_Core());

  test(
    'error reaches Analytics SDK and Crashlytics with accepted event name',
    () async {
      final calls = <MethodCall>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMessageHandler(
            'dev.flutter.pigeon.firebase_crashlytics_platform_interface.FirebaseCrashlyticsHostApi.recordError',
            (message) async {
              calls.add(const MethodCall('Crashlytics#recordError'));
              return const StandardMessageCodec().encodeMessage(<Object?>[
                null,
              ]);
            },
          );
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockDecodedMessageHandler<Object?>(
            const BasicMessageChannel<Object?>(
              'dev.flutter.pigeon.firebase_analytics_platform_interface.FirebaseAnalyticsHostApi.logEvent',
              StandardMessageCodec(),
            ),
            (message) async {
              calls.add(
                MethodCall('Analytics#logEvent', (message as List).single),
              );
              return <Object?>[null];
            },
          );
      for (final channel in ['firebase_analytics', 'firebase_crashlytics']) {
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(
              MethodChannel('plugins.flutter.io/$channel'),
              (call) async {
                calls.add(call);
                return null;
              },
            );
      }
      await Firebase.initializeApp();
      await FirebaseAppLogger().recordError(
        MaterialDownloadFailure(
          fileId: 'file',
          fileName: 'Plano.pdf',
          code: 'incomplete_body',
          received: 3,
          total: 11,
        ),
        StackTrace.current,
        context: 'moodle_material_native_download',
      );
      final analytics = calls.singleWhere(
        (call) => call.method == 'Analytics#logEvent',
      );
      expect(analytics.arguments['eventName'], 'client_error');
      expect(
        analytics.arguments['parameters']['error_code'],
        'incomplete_body',
      );
      expect(
        calls.any((call) => call.method == 'Crashlytics#recordError'),
        isTrue,
      );
    },
  );
}

class _Core extends MockFirebaseApp {
  @override
  Future<List<CoreInitializeResponse>> initializeCore() async {
    final apps = await super.initializeCore();
    for (final app in apps) {
      app.pluginConstants['plugins.flutter.io/firebase_crashlytics'] = {
        'isCrashlyticsCollectionEnabled': false,
      };
    }
    return apps;
  }
}
