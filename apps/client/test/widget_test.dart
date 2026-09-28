import 'dart:async';

import 'package:firebase_core_platform_interface/test.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_gateway.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/main.dart' as app;
import 'package:frequencia_ufmg/observability/app_logger.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  TestFirebaseCoreHostApi.setUp(_FirebaseCoreHostApi());

  testWidgets('bootstraps Firebase and shows the signed-out experience', (
    tester,
  ) async {
    final gateway = _FakeAuthGateway();
    final logger = _FakeAppLogger();
    addTearDown(gateway.close);
    app.authGatewayFactory = () => gateway;
    app.appLoggerFactory = () => logger;
    app.courseRepositoryFactory = (_, _) => _FakeCourseRepository();
    app.meetingRepositoryFactory = (_, _) => _FakeMeetingRepository();
    final previousFlutterHandler = FlutterError.onError;
    final previousPlatformHandler = PlatformDispatcher.instance.onError;
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      await app.main();
      await tester.pump();

      expect(find.text('Frequência UFMG'), findsOneWidget);
      expect(find.text('Entrar com Google'), findsOneWidget);
      expect(logger.events, ['app_started']);
    } finally {
      debugDefaultTargetPlatformOverride = null;
      FlutterError.onError = previousFlutterHandler;
      PlatformDispatcher.instance.onError = previousPlatformHandler;
    }
  });

  testWidgets('renders before startup analytics delivery completes', (
    tester,
  ) async {
    final gateway = _FakeAuthGateway();
    final delivery = Completer<void>();
    final logger = _FakeAppLogger(logCompleter: delivery);
    addTearDown(gateway.close);
    app.authGatewayFactory = () => gateway;
    app.appLoggerFactory = () => logger;
    app.courseRepositoryFactory = (_, _) => _FakeCourseRepository();
    app.meetingRepositoryFactory = (_, _) => _FakeMeetingRepository();
    final previousFlutterHandler = FlutterError.onError;
    final previousPlatformHandler = PlatformDispatcher.instance.onError;
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      final startup = app.main();
      await tester.pump();

      final renderedBeforeDelivery = find
          .text('Entrar com Google')
          .evaluate()
          .isNotEmpty;
      delivery.complete();
      await startup;
      expect(renderedBeforeDelivery, isTrue);
    } finally {
      debugDefaultTargetPlatformOverride = null;
      FlutterError.onError = previousFlutterHandler;
      PlatformDispatcher.instance.onError = previousPlatformHandler;
    }
  });

  testWidgets('bootstraps the repository for an authenticated user', (
    tester,
  ) async {
    final gateway = _FakeAuthGateway(
      initialUser: AuthUser(id: 'user-42', email: 'aluno@ufmg.br'),
    );
    final logger = _FakeAppLogger();
    var repositoryUserId = '';
    addTearDown(gateway.close);
    app.authGatewayFactory = () => gateway;
    app.appLoggerFactory = () => logger;
    app.courseRepositoryFactory = (userId, _) {
      repositoryUserId = userId;
      return _FakeCourseRepository();
    };
    app.meetingRepositoryFactory = (_, _) => _FakeMeetingRepository();
    final previousFlutterHandler = FlutterError.onError;
    final previousPlatformHandler = PlatformDispatcher.instance.onError;
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      await app.main();
      await tester.pumpAndSettle();

      expect(repositoryUserId, 'user-42');
      expect(find.text('Suas disciplinas'), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = null;
      FlutterError.onError = previousFlutterHandler;
      PlatformDispatcher.instance.onError = previousPlatformHandler;
    }
  });

  testWidgets('signs in and presents the authenticated user', (tester) async {
    final completer = Completer<void>();
    final gateway = _FakeAuthGateway(signInCompleter: completer);
    final logger = _FakeAppLogger();
    addTearDown(gateway.close);
    await tester.pumpWidget(
      app.FrequenciaUFMGApp(
        authGateway: gateway,
        logger: logger,
        courseRepositoryFactory: (_) => _FakeCourseRepository(),
        meetingRepositoryFactory: (_) => _FakeMeetingRepository(),
      ),
    );

    await tester.tap(find.text('Entrar com Google'));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(gateway.signInCalls, 1);

    completer.complete();
    await tester.pumpAndSettle();
    expect(find.text('Olá, Eduardo'), findsOneWidget);
    expect(find.text('eduardo@ufmg.br'), findsOneWidget);
    expect(find.text('Nenhuma disciplina cadastrada'), findsOneWidget);
    expect(logger.events, [
      'auth_google_sign_in_started',
      'auth_google_sign_in_succeeded',
    ]);
  });

  testWidgets('shows a friendly message when sign-in fails', (tester) async {
    final gateway = _FakeAuthGateway(signInFails: true);
    final logger = _FakeAppLogger();
    addTearDown(gateway.close);
    await tester.pumpWidget(
      app.FrequenciaUFMGApp(
        authGateway: gateway,
        logger: logger,
        courseRepositoryFactory: (_) => _FakeCourseRepository(),
        meetingRepositoryFactory: (_) => _FakeMeetingRepository(),
      ),
    );

    await tester.tap(find.text('Entrar com Google'));
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível entrar. Tente novamente.'),
      findsOneWidget,
    );
    expect(find.text('Entrar com Google'), findsOneWidget);
    expect(logger.events, [
      'auth_google_sign_in_started',
      'auth_google_sign_in_failed',
    ]);
    expect(logger.errorContexts, ['auth_google_sign_in']);
  });

  testWidgets('signs out and returns to the login screen', (tester) async {
    final gateway = _FakeAuthGateway(
      initialUser: AuthUser(id: '1', email: 'aluno@ufmg.br'),
    );
    final logger = _FakeAppLogger();
    addTearDown(gateway.close);
    await tester.pumpWidget(
      app.FrequenciaUFMGApp(
        authGateway: gateway,
        logger: logger,
        courseRepositoryFactory: (_) => _FakeCourseRepository(),
        meetingRepositoryFactory: (_) => _FakeMeetingRepository(),
      ),
    );

    expect(find.text('Suas disciplinas'), findsOneWidget);
    await tester.tap(find.byTooltip('Sair'));
    await tester.pumpAndSettle();

    expect(gateway.signOutCalls, 1);
    expect(find.text('Entrar com Google'), findsOneWidget);
    expect(logger.events, ['auth_logout_started', 'auth_logout_succeeded']);
  });
}

class _FakeAppLogger implements AppLogger {
  _FakeAppLogger({this.logCompleter});

  final Completer<void>? logCompleter;
  final events = <String>[];
  final errorContexts = <String>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
    await logCompleter?.future;
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errorContexts.add(context);
  }
}

final class _FakeCourseRepository implements CourseRepository {
  @override
  Future<void> deleteCourse(String courseId) async {}

  @override
  Future<List<CourseRecord>> listCourses() async => [];

  @override
  Future<void> saveCourse(CourseRecord course) async {}
}

final class _FakeMeetingRepository implements MeetingRepository {
  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {}

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async => [];

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {}
}

class _FakeAuthGateway implements AuthGateway {
  _FakeAuthGateway({
    AuthUser? initialUser,
    this.signInCompleter,
    this.signInFails = false,
  }) : _currentUser = initialUser;

  final _controller = StreamController<AuthUser?>.broadcast();
  final Completer<void>? signInCompleter;
  final bool signInFails;
  AuthUser? _currentUser;
  int signInCalls = 0;
  int signOutCalls = 0;

  @override
  AuthUser? get currentUser => _currentUser;

  @override
  Stream<AuthUser?> get authStateChanges => _controller.stream;

  @override
  Future<void> signInWithGoogle() async {
    signInCalls++;
    if (signInFails) throw Exception('test failure');
    await signInCompleter?.future;
    _currentUser = AuthUser(
      id: '1',
      email: 'eduardo@ufmg.br',
      displayName: 'Eduardo',
      photoUrl: 'https://example.test/photo.png',
    );
    _controller.add(_currentUser);
  }

  @override
  Future<void> signOut() async {
    signOutCalls++;
    _currentUser = null;
    _controller.add(null);
  }

  Future<void> close() => _controller.close();
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
