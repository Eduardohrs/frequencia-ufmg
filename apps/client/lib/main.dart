import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'auth/auth_gate.dart';
import 'auth/auth_gateway.dart';
import 'auth/firebase_auth_gateway.dart';
import 'firebase_options.dart';
import 'observability/app_logger.dart';
import 'observability/error_reporting.dart';
import 'observability/firebase_app_logger.dart';

typedef AuthGatewayFactory = AuthGateway Function();
typedef AppLoggerFactory = AppLogger Function();

@visibleForTesting
AuthGatewayFactory authGatewayFactory = FirebaseAuthGateway.new;

@visibleForTesting
AppLoggerFactory appLoggerFactory = FirebaseAppLogger.new;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  final logger = appLoggerFactory();
  configureErrorReporting(logger);
  await logger.logEvent('app_started');
  runApp(FrequenciaUFMGApp(authGateway: authGatewayFactory(), logger: logger));
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({
    required this.authGateway,
    required this.logger,
    super.key,
  });

  final AuthGateway authGateway;
  final AppLogger logger;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Frequência UFMG',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF006633)),
        useMaterial3: true,
      ),
      home: AuthGate(authGateway: authGateway, logger: logger),
    );
  }
}
