import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'auth/auth_gate.dart';
import 'auth/auth_gateway.dart';
import 'auth/firebase_auth_gateway.dart';
import 'firebase_options.dart';

typedef AuthGatewayFactory = AuthGateway Function();

@visibleForTesting
AuthGatewayFactory authGatewayFactory = FirebaseAuthGateway.new;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  runApp(FrequenciaUFMGApp(authGateway: authGatewayFactory()));
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({required this.authGateway, super.key});

  final AuthGateway authGateway;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Frequência UFMG',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF006633)),
        useMaterial3: true,
      ),
      home: AuthGate(authGateway: authGateway),
    );
  }
}
