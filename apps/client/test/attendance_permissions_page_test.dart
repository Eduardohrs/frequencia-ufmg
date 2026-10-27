import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/features/attendance/attendance_permissions_page.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'fixtures/attendance_permission_fixture.dart';

void main() {
  Future<void> show(WidgetTester tester, _Gateway gateway, _Logger logger) =>
      tester.pumpWidget(
        MaterialApp(
          home: AttendancePermissionsPage(gateway: gateway, logger: logger),
        ),
      );

  testWidgets(
    'inspects without requesting permissions and logs the actual flags',
    (tester) async {
      final gateway = _Gateway();
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pumpAndSettle();
      expect(find.text('Acesso à localização pronto'), findsOneWidget);
      expect(gateway.actions, isEmpty);
      final event = logger.events.singleWhere(
        (e) => e.$1 == 'attendance_permission_status',
      );
      expect(event.$2, containsPair('background_location', true));
      expect(event.$2, containsPair('battery_unrestricted', false));
      expect(event.$2?['operation_id'], isNotEmpty);
      expect(event.$2!.keys, isNot(contains('latitude')));
    },
  );

  testWidgets(
    'requests foreground before background and denial stays recoverable',
    (tester) async {
      final gateway = _Gateway()
        ..state.addAll({
          'foreground_location': false,
          'precise_location': false,
          'background_location': false,
          'location_requestable': true,
        });
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pumpAndSettle();
      final background = find.byKey(const Key('permission-backgroundSettings'));
      await tester.ensureVisible(background);
      expect(tester.widget<TextButton>(background).onPressed, isNull);
      final request = find.byKey(const Key('permission-requestLocation'));
      await tester.ensureVisible(request);
      await tester.tap(request);
      await tester.pumpAndSettle();
      expect(gateway.actions, [AttendancePermissionAction.requestLocation]);
      expect(find.text('Não permitida'), findsWidgets);
      expect(
        logger.errors,
        isEmpty,
      ); // A user's refusal is state, not an application exception.
      gateway.state.addAll({
        'foreground_location': true,
        'location_requestable': false,
      });
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Somente aproximada'), findsOneWidget);
      await tester.ensureVisible(background);
      expect(tester.widget<TextButton>(background).onPressed, isNotNull);
      await tester.tap(background);
      await tester.pumpAndSettle();
      expect(
        gateway.actions.last,
        AttendancePermissionAction.backgroundSettings,
      );
      expect(find.textContaining('Allow all the time'), findsOneWidget);
    },
  );

  testWidgets(
    'opens each settings destination and supports disabled notifications and battery review',
    (tester) async {
      final gateway = _Gateway()
        ..state.addAll({
          'notifications': false,
          'notifications_requestable': true,
          'battery_unrestricted': true,
          'location_services': false,
        });
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pumpAndSettle();
      for (final action in [
        AttendancePermissionAction.locationSettings,
        AttendancePermissionAction.appSettings,
        AttendancePermissionAction.requestNotifications,
        AttendancePermissionAction.batterySettings,
      ]) {
        final button = find.byKey(Key('permission-${action.name}'));
        await tester.ensureVisible(button);
        await tester.tap(button);
        await tester.pumpAndSettle();
      }
      gateway.state['notifications_requestable'] = false;
      await tester.tap(find.byTooltip('Atualizar permissões'));
      await tester.pumpAndSettle();
      final settings = find.byKey(const Key('permission-notificationSettings'));
      await tester.ensureVisible(settings);
      await tester.tap(settings);
      await tester.pumpAndSettle();
      expect(
        gateway.actions.last,
        AttendancePermissionAction.notificationSettings,
      );
      expect(find.text('Sem otimização de bateria'), findsOneWidget);
    },
  );

  testWidgets('read failure retries without a permission request', (
    tester,
  ) async {
    final gateway = _Gateway()..readError = StateError('read failed');
    final logger = _Logger();
    await show(tester, gateway, logger);
    await tester.pumpAndSettle();
    expect(
      find.text('Não foi possível atualizar as permissões.'),
      findsOneWidget,
    );
    gateway.readError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('Acesso à localização pronto'), findsOneWidget);
    expect(gateway.actions, isEmpty);
    expect(logger.errors, isNotEmpty);
  });

  testWidgets(
    'action errors are logged with native diagnostics and buttons recover',
    (tester) async {
      final error = PlatformException(
        code: 'attendance_permission_action_failed',
        details: {
          'stage': 'android_permission_action',
          'action': 'appSettings',
          'cause_type': 'ActivityNotFoundException',
        },
      );
      final gateway = _Gateway()..actionError = error;
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pumpAndSettle();
      final button = find.byKey(const Key('permission-appSettings'));
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Não foi possível abrir essa opção'),
        findsOneWidget,
      );
      expect(logger.errors, contains(same(error)));
      expect(tester.widget<TextButton>(button).onPressed, isNotNull);
      expect(
        logger.events.any(
          (e) =>
              e.$1 == 'attendance_permission_action_selected' &&
              e.$2?['action'] == 'appSettings',
        ),
        isTrue,
      );
    },
  );

  testWidgets(
    'a pending action blocks duplicate taps and safely finishes after leaving',
    (tester) async {
      final gateway = _Gateway()..pendingAction = Completer<void>();
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pumpAndSettle();
      final button = find.byKey(const Key('permission-appSettings'));
      await tester.ensureVisible(button);
      tester.widget<TextButton>(button).onPressed!();
      tester.widget<TextButton>(button).onPressed!();
      await tester.pump();
      expect(gateway.actions, hasLength(1));
      expect(tester.widget<TextButton>(button).onPressed, isNull);
      await tester.pumpWidget(const SizedBox());
      gateway.pendingAction!.completeError(StateError('settings rejected'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'late snapshots cannot overwrite a newer state or update a disposed page',
    (tester) async {
      final old = Completer<AttendancePermissionStatus>();
      final gateway = _Gateway()..pendingReads.add(old);
      await show(tester, gateway, _Logger());
      await tester.pump();
      await tester.tap(find.byTooltip('Atualizar permissões'));
      await tester.pumpAndSettle();
      old.complete(
        AttendancePermissionStatus.fromMap({
          ...readyPermissionSnapshot,
          'precise_location': false,
        }),
      );
      await tester.pumpAndSettle();
      expect(find.text('Acesso à localização pronto'), findsOneWidget);
      final late = Completer<AttendancePermissionStatus>();
      gateway.pendingReads.add(late);
      await tester.tap(find.byTooltip('Atualizar permissões'));
      await tester.pump();
      await tester.pumpWidget(const SizedBox());
      late.completeError(StateError('late'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('logging failure does not prevent displaying permissions', (
    tester,
  ) async {
    await show(tester, _Gateway(), _Logger()..failLogging = true);
    await tester.pumpAndSettle();
    expect(find.text('Acesso à localização pronto'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'successful status completion after leaving is still logged safely',
    (tester) async {
      final late = Completer<AttendancePermissionStatus>();
      final gateway = _Gateway()..pendingReads.add(late);
      final logger = _Logger();
      await show(tester, gateway, logger);
      await tester.pump();
      await tester.pumpWidget(const SizedBox());
      late.complete(
        AttendancePermissionStatus.fromMap(readyPermissionSnapshot),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(
        logger.events.any((e) => e.$1 == 'attendance_permission_status'),
        isTrue,
      );
    },
  );

  testWidgets('mobile layout supports enlarged text without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: const TextScaler.linear(2)),
          child: child!,
        ),
        home: AttendancePermissionsPage(gateway: _Gateway(), logger: _Logger()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.drag(find.byType(ListView), const Offset(0, -1400));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}

class _Gateway implements AttendancePermissionsGateway {
  final state = Map<String, Object>.of(readyPermissionSnapshot);
  final actions = <AttendancePermissionAction>[];
  final pendingReads = <Completer<AttendancePermissionStatus>>[];
  Object? readError, actionError;
  Completer<void>? pendingAction;
  @override
  Future<AttendancePermissionStatus> read() async {
    if (pendingReads.isNotEmpty) return pendingReads.removeAt(0).future;
    if (readError case final error?) throw error;
    return AttendancePermissionStatus.fromMap(state);
  }

  @override
  Future<void> perform(AttendancePermissionAction action) async {
    actions.add(action);
    if (actionError case final error?) throw error;
    await pendingAction?.future;
  }
}

class _Logger implements AppLogger {
  final events = <(String, Map<String, Object>?)>[];
  final errors = <Object>[];
  bool failLogging = false;
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (failLogging) throw StateError('logging unavailable');
    events.add((name, parameters));
  }

  @override
  Future<void> recordError(
    Object error,
    StackTrace stackTrace, {
    required String context,
    bool fatal = false,
    Map<String, Object>? parameters,
  }) async {
    errors.add(error);
  }
}
