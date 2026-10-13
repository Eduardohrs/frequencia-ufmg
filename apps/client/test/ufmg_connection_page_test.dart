import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/ufmg_sync_schedule.dart';
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
    await tester.enterText(
      find.byKey(const Key('ufmg-username')),
      '2025019259',
    );
    await tester.enterText(
      find.byKey(const Key('ufmg-password')),
      'private-password',
    );
    await tester.tap(find.byKey(const Key('ufmg-connect')));
    await tester.pumpAndSettle();

    expect(gateway.credentials, [('2025019259', 'private-password')]);
    expect(find.text('UFMG conectada'), findsOneWidget);
    expect(find.text('private-password'), findsNothing);
    expect(find.byKey(const Key('ufmg-password')), findsNothing);
    expect(
      logger.events,
      containsAll([
        'ufmg_session_status_succeeded',
        'ufmg_session_connect_succeeded',
      ]),
    );
  });

  testWidgets('imports courses while connected and shows the safe summary', (
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

    await tester.tap(find.byKey(const Key('ufmg-import-courses')));
    await tester.pumpAndSettle();

    expect(gateway.importCalls, 1);
    expect(
      find.text('2 disciplinas importadas. 3 já estavam cadastradas.'),
      findsOneWidget,
    );
    expect(logger.events, contains('ufmg_course_import_succeeded'));
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
    expect(find.byKey(const Key('moodle-import-dates')), findsOneWidget);
    expect(logger.events, contains('moodle_date_list_failed'));
  });

  testWidgets('imports schedules and exposes preserved conflicts', (
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

    await tester.tap(find.byKey(const Key('ufmg-import-schedules')));
    await tester.pumpAndSettle();

    expect(gateway.scheduleImportCalls, 1);
    expect(find.textContaining('2 grades atualizadas'), findsOneWidget);
    expect(find.textContaining('1 conflito preservado'), findsOneWidget);
    expect(
      find.textContaining('1 disciplina ainda não cadastrada'),
      findsOneWidget,
    );
    expect(logger.events, contains('ufmg_schedule_import_succeeded'));
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

    final button = find.byKey(const Key('moodle-import-dates'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();

    expect(gateway.dateImportCalls, 1);
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
        'Sua sessão expirou. Reconecte para importar.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível consultar as datas no Moodle agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível importar as datas do Moodle.',
      ),
      (
        StateError('unexpected'),
        'Não foi possível importar as datas do Moodle.',
      ),
    ];
    for (final (error, message) in cases) {
      gateway.dateImportError = error;
      final button = find.byKey(const Key('moodle-import-dates'));
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
    final button = find.byKey(const Key('moodle-import-dates'));
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pump();
    await tester.pumpWidget(const SizedBox());
    gateway.dateImportCompleter!.completeError(StateError('late'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('runs every ready import stage through one synchronization', (
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

    await tester.tap(find.byKey(const Key('ufmg-sync')));
    await tester.pumpAndSettle();

    expect(gateway.syncCalls, 1);
    expect(find.textContaining('2 disciplinas importadas'), findsOneWidget);
    expect(find.textContaining('2 grades atualizadas'), findsOneWidget);
    expect(find.textContaining('1 conflito preservado'), findsOneWidget);
    expect(find.textContaining('2 datas do Moodle importadas'), findsOneWidget);
    expect(
      find.textContaining('1 data sem disciplina correspondente'),
      findsOneWidget,
    );
    expect(logger.events, contains('ufmg_sync_succeeded'));
    expect(await schedule.isDue('user-1'), isFalse);
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

      await tester.tap(find.byKey(const Key('ufmg-sync')));
      await tester.pumpAndSettle();

      expect(find.textContaining(failure.$2), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    }
  });

  testWidgets('handles expired and failed schedule imports safely', (
    tester,
  ) async {
    final failures = <(Object, String)>[
      (
        const PythonBackendException(
          PythonBackendError.ufmgReauthenticationRequired,
        ),
        'Sua sessão expirou. Reconecte para importar.',
      ),
      (
        const PythonBackendException(PythonBackendError.ufmgUnavailable),
        'Não foi possível consultar os horários na UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível consultar os horários na UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.timeout),
        'Não foi possível consultar os horários na UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível importar os horários.',
      ),
      (StateError('unexpected'), 'Não foi possível importar os horários.'),
    ];
    for (var index = 0; index < failures.length; index++) {
      final gateway = _Gateway(
        status: const PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
        ),
      )..scheduleImportError = failures[index].$1;
      await tester.pumpWidget(
        MaterialApp(
          key: ValueKey('schedule-failure-$index'),
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-import-schedules')));
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
          ..importError = const PythonBackendException(
            PythonBackendError.ufmgReauthenticationRequired,
          );
    await tester.pumpWidget(
      MaterialApp(
        home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('ufmg-import-courses')));
    await tester.pumpAndSettle();

    expect(
      find.text('Sua sessão expirou. Reconecte para importar.'),
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
        'Não foi possível consultar as matrículas na UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.unavailable),
        'Não foi possível consultar as matrículas na UFMG agora.',
      ),
      (
        const PythonBackendException(PythonBackendError.rateLimited),
        'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
      ),
      (
        const PythonBackendException(PythonBackendError.invalidResponse),
        'Não foi possível importar as disciplinas.',
      ),
      (StateError('unexpected'), 'Não foi possível importar as disciplinas.'),
    ];
    for (var index = 0; index < failures.length; index++) {
      final gateway = _Gateway(
        status: PythonUFMGSessionStatus(
          connected: true,
          reauthenticationRequired: false,
          createdAt: DateTime.utc(2026, 10, 12, 12),
          expiresAt: DateTime.utc(2026, 10, 12, 21),
        ),
      )..importError = failures[index].$1;
      await tester.pumpWidget(
        MaterialApp(
          key: ValueKey(index),
          home: UFMGConnectionPage(gateway: gateway, logger: _Logger()),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('ufmg-import-courses')));
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
}

final class _Gateway implements BackendUFMGSessionGateway {
  _Gateway({required this.status});

  PythonUFMGSessionStatus status;
  Object? connectError;
  Object? statusError;
  Object? disconnectError;
  Object? importError;
  Object? scheduleImportError;
  Object? dateImportError;
  Object? dateListError;
  Completer<PythonMoodleDateImportResult>? dateImportCompleter;
  Object? syncError;
  final credentials = <(String, String)>[];
  int disconnectCalls = 0;
  int importCalls = 0;
  int scheduleImportCalls = 0;
  int dateImportCalls = 0;
  List<PythonMoodleDate> dates = const [];
  int syncCalls = 0;

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
  Future<PythonUFMGSyncResult> syncUFMG() async {
    syncCalls++;
    if (syncError case final error?) throw error;
    return PythonUFMGSyncResult(
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
      dates: const PythonMoodleDateImportResult(
        total: 4,
        matched: 3,
        unmatched: 1,
        created: 2,
        updated: 1,
        unchanged: 0,
      ),
      checkedAt: DateTime.utc(2026, 10, 13, 12),
      nextAutomaticSyncAt: DateTime.utc(2026, 12, 6),
    );
  }

  @override
  Future<PythonUFMGSessionStatus> getUFMGSessionStatus() async {
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

  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    events.add(name);
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
