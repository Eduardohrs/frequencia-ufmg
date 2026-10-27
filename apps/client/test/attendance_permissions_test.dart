import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/observability/error_log_details.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('production channel reads the native response', () async {
    const channel = MethodChannel(
      'br.ufmg.frequencia.frequencia_ufmg/attendance_permissions',
    );
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
          expect((call.arguments as Map)['operation_id'], isNotEmpty);
          return ready;
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null),
    );
    expect(
      (await const AndroidAttendancePermissions().read()).locationReady,
      isTrue,
    );
  });
  test(
    'readiness requires services, precise foreground and background access',
    () {
      for (final field in [
        'location_services',
        'precise_location',
        'foreground_location',
        'background_location',
      ]) {
        final status = AttendancePermissionStatus.fromMap({
          ...ready,
          field: false,
        });
        expect(status.locationReady, isFalse, reason: field);
      }
      final status = AttendancePermissionStatus.fromMap({
        ...ready,
        'notifications': false,
        'battery_unrestricted': false,
      });
      expect(status.locationReady, isTrue);
      expect(status.logFields['notifications'], false);
    },
  );

  test(
    'invalid platform snapshots identify the broken field without dumping data',
    () {
      for (final data in [
        {...ready, 'sdk': '36'},
        {...ready}..remove('location_services'),
        {...ready, 'background_option_label': 0},
      ]) {
        try {
          AttendancePermissionStatus.fromMap(data);
          fail('Expected an invalid snapshot');
        } catch (error) {
          final details = ErrorLogDetails.from(error);
          expect(details.code, 'invalid_permission_snapshot');
          expect(details.details, contains('permission_snapshot_decode'));
        }
      }
    },
  );

  test(
    'platform gateway only inspects state or performs the chosen action',
    () async {
      final calls = <String>[];
      final gateway = AndroidAttendancePermissions(
        invoke: <T>(method, [arguments]) async {
          calls.add(method);
          return (method == 'read' ? ready : null) as T?;
        },
      );
      expect((await gateway.read()).locationReady, isTrue);
      for (final action in AttendancePermissionAction.values) {
        await gateway.perform(action);
      }
      expect(calls, [
        'read',
        ...AttendancePermissionAction.values.map((a) => a.name),
      ]);
    },
  );

  test('empty platform response is diagnosable', () async {
    final gateway = AndroidAttendancePermissions(
      invoke: <T>(method, [arguments]) async => null,
    );
    await expectLater(
      gateway.read(),
      throwsA(isA<PermissionSnapshotException>()),
    );
  });

  test('production gateway can be constructed without making a request', () {
    expect(
      const AndroidAttendancePermissions(),
      isA<AttendancePermissionsGateway>(),
    );
  });
}

const ready = <String, Object>{
  'sdk': 36,
  'location_services': true,
  'foreground_location': true,
  'precise_location': true,
  'background_location': true,
  'notifications': true,
  'battery_unrestricted': false,
  'location_requestable': false,
  'notifications_requestable': false,
  'background_option_label': 'Allow all the time',
};
