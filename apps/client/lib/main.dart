import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:timezone/data/latest.dart' as tz_data;

import 'auth/auth_gate.dart';
import 'auth/auth_gateway.dart';
import 'auth/firebase_auth_gateway.dart';
import 'data/academic_repositories.dart';
import 'data/firebase_course_repository.dart';
import 'data/firestore_configuration.dart';
import 'firebase_options.dart';
import 'observability/app_logger.dart';
import 'observability/error_reporting.dart';
import 'observability/firebase_logger_composition.dart';
import 'observability/resilient_app_logger.dart';

typedef AuthGatewayFactory = AuthGateway Function();
typedef AppLoggerFactory = AppLogger Function();
typedef MainCourseRepositoryFactory =
    CourseRepository Function(String userId, AppLogger logger);
typedef MainMeetingRepositoryFactory =
    MeetingRepository Function(String userId, AppLogger logger);
typedef MainSessionRepositoryFactory =
    SessionRepository Function(String userId, AppLogger logger);

@visibleForTesting
AuthGatewayFactory authGatewayFactory = FirebaseAuthGateway.new;

@visibleForTesting
AppLoggerFactory appLoggerFactory = createFirebaseLogger;

@visibleForTesting
MainCourseRepositoryFactory courseRepositoryFactory =
    createFirebaseCourseRepository;

@visibleForTesting
MainMeetingRepositoryFactory meetingRepositoryFactory =
    createFirebaseMeetingRepository;

@visibleForTesting
MainSessionRepositoryFactory sessionRepositoryFactory =
    createFirebaseSessionRepository;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  tz_data.initializeTimeZones();
  await Firebase.initializeApp(options: DefaultFirebaseOptions.currentPlatform);
  if (kIsWeb) {
    // coverage:ignore-start
    FirebaseFirestore.instance.settings = firestoreWebSettings;
    // coverage:ignore-end
  }
  final logger = ResilientAppLogger(appLoggerFactory());
  configureErrorReporting(logger);
  runApp(
    FrequenciaUFMGApp(
      authGateway: authGatewayFactory(),
      logger: logger,
      courseRepositoryFactory: (userId) =>
          courseRepositoryFactory(userId, logger),
      meetingRepositoryFactory: (userId) =>
          meetingRepositoryFactory(userId, logger),
      sessionRepositoryFactory: (userId) =>
          sessionRepositoryFactory(userId, logger),
    ),
  );
  await logger.logEvent('app_started');
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({
    required this.authGateway,
    required this.logger,
    required this.courseRepositoryFactory,
    required this.meetingRepositoryFactory,
    required this.sessionRepositoryFactory,
    super.key,
  });

  final AuthGateway authGateway;
  final AppLogger logger;
  final CourseRepository Function(String userId) courseRepositoryFactory;
  final MeetingRepository Function(String userId) meetingRepositoryFactory;
  final SessionRepository Function(String userId) sessionRepositoryFactory;

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
        meetingRepositoryFactory: meetingRepositoryFactory,
        sessionRepositoryFactory: sessionRepositoryFactory,
      ),
    );
  }
}
