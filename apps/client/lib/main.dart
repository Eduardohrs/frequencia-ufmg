import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:timezone/data/latest.dart' as tz_data;

import 'auth/auth_gate.dart';
import 'auth/auth_gateway.dart';
import 'auth/firebase_auth_gateway.dart';
import 'backend/firebase_python_backend.dart';
import 'backend/python_backend_transport.dart';
import 'data/academic_repositories.dart';
import 'data/cached_academic_overview_repository.dart';
import 'data/firebase_current_user.dart';
import 'data/firebase_course_repository.dart';
import 'data/firestore_configuration.dart';
import 'data/python_course_repository.dart';
import 'data/python_overview_repository.dart';
import 'data/shared_preferences_academic_overview_cache.dart';
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
typedef BackendIdentityVerifierFactory = BackendIdentityVerifier? Function();

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

@visibleForTesting
BackendIdentityVerifierFactory backendIdentityVerifierFactory =
    createFirebasePythonBackendVerifier;

@visibleForTesting
MainCourseRepositoryFactory resolveCourseRepositoryFactory(
  BackendIdentityVerifier? backend,
) => backend is BackendCourseGateway
    ? (String _, AppLogger logger) => PythonCourseRepository(
        gateway: backend as BackendCourseGateway,
        logger: logger,
      )
    : courseRepositoryFactory;

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
  final backend = backendIdentityVerifierFactory();
  final effectiveCourseRepositoryFactory = resolveCourseRepositoryFactory(
    backend,
  );
  final overviewRepository = backend is BackendOverviewGateway
      ? CachedAcademicOverviewRepository(
          remote: PythonOverviewRepository(
            gateway: backend as BackendOverviewGateway,
            logger: logger,
          ),
          cache: SharedPreferencesAcademicOverviewCache(),
          currentUserId: currentFirebaseUserId,
          logger: logger,
        )
      : null;
  configureErrorReporting(logger);
  runApp(
    FrequenciaUFMGApp(
      authGateway: authGatewayFactory(),
      logger: logger,
      courseRepositoryFactory: (userId) =>
          effectiveCourseRepositoryFactory(userId, logger),
      fallbackCourseRepositoryFactory: (userId) =>
          courseRepositoryFactory(userId, logger),
      meetingRepositoryFactory: (userId) =>
          meetingRepositoryFactory(userId, logger),
      sessionRepositoryFactory: (userId) =>
          sessionRepositoryFactory(userId, logger),
      backendIdentityVerifier: backend,
      attendanceEvaluator: backend is BackendAttendanceEvaluator
          ? backend as BackendAttendanceEvaluator
          : null,
      scheduleGateway: backend is BackendScheduleGateway
          ? backend as BackendScheduleGateway
          : null,
      sessionGateway: backend is BackendSessionGateway
          ? backend as BackendSessionGateway
          : null,
      overviewRepository: overviewRepository,
      scheduleWritesEnabled: pythonScheduleWritesEnabled,
      sessionWritesEnabled: pythonSessionWritesEnabled,
      overviewReadsEnabled: pythonOverviewReadsEnabled,
      androidOfflineQueueEnabled:
          !kIsWeb && defaultTargetPlatform == TargetPlatform.android,
    ),
  );
  await logger.logEvent('app_started');
}

class FrequenciaUFMGApp extends StatelessWidget {
  const FrequenciaUFMGApp({
    required this.authGateway,
    required this.logger,
    required this.courseRepositoryFactory,
    this.fallbackCourseRepositoryFactory,
    required this.meetingRepositoryFactory,
    required this.sessionRepositoryFactory,
    this.backendIdentityVerifier,
    this.attendanceEvaluator,
    this.scheduleGateway,
    this.sessionGateway,
    this.overviewRepository,
    this.scheduleWritesEnabled = false,
    this.sessionWritesEnabled = false,
    this.overviewReadsEnabled = false,
    this.androidOfflineQueueEnabled = false,
    super.key,
  });

  final AuthGateway authGateway;
  final AppLogger logger;
  final CourseRepository Function(String userId) courseRepositoryFactory;
  final CourseRepository Function(String userId)?
  fallbackCourseRepositoryFactory;
  final MeetingRepository Function(String userId) meetingRepositoryFactory;
  final SessionRepository Function(String userId) sessionRepositoryFactory;
  final BackendIdentityVerifier? backendIdentityVerifier;
  final BackendAttendanceEvaluator? attendanceEvaluator;
  final BackendScheduleGateway? scheduleGateway;
  final BackendSessionGateway? sessionGateway;
  final AcademicOverviewRepository? overviewRepository;
  final bool scheduleWritesEnabled;
  final bool sessionWritesEnabled;
  final bool overviewReadsEnabled;
  final bool androidOfflineQueueEnabled;

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
        fallbackCourseRepositoryFactory: fallbackCourseRepositoryFactory,
        meetingRepositoryFactory: meetingRepositoryFactory,
        sessionRepositoryFactory: sessionRepositoryFactory,
        backendIdentityVerifier: backendIdentityVerifier,
        attendanceEvaluator: attendanceEvaluator,
        scheduleGateway: scheduleGateway,
        sessionGateway: sessionGateway,
        overviewRepository: overviewRepository,
        scheduleWritesEnabled: scheduleWritesEnabled,
        sessionWritesEnabled: sessionWritesEnabled,
        overviewReadsEnabled: overviewReadsEnabled,
        androidOfflineQueueEnabled: androidOfflineQueueEnabled,
      ),
    );
  }
}
