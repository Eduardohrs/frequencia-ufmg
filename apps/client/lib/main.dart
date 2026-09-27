import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'auth/auth_gate.dart';
import 'auth/auth_gateway.dart';
import 'auth/firebase_auth_gateway.dart';
import 'data/academic_repositories.dart';
import 'data/firebase_course_repository.dart';
import 'data/firestore_configuration.dart';
import 'firebase_options.dart';
import 'observability/app_logger.dart';
import 'observability/error_reporting.dart';
import 'observability/firebase_app_logger.dart';
import 'observability/resilient_app_logger.dart';

typedef AuthGatewayFactory = AuthGateway Function();
typedef AppLoggerFactory = AppLogger Function();
typedef MainCourseRepositoryFactory =
    CourseRepository Function(String userId, AppLogger logger);

@visibleForTesting
AuthGatewayFactory authGatewayFactory = FirebaseAuthGateway.new;

@visibleForTesting
AppLoggerFactory appLoggerFactory = FirebaseAppLogger.new;

@visibleForTesting
MainCourseRepositoryFactory courseRepositoryFactory =
    createFirebaseCourseRepository;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  if (kIsWeb) {
    FirebaseFirestore.instance.settings = firestoreWebSettings; // coverage:ignore-line
  }
  final logger = ResilientAppLogger(appLoggerFactory());
  configureErrorReporting(logger);
  runApp(
    FrequenciaUFMGApp(
      authGateway: authGatewayFactory(),
      logger: logger,
      courseRepositoryFactory: (userId) =>
          courseRepositoryFactory(userId, logger),
    ),
  );
  await logger.logEvent('app_started');
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({
    required this.authGateway,
    required this.logger,
    required this.courseRepositoryFactory,
    super.key,
  });

  final AuthGateway authGateway;
  final AppLogger logger;
  final CourseRepository Function(String userId) courseRepositoryFactory;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Frequência UFMG',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF006633)),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF7F9F7),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFFF7F9F7),
          surfaceTintColor: Colors.transparent,
        ),
        cardTheme: CardThemeData(
          color: Colors.white,
          shape: RoundedRectangleBorder(
            side: const BorderSide(color: Color(0xFFDDE5DF)),
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
        ),
      ),
      home: AuthGate(
        authGateway: authGateway,
        logger: logger,
        courseRepositoryFactory: courseRepositoryFactory,
      ),
    );
  }
}
