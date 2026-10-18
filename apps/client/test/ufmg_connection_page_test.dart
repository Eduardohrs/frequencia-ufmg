import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/ufmg_sync_schedule.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';
import 'package:frequencia_ufmg/features/ufmg/ufmg_connection_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';

void main() {
  setUp(() {
    SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty();
  });

  testWidgets('connects without displaying or retaining the password', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: false,
        reauthenticationRequired: false,
      ),
    );
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: logger),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Conectar à UFMG'), findsOneWidget);
    expect(find.textContaining('senha não é armazenada'), findsOneWidget);
    final autofillGroup = tester.widget<AutofillGroup>(
      find.byType(AutofillGroup),
    );
    expect(autofillGroup.onDisposeAction, AutofillContextAction.cancel);
    final usernameField = tester.widget<TextField>(
      find.descendant(
        of: find.byKey(const Key('ufmg-username')),
        matching: find.byType(TextField),
      ),
    );
    final passwordField = tester.widget<TextField>(
      find.descendant(
        of: find.byKey(const Key('ufmg-password')),
        matching: find.byType(TextField),
      ),
    );
    expect(usernameField.autofillHints, const [AutofillHints.username]);
    expect(passwordField.autofillHints, const [AutofillHints.password]);
    expect(passwordField.textInputAction, TextInputAction.done);
    await tester.enterText(
      find.byKey(const Key('ufmg-username')),
      '2025019259',
    );
    await tester.enterText(
      find.byKey(const Key('ufmg-password')),
      'private-password',
    );
    tester.testTextInput.log.clear();
    await tester.tap(find.byKey(const Key('ufmg-connect')));
    await tester.pumpAndSettle();

    expect(gateway.credentials, [('2025019259', 'private-password')]);
    expect(find.text('UFMG conectada'), findsOneWidget);
    expect(find.text('private-password'), findsNothing);
    expect(find.byKey(const Key('ufmg-password')), findsNothing);
    expect(
      tester.testTextInput.log,
      contains(
        isA<MethodCall>()
            .having(
              (call) => call.method,
              'method',
              'TextInput.finishAutofillContext',
            )
            .having((call) => call.arguments, 'shouldSave', isTrue),
      ),
    );
    expect(
      logger.events,
      containsAll([
        'ufmg_session_status_succeeded',
        'ufmg_session_connect_succeeded',
      ]),
    );
    expect(
      logger.parameters,
      anyElement(
        equals({'screen': 'ufmg_connection', 'action': 'ufmg_connect'}),
      ),
    );
    expect(logger.parameters.toString(), isNot(contains('private-password')));
  });

  testWidgets('syncs SIGA while connected and shows the safe summary', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
        createdAt: DateTime.utc(2026, 10, 12, 12),
        expiresAt: DateTime.utc(2026, 10, 12, 21),
      ),
    );
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: logger),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
    await tester.pumpAndSettle();

    expect(gateway.syncCalls, 1);
    expect(
      find.textContaining(
        '2 disciplinas importadas. 3 já estavam cadastradas.',
      ),
      findsOneWidget,
    );
    expect(logger.events, contains('ufmg_sync_succeeded'));
  });

  testWidgets('keeps connection controls available when date listing fails', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..dateListError = StateError('dates unavailable');
    final logger = _Logger();

    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: logger),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('UFMG conectada'), findsOneWidget);
    expect(find.byKey(const Key('ufmg-sync-moodle')), findsOneWidget);
    expect(logger.events, contains('moodle_date_list_failed'));
  });

  testWidgets('syncs courses and schedules and exposes preserved conflicts', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: logger),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
    await tester.pumpAndSettle();

    expect(gateway.syncCalls, 1);
    expect(find.textContaining('2 grades atualizadas'), findsOneWidget);
    expect(find.textContaining('1 conflito preservado'), findsOneWidget);
    expect(find.textContaining('3 já estavam cadastradas'), findsOneWidget);
    expect(logger.events, contains('ufmg_sync_succeeded'));
  });

  testWidgets('imports structured Moodle dates and reports unmatched items', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: logger),
      ),
    );
    await tester.pumpAndSettle();

    final button = find.byKey(const Key('ufmg-sync-moodle'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();

    expect(gateway.dateImportCalls, 1);
    expect(gateway.contentDiscoveryCalls, 1);
    expect(find.textContaining('2 datas do Moodle importadas'), findsOneWidget);
    expect(find.textContaining('1 data atualizada'), findsOneWidget);
    expect(
      find.textContaining('1 data não pôde ser ligada a uma disciplina'),
      findsOneWidget,
    );
    expect(logger.events, contains('moodle_date_import_succeeded'));
    expect(find.text('Trabalho prático'), findsOneWidget);
    expect(logger.events, contains('moodle_date_list_succeeded'));
  });

  testWidgets('shows every Moodle date kind and maps import failures', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          )
          ..dates = [
            PythonMoodleDate(
              id: 'moodle-1',
              courseId: 'dcc203',
              courseCode: 'DCC203',
              title: 'Questionário',
              dueAt: DateTime.utc(2026, 10, 20),
              kind: 'quiz',
            ),
            PythonMoodleDate(
              id: 'moodle-2',
              courseId: 'dcc203',
              courseCode: 'DCC203',
              title: 'Seminário',
              dueAt: DateTime.utc(2026, 10, 21),
              kind: 'event',
            ),
          ];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byIcon(Icons.quiz_outlined), findsOneWidget);
    expect(find.byIcon(Icons.event_outlined), findsOneWidget);

    final cases = <(Object, String)>[
      (
        const PythonBackendException(
          PythonBackendError.ufmgReauthenticationRequired,
        ),
        'Sua sessão expirou. Reconecte para sincronizar o Moodle.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível sincronizar com o Moodle agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível sincronizar os dados do Moodle.',
      ),
      (
        StateError('unexpected'),
        'Não foi possível sincronizar os dados do Moodle.',
      ),
    ];
    for (final (error, message) in cases) {
      gateway.dateImportError = error;
      final button = find.byKey(const Key('ufmg-sync-moodle'));
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(find.text(message), findsOneWidget);
      if (error is PythonBackendException &&
          error.code == PythonBackendError.ufmgReauthenticationRequired) {
        gateway.status = const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        );
        await tester.pumpWidget(
          MaterialApp(
            home: UFMGConnectionPage(
              key: UniqueKey(),
              gateway: gateway,
              logger: _Logger(),
            ),
          ),
        );
        await tester.pumpAndSettle();
      }
    }
  });

  testWidgets('does not update a disposed page after a late Moodle failure', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    gateway.dateImportCompleter = Completer<PythonMoodleDateImportResult>();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    final button = find.byKey(const Key('ufmg-sync-moodle'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    gateway.dateImportCompleter!.completeError(StateError('late'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('runs every ready SIGA stage through one synchronization', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final logger = _Logger();
    final schedule = UFMGSyncSchedule(
      now: () => DateTime.utc(2026, 10, 13, 12),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: logger,
          userId: 'user-1',
          syncSchedule: schedule,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
    await tester.pumpAndSettle();

    expect(gateway.syncCalls, 1);
    expect(find.textContaining('2 disciplinas importadas'), findsOneWidget);
    expect(find.textContaining('2 grades atualizadas'), findsOneWidget);
    expect(find.textContaining('1 conflito preservado'), findsOneWidget);
    expect(logger.events, contains('ufmg_sync_succeeded'));
    expect(await schedule.isDue('user-1'), isFalse);
  });

  testWidgets('presents one focused action for SIGA and one for Moodle', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    await tester.binding.setSurfaceSize(const Size(320, 700));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('ufmg-sync-siga')), findsOneWidget);
    expect(find.text('Disciplinas e horários'), findsOneWidget);
    expect(find.byKey(const Key('ufmg-sync-moodle')), findsOneWidget);
    expect(find.text('Datas, planos de ensino e cronogramas'), findsOneWidget);
    expect(find.byKey(const Key('ufmg-sync')), findsNothing);
    expect(find.byKey(const Key('ufmg-import-courses')), findsNothing);
    expect(find.byKey(const Key('ufmg-import-schedules')), findsNothing);
    expect(find.byKey(const Key('moodle-import-dates')), findsNothing);
    expect(find.byKey(const Key('moodle-discover-content')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('explains synchronization failures and expired sessions', (
    tester,
  ) async {
    final failures = <(Object, String)>[
      (
        const PythonBackendException(
          PythonBackendError.ufmgReauthenticationRequired,
        ),
        'Sua sessão expirou. Reconecte para sincronizar.',
      ),
      (
        const PythonBackendException(PythonBackendError.ufmgUnavailable),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível sincronizar os dados da UFMG.',
      ),
      (StateError('offline'), 'Não foi possível sincronizar os dados da UFMG.'),
    ];

    for (final failure in failures) {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
      )..syncError = failure.$1;
      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
      await tester.pumpAndSettle();

      expect(find.textContaining(failure.$2), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('handles expired and failed SIGA synchronization safely', (
    tester,
  ) async {
    final failures = <(Object, String)>[
      (
        const PythonBackendException(
          PythonBackendError.ufmgReauthenticationRequired,
        ),
        'Sua sessão expirou. Reconecte para sincronizar.',
      ),
      (
        const PythonBackendException(PythonBackendError.ufmgUnavailable),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.timeout),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível sincronizar os dados da UFMG.',
      ),
      (
        StateError('unexpected'),
        'Não foi possível sincronizar os dados da UFMG.',
      ),
    ];
    for (var index = 0; index < failures.length; index++) {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
      )..syncError = failures[index].$1;
      await tester.pumpWidget(
        MaterialApp(
          key: ValueKey('schedule-failure-$index'),
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
      await tester.pumpAndSettle();

      expect(find.text(failures[index].$2), findsOneWidget);
    }
  });

  testWidgets('asks for reconnection when the saved UFMG session expired', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
              createdAt: DateTime.utc(2026, 10, 12, 12),
              expiresAt: DateTime.utc(2026, 10, 12, 21),
            ),
          )
          ..syncError = const PythonBackendException(
            PythonBackendError.ufmgReauthenticationRequired,
          );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
    await tester.pumpAndSettle();

    expect(
      find.text('Sua sessão expirou. Reconecte para sincronizar.'),
      findsOneWidget,
    );
    expect(find.byKey(const Key('ufmg-username')), findsOneWidget);
  });

  testWidgets('explains import outages, throttling, and unexpected failures', (
    tester,
  ) async {
    final failures = <(Object, String)>[
      (
        const PythonBackendException(PythonBackendError.timeout),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível sincronizar com a UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível sincronizar os dados da UFMG.',
      ),
      (
        StateError('unexpected'),
        'Não foi possível sincronizar os dados da UFMG.',
      ),
    ];
    for (var index = 0; index < failures.length; index++) {
      final gateway = _Gateway(
        status: PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
          createdAt: DateTime.utc(2026, 10, 12, 12),
          expiresAt: DateTime.utc(2026, 10, 12, 21),
        ),
      )..syncError = failures[index].$1;
      await tester.pumpWidget(
        MaterialApp(
          key: ValueKey(index),
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-sync-siga')));
      await tester.pumpAndSettle();

      expect(find.text(failures[index].$2), findsOneWidget);
    }
  });

  testWidgets(
    'shows expired state, reconnects, and disconnects after confirmation',
    (tester) async {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: false,
          reauthenticationRequired: true,
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Sua sessão expirou'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('ufmg-username')), 'student');
      await tester.enterText(find.byKey(const Key('ufmg-password')), 'secret');
      await tester.tap(find.byKey(const Key('ufmg-connect')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ufmg-manage-connection')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ufmg-disconnect')));
      await tester.tap(find.byKey(const Key('ufmg-disconnect')));
      await tester.pumpAndSettle();
      expect(find.text('Desconectar da UFMG?'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Desconectar'));
      await tester.pumpAndSettle();

      expect(gateway.disconnectCalls, 1);
      expect(find.text('Conectar à UFMG'), findsOneWidget);
    },
  );

  testWidgets('explains invalid credentials and lets the user retry', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: false,
              reauthenticationRequired: false,
            ),
          )
          ..connectError = const PythonBackendException(
            PythonBackendError.ufmgCredentialsInvalid,
          );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('ufmg-username')), 'student');
    await tester.enterText(find.byKey(const Key('ufmg-password')), 'wrong');
    await tester.tap(find.byKey(const Key('ufmg-connect')));
    await tester.pumpAndSettle();

    expect(find.text('Usuário ou senha da UFMG inválidos.'), findsOneWidget);
    expect(find.byKey(const Key('ufmg-password')), findsOneWidget);
    expect(find.text('wrong'), findsNothing);
  });

  testWidgets(
    'reports status and disconnect failures and supports cancellation',
    (tester) async {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: false,
          reauthenticationRequired: false,
        ),
      )..statusError = StateError('offline');
      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('Não foi possível consultar a conexão com a UFMG.'),
        findsOneWidget,
      );

      gateway.statusError = null;
      gateway.status = PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
        createdAt: DateTime.utc(2026, 10, 12, 12),
        expiresAt: DateTime.utc(2026, 10, 12, 21),
      );
      await tester.pumpWidget(
        MaterialApp(
          key: const Key('connected-app'),
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ufmg-manage-connection')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ufmg-reconnect')));
      await tester.tap(find.byKey(const Key('ufmg-reconnect')));
      await tester.pumpAndSettle();
      expect(find.text('Renovar conexão'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('ufmg-username')),
        'temporary',
      );
      await tester.enterText(
        find.byKey(const Key('ufmg-password')),
        'temporary',
      );
      await tester.tap(find.text('Cancelar'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('ufmg-username')), findsNothing);

      await tester.tap(find.byKey(const Key('ufmg-manage-connection')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ufmg-disconnect')));
      await tester.tap(find.byKey(const Key('ufmg-disconnect')));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'Cancelar'));
      await tester.pumpAndSettle();
      expect(gateway.disconnectCalls, 0);

      gateway.disconnectError = const PythonBackendException(
        PythonBackendError.ufmgUnavailable,
      );
      await tester.ensureVisible(find.byKey(const Key('ufmg-disconnect')));
      await tester.tap(find.byKey(const Key('ufmg-disconnect')));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'Desconectar'));
      await tester.pumpAndSettle();
      expect(
        find.text(
          'A UFMG está indisponível no momento. Tente novamente mais tarde.',
        ),
        findsOneWidget,
      );
    },
  );

  testWidgets('validates the form and maps retryable and generic failures', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: false,
        reauthenticationRequired: false,
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-connect')));
    await tester.pumpAndSettle();
    expect(find.text('Informe seu usuário da UFMG.'), findsOneWidget);
    expect(find.text('Informe sua senha da UFMG.'), findsOneWidget);

    for (final entry in [
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.timeout),
        'A UFMG está indisponível no momento. Tente novamente mais tarde.',
      ),
      (
        StateError('unexpected'),
        'Não foi possível atualizar a conexão com a UFMG.',
      ),
    ]) {
      gateway.connectError = entry.$1;
      await tester.enterText(find.byKey(const Key('ufmg-username')), 'student');
      await tester.enterText(find.byKey(const Key('ufmg-password')), 'secret');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();
      expect(find.text(entry.$2), findsOneWidget);
    }
  });

  testWidgets('discovers and explains Moodle content candidates', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final logger = _Logger();
    final openedUris = <Uri>[];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: logger,
          openExternalUri: (uri) async {
            openedUris.add(uri);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();

    final button = find.byKey(const Key('ufmg-sync-moodle'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();

    expect(gateway.contentDiscoveryCalls, 1);
    expect(
      find.textContaining('3 materiais candidatos encontrados'),
      findsOneWidget,
    );
    expect(find.textContaining('Download direto disponível'), findsOneWidget);
    expect(find.text('3 materiais candidatos'), findsOneWidget);
    expect(
      find.text('Nenhuma publicação candidata encontrada'),
      findsOneWidget,
    );
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    expect(find.text('Plano de ensino'), findsOneWidget);
    expect(find.text('Possível plano de ensino'), findsOneWidget);
    expect(find.text('Possível cronograma'), findsOneWidget);
    expect(find.text('Material da disciplina • Metaturma'), findsOneWidget);
    expect(find.byKey(const Key('moodle-material-open-103')), findsNothing);
    await tester.tap(find.byKey(const Key('moodle-material-open-101')));
    await tester.pumpAndSettle();
    expect(openedUris, [
      Uri.parse('https://virtual.ufmg.br/20262/mod/page/view.php?id=101'),
    ]);
    expect(logger.events, contains('moodle_material_open_succeeded'));
    expect(find.text('Disciplina não localizada no Moodle'), findsOneWidget);
    expect(
      find.text('Mais de uma disciplina correspondente no Moodle'),
      findsOneWidget,
    );
    expect(logger.events, contains('moodle_content_discovery_succeeded'));
    expect(logger.events, contains('moodle_mobile_capability_succeeded'));
  });

  testWidgets('shows the persisted material catalog before a new Moodle sync', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    gateway.materialCatalog = await gateway.discoverMoodleContent();
    gateway.contentDiscoveryCalls = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();

    expect(gateway.materialCatalogCalls, 1);
    expect(gateway.contentDiscoveryCalls, 0);
    expect(find.text('Materiais do Moodle'), findsOneWidget);
    expect(find.byKey(const Key('moodle-content-dcc203')), findsOneWidget);
  });

  testWidgets(
    'keeps Moodle sync useful when capability probing is unavailable',
    (tester) async {
      final gateway =
          _Gateway(
              status: const PythonUFMGSessionStatus(
                connected: true,
                reauthenticationRequired: false,
              ),
            )
            ..capabilityError = const PythonBackendException(
              PythonBackendError.unavailable,
            );
      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
      await tester.pumpAndSettle();

      expect(
        find.textContaining('Não foi possível validar o download direto agora'),
        findsOneWidget,
      );
      expect(
        find.textContaining('3 materiais candidatos encontrados'),
        findsOneWidget,
      );
    },
  );

  testWidgets('downloads Moodle file materials without a browser login', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final openedUris = <Uri>[];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          openExternalUri: (uri) async {
            openedUris.add(uri);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();

    expect(gateway.materialFileRequests, [('2026-2', '3701', '102')]);
    expect(openedUris.single.pathSegments[1], 'tokenpluginfile.php');
  });

  testWidgets('saves and opens an Android private material copy', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final cache = _MaterialCache();
    final logger = _Logger();
    final openedUris = <Uri>[];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: logger,
          materialFileCache: cache,
          openExternalUri: (uri) async {
            openedUris.add(uri);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();

    expect(openedUris, isEmpty);
    expect(cache.saved.single.name, 'Cronograma.pdf');
    expect(find.text('Cronograma.pdf'), findsOneWidget);
    expect(find.text('123 B no dispositivo'), findsOneWidget);
    expect(logger.events, contains('moodle_material_cache_save_succeeded'));

    final cachedOpen = find.widgetWithText(ListTile, 'Cronograma.pdf');
    await tester.ensureVisible(cachedOpen);
    await tester.tap(cachedOpen);
    await tester.pumpAndSettle();
    expect(cache.opened, [cache.files.single.id]);
    expect(logger.events, contains('moodle_material_cache_open_succeeded'));
    final cachedOpenButton = find.byKey(
      Key('cached-material-open-${cache.files.single.id}'),
    );
    await tester.ensureVisible(cachedOpenButton);
    await tester.tap(cachedOpenButton);
    await tester.pumpAndSettle();
    expect(cache.opened, [cache.files.single.id, cache.files.single.id]);
  });

  testWidgets('queues Android material downloads without blocking the page', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final cache = _BackgroundMaterialCache();
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: logger,
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();

    expect(cache.queued.single.name, 'Cronograma.pdf');
    expect(cache.saved, isEmpty);
    expect(find.text('Download iniciado em segundo plano.'), findsOneWidget);
    expect(
      logger.events,
      contains('moodle_material_download_enqueue_succeeded'),
    );
  });

  testWidgets('shows native download queue progress in the app', (
    tester,
  ) async {
    final logger = _Logger();
    final cache = _BackgroundMaterialCache()
      ..progress.addAll([
        const MaterialDownloadProgress(
          id: 'queued-id',
          name: 'Plano offline.pdf',
          state: MaterialDownloadState.failed,
          downloaded: 0,
          total: 100,
          failureCode: 'timeout',
        ),
        const MaterialDownloadProgress(
          id: 'finished-id',
          name: 'Concluído.pdf',
          state: MaterialDownloadState.succeeded,
          downloaded: 100,
          total: 100,
        ),
      ]);
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: logger,
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Plano offline.pdf'), findsOneWidget);
    expect(
      find.text('Falhou: o Moodle demorou para responder'),
      findsOneWidget,
    );
    expect(logger.events, contains('moodle_material_download_failed'));
  });

  testWidgets('downloads every file material from one discipline as a batch', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-download-all-dcc203')));
    await tester.pumpAndSettle();
    expect(find.text('Baixar todos de DCC203?'), findsOneWidget);
    await tester.tap(find.text('Baixar'));
    await tester.pumpAndSettle();

    expect(cache.queued, hasLength(1));
    expect(cache.queued.single.name, 'Cronograma.pdf');
    expect(find.text('1 de 1 materiais preparados'), findsOneWidget);
  });

  testWidgets('enqueues a batch only after every authorization is prepared', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final secondCandidate = PythonMoodleContentCandidate(
      sourceId: '104',
      moodleCourseId: '3701',
      kind: 'file',
      title: 'Exercícios',
      url: Uri.parse(
        'https://virtual.ufmg.br/20262/mod/resource/view.php?id=104',
      ),
      relevance: 'other',
      origin: PythonMoodleContentOrigin.canonical,
    );
    final original = await gateway.discoverMoodleContent();
    final course = original.courses.first;
    gateway.materialCatalog = PythonMoodleContentDiscovery(
      candidateTotal: original.candidateTotal + 1,
      metaturmaCandidateTotal: original.metaturmaCandidateTotal,
      courses: [
        PythonMoodleCourseContent(
          courseId: course.courseId,
          courseCode: course.courseCode,
          term: course.term,
          moodleCourseId: course.moodleCourseId,
          status: course.status,
          candidates: [...course.candidates, secondCandidate],
        ),
        ...original.courses.skip(1),
      ],
    );
    gateway.materialFileCompleters['102'] = Completer();
    gateway.materialFileCompleters['104'] = Completer();
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    final downloadAll = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(downloadAll);
    await tester.tap(downloadAll);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Baixar'));
    await tester.pump();

    gateway.materialFileCompleters['102']!.complete([
      _materialFile('Cronograma.pdf', 123),
    ]);
    await tester.pump();
    expect(cache.queued, isEmpty);

    gateway.materialFileCompleters['104']!.complete([
      _materialFile('Exercicios.pdf', 456),
    ]);
    await tester.pumpAndSettle();
    expect(cache.queued.map((item) => item.name), [
      'Cronograma.pdf',
      'Exercicios.pdf',
    ]);
  });

  testWidgets('offers one global batch action for Moodle file materials', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();

    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    expect(find.text('Baixar todos os materiais?'), findsOneWidget);
    await tester.tap(find.text('Baixar'));
    await tester.pumpAndSettle();

    expect(cache.queued, hasLength(1));
    expect(find.text('1 de 1 materiais preparados'), findsOneWidget);
  });

  testWidgets('deduplicates a repeated material batch', (tester) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();

    for (var attempt = 0; attempt < 2; attempt++) {
      final global = find.byKey(const Key('moodle-download-all'));
      await tester.ensureVisible(global);
      await tester.tap(global);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Baixar'));
      await tester.pumpAndSettle();
    }

    expect(cache.queued, hasLength(1));
  });

  testWidgets('retries only failed batch materials', (tester) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..materialFileFailuresRemaining = 1;
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Baixar'));
    await tester.pumpAndSettle();

    expect(find.text('0 de 1 materiais preparados'), findsOneWidget);
    await tester.tap(find.byKey(const Key('moodle-download-retry-failed')));
    await tester.pumpAndSettle();

    expect(cache.queued, hasLength(1));
    expect(find.text('1 de 1 materiais preparados'), findsOneWidget);
    expect(gateway.materialFileRequests, hasLength(2));
  });

  testWidgets('cancels a material batch without enqueueing files', (
    tester,
  ) async {
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    expect(cache.queued, isEmpty);
  });

  testWidgets('stores a material batch in a synchronous local cache', (
    tester,
  ) async {
    final cache = _MaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Baixar'));
    await tester.pumpAndSettle();

    expect(cache.saved, hasLength(1));
    expect(find.text('Cronograma.pdf'), findsOneWidget);
  });

  testWidgets('releases deduplication after queue and cache failures', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    final queue = _BackgroundMaterialCache()
      ..enqueueError = StateError('queue');
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: queue,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    final download = find.byKey(const Key('moodle-material-open-102'));
    await tester.tap(download);
    await tester.pumpAndSettle();
    queue.enqueueError = null;
    await tester.tap(download);
    await tester.pumpAndSettle();
    expect(queue.enqueueAttempts, 2);
    expect(queue.queued, hasLength(1));

    await tester.pumpWidget(const SizedBox());
    await tester.pumpAndSettle();
    final local = _MaterialCache()..saveError = StateError('disk');
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: local,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    final localDownload = find.byKey(const Key('moodle-material-open-102'));
    await tester.ensureVisible(localDownload);
    await tester.tap(localDownload);
    await tester.pumpAndSettle();
    local.saveError = null;
    await tester.tap(localDownload);
    await tester.pumpAndSettle();
    expect(local.saveAttempts, 2);
    expect(local.saved, hasLength(1));
  });

  testWidgets('reports one batch failure when multiple files cannot enqueue', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          )
          ..materialFiles = [
            _materialFile('One.pdf', 10),
            _materialFile('Two.pdf', 20),
          ];
    final queue = _BackgroundMaterialCache()
      ..enqueueError = StateError('queue');
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: queue,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Baixar'));
    await tester.pumpAndSettle();

    expect(queue.enqueueAttempts, 2);
    expect(find.text('Tentar novamente (1)'), findsOneWidget);
  });

  testWidgets('retries a failed native download from its catalog identity', (
    tester,
  ) async {
    final cache = _BackgroundMaterialCache()
      ..progress.add(
        const MaterialDownloadProgress(
          id: '2026-2/3701/102/Cronograma.pdf',
          name: 'Cronograma.pdf',
          state: MaterialDownloadState.failed,
          downloaded: 0,
          total: 123,
        ),
      );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final retry = find.byKey(
      const Key('material-download-retry-2026-2/3701/102/Cronograma.pdf'),
    );
    await tester.ensureVisible(retry);
    await tester.tap(retry);
    await tester.pump(const Duration(seconds: 2));

    expect(cache.queued, hasLength(1));
  });

  testWidgets('reports a failed native retry when the file disappeared', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..materialFiles = [_materialFile('Outro.pdf', 20)];
    final cache = _BackgroundMaterialCache()
      ..progress.add(
        const MaterialDownloadProgress(
          id: '2026-2/3701/102/Cronograma.pdf',
          name: 'Cronograma.pdf',
          state: MaterialDownloadState.failed,
          downloaded: 0,
          total: 123,
        ),
      );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final retry = find.byKey(
      const Key('material-download-retry-2026-2/3701/102/Cronograma.pdf'),
    );
    await tester.ensureVisible(retry);
    await tester.tap(retry);
    await tester.pumpAndSettle();

    expect(find.text('Não foi possível repetir o download.'), findsOneWidget);
  });

  testWidgets('shows non-blocking preparation progress during a batch', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..materialFilesCompleter = Completer<List<PythonMoodleMaterialFile>>();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: _BackgroundMaterialCache(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    final global = find.byKey(const Key('moodle-download-all'));
    await tester.ensureVisible(global);
    await tester.tap(global);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Baixar'));
    await tester.pump();

    expect(find.text('0 de 1 materiais processados'), findsOneWidget);
    gateway.materialFilesCompleter!.complete([
      _materialFile('Cronograma.pdf', 123),
    ]);
    await tester.pumpAndSettle();
  });

  testWidgets('ignores repeated taps while a material download is resolving', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..materialFilesCompleter = Completer<List<PythonMoodleMaterialFile>>();
    final cache = _BackgroundMaterialCache();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    final download = find.byKey(const Key('moodle-material-open-102'));
    await tester.tap(download);
    await tester.tap(download);
    await tester.pump();

    expect(gateway.materialFileRequests, [('2026-2', '3701', '102')]);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    gateway.materialFilesCompleter!.complete([
      _materialFile('Cronograma.pdf', 123),
    ]);
    await tester.pumpAndSettle();
    expect(cache.queued, hasLength(1));
  });

  testWidgets('removes one or every private material copy', (tester) async {
    final cache = _MaterialCache()
      ..files.addAll(const [
        CachedMaterialFile(
          id: 'one',
          name: 'Plano.pdf',
          size: 2048,
          mimeType: 'application/pdf',
        ),
        CachedMaterialFile(
          id: 'two',
          name: 'Notas.txt',
          size: 512,
          mimeType: 'text/plain',
        ),
      ]);
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: false,
              reauthenticationRequired: true,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('2.5 KB no dispositivo'), findsOneWidget);
    await tester.ensureVisible(
      find.byKey(const Key('cached-material-remove-one')),
    );
    await tester.tap(find.byKey(const Key('cached-material-remove-one')));
    await tester.pumpAndSettle();
    expect(cache.removed, ['one']);
    expect(find.text('Plano.pdf'), findsNothing);

    await tester.ensureVisible(find.byKey(const Key('cached-material-clear')));
    await tester.tap(find.byKey(const Key('cached-material-clear')));
    await tester.pumpAndSettle();
    expect(find.text('Remover todas as cópias?'), findsOneWidget);
    await tester.tap(find.text('Remover todas'));
    await tester.pumpAndSettle();
    expect(cache.clearCalls, 1);
    expect(find.text('Arquivos neste dispositivo'), findsOneWidget);
    expect(find.text('Nenhuma cópia offline'), findsOneWidget);
  });

  testWidgets('downloads to the local cache without a duplicate action sheet', (
    tester,
  ) async {
    final cache = _MaterialCache();
    final openedUris = <Uri>[];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
          openExternalUri: (uri) async {
            openedUris.add(uri);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();

    expect(find.text('O que deseja fazer?'), findsNothing);
    expect(openedUris, isEmpty);
    expect(cache.saved, hasLength(1));
    expect(cache.saved.single.name, 'Cronograma.pdf');
  });

  testWidgets('keeps cache failures non-blocking and observable', (
    tester,
  ) async {
    final cache = _MaterialCache()
      ..files.add(
        const CachedMaterialFile(
          id: 'one',
          name: 'Plano.pdf',
          size: 10,
          mimeType: 'application/pdf',
        ),
      )
      ..openError = StateError('open')
      ..removeError = StateError('remove')
      ..clearError = StateError('clear');
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: false,
              reauthenticationRequired: true,
            ),
          ),
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();

    final fileTile = find.widgetWithText(ListTile, 'Plano.pdf');
    await tester.ensureVisible(fileTile);
    await tester.tap(fileTile);
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível abrir a cópia offline.'),
      findsOneWidget,
    );
    await tester.pump(const Duration(seconds: 5));

    final remove = find.byKey(const Key('cached-material-remove-one'));
    await tester.ensureVisible(remove);
    await tester.tap(remove);
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível remover a cópia offline.'),
      findsOneWidget,
    );
    await tester.pump(const Duration(seconds: 5));

    await tester.ensureVisible(find.byKey(const Key('cached-material-clear')));
    await tester.tap(find.byKey(const Key('cached-material-clear')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(cache.clearCalls, 0);

    await tester.tap(find.byKey(const Key('cached-material-clear')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Remover todas'));
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível limpar as cópias offline.'),
      findsOneWidget,
    );
  });

  testWidgets('hides a failed private cache without blocking UFMG', (
    tester,
  ) async {
    final cache = _MaterialCache()..listError = StateError('disk');
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: false,
              reauthenticationRequired: false,
            ),
          ),
          logger: logger,
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Conectar à UFMG'), findsOneWidget);
    expect(logger.events, contains('moodle_material_cache_list_failed'));
  });

  testWidgets('keeps offline copies usable while the UFMG check is pending', (
    tester,
  ) async {
    final statusCompleter = Completer<PythonUFMGSessionStatus>();
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: false,
        reauthenticationRequired: false,
      ),
    )..statusCompleter = statusCompleter;
    final cache = _MaterialCache()
      ..files.add(
        const CachedMaterialFile(
          id: 'offline',
          name: 'Offline.pdf',
          size: 50,
          mimeType: 'application/pdf',
        ),
      );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: cache,
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Conferindo a conexão com a UFMG…'), findsOneWidget);
    expect(find.text('Offline.pdf'), findsOneWidget);
    await tester.tap(find.widgetWithText(ListTile, 'Offline.pdf'));
    await tester.pump();
    expect(cache.opened, ['offline']);

    statusCompleter.complete(gateway.status);
    await tester.pumpAndSettle();
  });

  testWidgets('lets the student choose among multiple Moodle files', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          )
          ..materialFiles = [
            _materialFile('Resumo.txt', 500),
            _materialFile('Plano.pdf', 2048),
            _materialFile('Apostila.pdf', 2 * 1024 * 1024),
          ];
    final openedUris = <Uri>[];
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: gateway,
          logger: _Logger(),
          materialFileCache: const DisabledMaterialFileCache(),
          openExternalUri: (uri) async {
            openedUris.add(uri);
            return true;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pump(const Duration(milliseconds: 500));
    expect(find.text('Escolha um arquivo'), findsOneWidget);
    expect(find.text('500 B'), findsOneWidget);
    expect(find.text('2.0 KB'), findsOneWidget);
    expect(find.text('2.0 MB'), findsOneWidget);
    final choice = tester.widget<ListTile>(
      find.widgetWithText(ListTile, 'Plano.pdf'),
    );
    choice.onTap!();
    await tester.pumpAndSettle();

    expect(openedUris.single.path, contains('plano.pdf'));
  });

  testWidgets('explains missing and expired Moodle download authorization', (
    tester,
  ) async {
    final gateway =
        _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          )
          ..materialFilesError = const PythonBackendException(
            PythonBackendError.moodleAuthorizationRequired,
          );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();
    expect(
      find.text('Sincronize o Moodle novamente para baixar este material.'),
      findsOneWidget,
    );
    await tester.pump(const Duration(seconds: 5));

    gateway
      ..materialFilesError = null
      ..materialFiles = [];
    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível abrir este material no Moodle.'),
      findsOneWidget,
    );
  });

  testWidgets('does not launch a late Moodle file response after disposal', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..materialFilesCompleter = Completer<List<PythonMoodleMaterialFile>>();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('moodle-material-open-102')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    gateway.materialFilesCompleter!.complete([
      _materialFile('Primeiro.pdf', 1),
      _materialFile('Segundo.pdf', 2),
    ]);
    await tester.pumpAndSettle();
    expect(find.byType(UFMGConnectionPage), findsNothing);
  });

  testWidgets(
    'uses the material course identity instead of the canonical one',
    (tester) async {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
      )..foundMoodleCourseId = null;
      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(
            gateway: gateway,
            logger: _Logger(),
            materialFileCache: const DisabledMaterialFileCache(),
            openExternalUri: (_) async => true,
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('moodle-content-dcc203')),
      );
      await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('moodle-material-open-102')));
      await tester.pumpAndSettle();
      expect(gateway.materialFileRequests, [('2026-2', '3701', '102')]);
    },
  );

  testWidgets('explains when Moodle refuses to open a material', (
    tester,
  ) async {
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: logger,
          openExternalUri: (_) async => false,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-101')));
    await tester.pumpAndSettle();

    expect(
      find.text('Não foi possível abrir este material no Moodle.'),
      findsOneWidget,
    );
    expect(logger.events, contains('moodle_material_open_failed'));
  });

  testWidgets('uses the platform launcher for Moodle materials by default', (
    tester,
  ) async {
    const launcherChannel = MethodChannel('plugins.flutter.io/url_launcher');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(launcherChannel, (_) async => true);
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(launcherChannel, null),
    );
    final logger = _Logger();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(
          gateway: _Gateway(
            status: const PythonUFMGSessionStatus(
              connected: true,
              reauthenticationRequired: false,
            ),
          ),
          logger: logger,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('moodle-content-dcc203')));
    await tester.tap(find.byKey(const Key('moodle-content-dcc203')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('moodle-material-open-101')));
    await tester.pumpAndSettle();

    expect(logger.events, contains('moodle_material_open_succeeded'));
  });

  testWidgets('handles content discovery failure and expired session', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    gateway.contentDiscoveryError = StateError('failed');
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível sincronizar os dados do Moodle.'),
      findsOneWidget,
    );

    gateway.contentDiscoveryError = const PythonBackendException(
      PythonBackendError.ufmgReauthenticationRequired,
    );
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pumpAndSettle();
    expect(
      find.text('Sua sessão expirou. Reconecte para sincronizar o Moodle.'),
      findsOneWidget,
    );
  });

  testWidgets(
    'retries discovery safely when its first response is interrupted',
    (tester) async {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
      );
      gateway.materialCatalog = await gateway.discoverMoodleContent();
      gateway.contentDiscoveryCalls = 0;
      gateway.transientContentDiscoveryFailures = 1;
      final logger = _Logger();

      await tester.pumpWidget(
        MaterialApp(
          home: UFMGConnectionPage(gateway: gateway, logger: logger),
        ),
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
      await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
      await tester.pumpAndSettle();

      expect(gateway.contentDiscoveryCalls, 2);
      expect(gateway.materialCatalogCalls, 2);
      expect(
        find.textContaining('3 materiais candidatos encontrados'),
        findsOneWidget,
      );
      expect(
        find.text('Não foi possível sincronizar os dados do Moodle.'),
        findsNothing,
      );
      expect(logger.events, contains('moodle_content_discovery_retrying'));
      expect(logger.events, contains('moodle_content_discovery_recovered'));
    },
  );

  testWidgets('ignores a late content discovery failure after disposal', (
    tester,
  ) async {
    final gateway = _Gateway(
      status: const PythonUFMGSessionStatus(
        connected: true,
        reauthenticationRequired: false,
      ),
    )..contentDiscoveryCompleter = Completer<PythonMoodleContentDiscovery>();
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.tap(find.byKey(const Key('ufmg-sync-moodle')));
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    gateway.contentDiscoveryCompleter!.completeError(StateError('late'));
    await tester.pumpAndSettle();
    expect(find.byType(UFMGConnectionPage), findsNothing);
  });
}

PythonMoodleMaterialFile _materialFile(String name, int size) =>
    PythonMoodleMaterialFile(
      name: name,
      url: Uri.parse(
        'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
        'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/${name.toLowerCase()}'
        '?forcedownload=1',
      ),
      size: size,
      mimeType: 'application/pdf',
    );

final class _Gateway implements BackendUFMGSessionGateway {
  _Gateway({required this.status});

  PythonUFMGSessionStatus status;
  Object? connectError;
  Object? statusError;
  Completer<PythonUFMGSessionStatus>? statusCompleter;
  Object? disconnectError;
  Object? importError;
  Object? scheduleImportError;
  Object? dateImportError;
  Object? dateListError;
  Completer<PythonMoodleDateImportResult>? dateImportCompleter;
  Object? syncError;
  Object? contentDiscoveryError;
  int transientContentDiscoveryFailures = 0;
  Object? capabilityError;
  Object? materialFilesError;
  int materialFileFailuresRemaining = 0;
  List<PythonMoodleMaterialFile>? materialFiles;
  Completer<List<PythonMoodleMaterialFile>>? materialFilesCompleter;
  final materialFileCompleters =
      <String, Completer<List<PythonMoodleMaterialFile>>>{};
  String? foundMoodleCourseId = '3701';
  Completer<PythonMoodleContentDiscovery>? contentDiscoveryCompleter;
  final credentials = <(String, String)>[];
  int disconnectCalls = 0;
  int importCalls = 0;
  int scheduleImportCalls = 0;
  int dateImportCalls = 0;
  List<PythonMoodleDate> dates = const [];
  int syncCalls = 0;
  int contentDiscoveryCalls = 0;
  int materialCatalogCalls = 0;
  final materialFileRequests = <(String, String, String)>[];
  PythonMoodleContentDiscovery materialCatalog =
      const PythonMoodleContentDiscovery(
        courses: [],
        candidateTotal: 0,
        metaturmaCandidateTotal: 0,
      );

  @override
  Future<PythonMoodleContentDiscovery> listMoodleMaterialCatalog() async {
    materialCatalogCalls++;
    return materialCatalog;
  }

  @override
  Future<PythonMoodleMobileCapabilities> probeMoodleMobileCapabilities() async {
    if (capabilityError case final error?) throw error;
    return const PythonMoodleMobileCapabilities(
      term: '2026-2',
      directDownloadSupported: true,
      downloadFiles: true,
      privateFileAccess: true,
      webserviceTokenIssued: true,
    );
  }

  @override
  Future<List<PythonMoodleMaterialFile>> listMoodleMaterialFiles({
    required String term,
    required String courseId,
    required String sourceId,
  }) async {
    materialFileRequests.add((term, courseId, sourceId));
    if (materialFileCompleters[sourceId] case final completer?) {
      return completer.future;
    }
    if (materialFilesCompleter case final completer?) return completer.future;
    if (materialFileFailuresRemaining > 0) {
      materialFileFailuresRemaining--;
      throw const PythonBackendException(PythonBackendError.unavailable);
    }
    if (materialFilesError case final error?) throw error;
    return materialFiles ??
        [
          PythonMoodleMaterialFile(
            name: 'Cronograma.pdf',
            url: Uri.parse(
              'https://virtual.ufmg.br/20262/tokenpluginfile.php/'
              'aaaaaaaaaaaaaaaa/700/mod_resource/content/1/cronograma.pdf'
              '?forcedownload=1',
            ),
            size: 123,
            mimeType: 'application/pdf',
          ),
        ];
  }

  @override
  Future<PythonMoodleContentDiscovery> discoverMoodleContent() async {
    contentDiscoveryCalls++;
    if (contentDiscoveryCompleter case final completer?) {
      return completer.future;
    }
    if (transientContentDiscoveryFailures > 0) {
      transientContentDiscoveryFailures--;
      throw const PythonBackendException(PythonBackendError.unavailable);
    }
    if (contentDiscoveryError case final error?) throw error;
    final discovery = PythonMoodleContentDiscovery(
      candidateTotal: 3,
      metaturmaCandidateTotal: 1,
      courses: [
        PythonMoodleCourseContent(
          courseId: 'dcc203',
          courseCode: 'DCC203',
          term: '2026-2',
          moodleCourseId: foundMoodleCourseId,
          status: PythonMoodleContentStatus.found,
          candidates: [
            PythonMoodleContentCandidate(
              sourceId: '101',
              moodleCourseId: '3701',
              kind: 'page',
              title: 'Plano de ensino',
              url: Uri.parse(
                'https://virtual.ufmg.br/20262/mod/page/view.php?id=101',
              ),
              relevance: 'teaching_plan',
              origin: PythonMoodleContentOrigin.canonical,
            ),
            PythonMoodleContentCandidate(
              sourceId: '102',
              moodleCourseId: '3701',
              kind: 'file',
              title: 'Cronograma',
              url: Uri.parse(
                'https://virtual.ufmg.br/20262/mod/resource/view.php?id=102',
              ),
              relevance: 'schedule',
              origin: PythonMoodleContentOrigin.canonical,
            ),
            PythonMoodleContentCandidate(
              sourceId: '103',
              moodleCourseId: '4999',
              kind: 'text',
              title: 'Avisos',
              url: null,
              relevance: 'other',
              origin: PythonMoodleContentOrigin.metaturma,
            ),
          ],
        ),
        PythonMoodleCourseContent(
          courseId: 'mat001',
          courseCode: 'MAT001',
          term: '2026-2',
          moodleCourseId: '4953',
          status: PythonMoodleContentStatus.empty,
          candidates: [],
        ),
        PythonMoodleCourseContent(
          courseId: 'ele028',
          courseCode: 'ELE028',
          term: '2026-2',
          moodleCourseId: null,
          status: PythonMoodleContentStatus.unmatched,
          candidates: [],
        ),
        PythonMoodleCourseContent(
          courseId: 'amb001',
          courseCode: 'AMB001',
          term: '2026-2',
          moodleCourseId: null,
          status: PythonMoodleContentStatus.ambiguous,
          candidates: [],
        ),
      ],
    );
    materialCatalog = discovery;
    return discovery;
  }

  @override
  Future<PythonUFMGCourseImportResult> importUFMGCourses() async {
    importCalls++;
    if (importError case final error?) throw error;
    return const PythonUFMGCourseImportResult(
      created: 2,
      existing: 3,
      total: 5,
    );
  }

  @override
  Future<PythonUFMGScheduleImportResult> importUFMGSchedules() async {
    scheduleImportCalls++;
    if (scheduleImportError case final error?) throw error;
    return const PythonUFMGScheduleImportResult(
      total: 5,
      updated: 2,
      unchanged: 1,
      conflicts: 1,
      missingCourses: 1,
      meetingsImported: 3,
    );
  }

  @override
  Future<PythonMoodleDateImportResult> importMoodleDates() async {
    dateImportCalls++;
    if (dateImportCompleter case final completer?) return completer.future;
    if (dateImportError case final error?) throw error;
    dates = [
      PythonMoodleDate(
        id: 'moodle-910',
        courseId: 'dcc203',
        courseCode: 'DCC203',
        title: 'Trabalho prático',
        dueAt: DateTime.utc(2026, 10, 22, 23),
        kind: 'assignment',
      ),
    ];
    return const PythonMoodleDateImportResult(
      total: 4,
      matched: 3,
      unmatched: 1,
      created: 2,
      updated: 1,
      unchanged: 0,
    );
  }

  @override
  Future<List<PythonMoodleDate>> listMoodleDates() async {
    if (dateListError case final error?) throw error;
    return dates;
  }

  @override
  Future<PythonUFMGSigaSyncResult> syncSiga() async {
    syncCalls++;
    if (syncError case final error?) throw error;
    return PythonUFMGSigaSyncResult(
      courses: const PythonUFMGCourseImportResult(
        created: 2,
        existing: 3,
        total: 5,
      ),
      schedules: const PythonUFMGScheduleImportResult(
        total: 5,
        updated: 2,
        unchanged: 2,
        conflicts: 1,
        missingCourses: 0,
        meetingsImported: 3,
      ),
      checkedAt: DateTime.utc(2026, 10, 13, 12),
      nextAutomaticSyncAt: DateTime.utc(2026, 12, 6),
    );
  }

  @override
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus() async {
    if (statusCompleter case final completer?) return completer.future;
    if (statusError case final error?) throw error;
    return status;
  }

  @override
  Future<PythonUFMGSessionStatus> connectUFMG({
    required String username,
    required String password,
  }) async {
    credentials.add((username, password));
    if (connectError case final error?) throw error;
    return status = PythonUFMGSessionStatus(
      connected: true,
      reauthenticationRequired: false,
      createdAt: DateTime.utc(2026, 10, 12, 12),
      expiresAt: DateTime.utc(2026, 10, 12, 21),
    );
  }

  @override
  Future<PythonUFMGSessionStatus> disconnectUFMG() async {
    disconnectCalls++;
    if (disconnectError case final error?) throw error;
    return status = const PythonUFMGSessionStatus(
      connected: false,
      reauthenticationRequired: false,
    );
  }
}

final class _Logger implements AppLogger {
  final events = <String>[];
  final parameters = <Map<String, Object>?>[];

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
    this.parameters.add(parameters);
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {}
}

class _MaterialCache implements MaterialFileCache {
  final files = <CachedMaterialFile>[];
  final saved = <MaterialDownload>[];
  final opened = <String>[];
  final removed = <String>[];
  int clearCalls = 0;
  bool disposed = false;
  Object? listError;
  Object? openError;
  Object? removeError;
  Object? clearError;
  Object? saveError;
  int saveAttempts = 0;

  @override
  bool get isAvailable => true;

  @override
  Future<List<CachedMaterialFile>> list() async {
    if (listError case final error?) throw error;
    return List.of(files);
  }

  @override
  Future<CachedMaterialFile> save(MaterialDownload download) async {
    saveAttempts++;
    if (saveError case final error?) throw error;
    saved.add(download);
    final file = CachedMaterialFile(
      id: download.id,
      name: download.name,
      size: download.expectedSize,
      mimeType: download.mimeType,
    );
    files
      ..removeWhere((existing) => existing.id == file.id)
      ..add(file);
    return file;
  }

  @override
  Future<void> open(String id) async {
    if (openError case final error?) throw error;
    opened.add(id);
  }

  @override
  Future<void> remove(String id) async {
    if (removeError case final error?) throw error;
    removed.add(id);
    files.removeWhere((file) => file.id == id);
  }

  @override
  Future<void> clear() async {
    clearCalls++;
    if (clearError case final error?) throw error;
    files.clear();
  }

  @override
  void dispose() => disposed = true;
}

final class _BackgroundMaterialCache extends _MaterialCache
    implements BackgroundMaterialDownloadQueue {
  final queued = <MaterialDownload>[];
  final progress = <MaterialDownloadProgress>[];
  Object? enqueueError;
  int enqueueAttempts = 0;

  @override
  Future<List<MaterialDownloadProgress>> listDownloads() async => progress;

  @override
  Future<void> enqueue(MaterialDownload download) async {
    enqueueAttempts++;
    if (enqueueError case final error?) throw error;
    queued.add(download);
  }
}
