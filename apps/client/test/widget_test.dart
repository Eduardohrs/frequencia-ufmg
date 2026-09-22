import 'dart:async';

import 'package:firebase_core_platform_interface/test.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/auth/auth_gateway.dart';
import 'package:frequencia_ufmg/auth/auth_user.dart';
import 'package:frequencia_ufmg/main.dart' as app;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  TestFirebaseCoreHostApi.setUp(_FirebaseCoreHostApi());

  testWidgets('bootstraps Firebase and shows the signed-out experience', (
    tester,
  ) async {
    final gateway = _FakeAuthGateway();
    addTearDown(gateway.close);
    app.authGatewayFactory = () => gateway;
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    try {
      await app.main();
      await tester.pump();

      expect(find.text('Frequência UFMG'), findsOneWidget);
      expect(find.text('Entrar com Google'), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });

  testWidgets('signs in and presents the authenticated user', (tester) async {
    final completer = Completer<void>();
    final gateway = _FakeAuthGateway(signInCompleter: completer);
    addTearDown(gateway.close);
    await tester.pumpWidget(app.FrequenciaUFMGApp(authGateway: gateway));

    await tester.tap(find.text('Entrar com Google'));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(gateway.signInCalls, 1);

    completer.complete();
    await tester.pumpAndSettle();
    expect(find.text('Olá, Eduardo!'), findsOneWidget);
    expect(find.text('eduardo@ufmg.br'), findsOneWidget);
  });

  testWidgets('shows a friendly message when sign-in fails', (tester) async {
    final gateway = _FakeAuthGateway(signInFails: true);
    addTearDown(gateway.close);
    await tester.pumpWidget(app.FrequenciaUFMGApp(authGateway: gateway));

    await tester.tap(find.text('Entrar com Google'));
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível entrar. Tente novamente.'),
      findsOneWidget,
    );
    expect(find.text('Entrar com Google'), findsOneWidget);
  });

  testWidgets('signs out and returns to the login screen', (tester) async {
    final gateway = _FakeAuthGateway(
      initialUser: const AuthUser(id: '1', email: 'aluno@ufmg.br'),
    );
    addTearDown(gateway.close);
    await tester.pumpWidget(app.FrequenciaUFMGApp(authGateway: gateway));

    expect(find.text('Login concluído'), findsOneWidget);
    await tester.tap(find.text('Sair'));
    await tester.pumpAndSettle();

    expect(gateway.signOutCalls, 1);
    expect(find.text('Entrar com Google'), findsOneWidget);
  });
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
    _currentUser = const AuthUser(
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
