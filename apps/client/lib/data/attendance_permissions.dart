import 'package:flutter/services.dart';

import '../observability/error_log_details.dart';
import '../observability/audited_operation.dart';

enum AttendancePermissionAction {
  requestLocation,
  requestNotifications,
  locationSettings,
  appSettings,
  backgroundSettings,
  notificationSettings,
  batterySettings,
}

abstract interface class AttendancePermissionsGateway {
  Future<AttendancePermissionStatus> read();
  Future<void> perform(AttendancePermissionAction action);
}

final class AttendancePermissionStatus {
  AttendancePermissionStatus.fromMap(Map<Object?, Object?> data)
    : sdk = _integer(data, 'sdk'),
      locationServices = _flag(data, 'location_services'),
      foregroundLocation = _flag(data, 'foreground_location'),
      preciseLocation = _flag(data, 'precise_location'),
      backgroundLocation = _flag(data, 'background_location'),
      notifications = _flag(data, 'notifications'),
      batteryUnrestricted = _flag(data, 'battery_unrestricted'),
      locationRequestable = _flag(data, 'location_requestable'),
      notificationsRequestable = _flag(data, 'notifications_requestable'),
      backgroundOptionLabel = _text(data, 'background_option_label');

  final int sdk;
  final bool locationServices, foregroundLocation, preciseLocation;
  final bool backgroundLocation, notifications, batteryUnrestricted;
  final bool locationRequestable, notificationsRequestable;
  final String backgroundOptionLabel;

  bool get locationReady =>
      locationServices &&
      foregroundLocation &&
      preciseLocation &&
      backgroundLocation;

  Map<String, Object> get logFields => {
    'android_sdk': sdk,
    'location_services': locationServices,
    'foreground_location': foregroundLocation,
    'precise_location': preciseLocation,
    'background_location': backgroundLocation,
    'notifications': notifications,
    'battery_unrestricted': batteryUnrestricted,
    'location_requestable': locationRequestable,
    'notifications_requestable': notificationsRequestable,
  };

  static bool _flag(Map<Object?, Object?> data, String field) {
    if (data[field] case final bool value) return value;
    throw PermissionSnapshotException(field);
  }

  static int _integer(Map<Object?, Object?> data, String field) {
    if (data[field] case final int value) return value;
    throw PermissionSnapshotException(field);
  }

  static String _text(Map<Object?, Object?> data, String field) {
    if (data[field] case final String value) return value;
    throw PermissionSnapshotException(field);
  }
}

final class PermissionSnapshotException implements StructuredAppError {
  const PermissionSnapshotException(this.field);
  final String field;
  @override
  String get logCode => 'invalid_permission_snapshot';
  @override
  String get logMessage => 'Invalid Android permission status';
  @override
  String get logDetails => 'stage=permission_snapshot_decode field=$field';
}

typedef AttendancePermissionInvoker =
    Future<T?> Function<T>(String method, [Object? arguments]);

final class AndroidAttendancePermissions
    implements AttendancePermissionsGateway {
  const AndroidAttendancePermissions({AttendancePermissionInvoker? invoke})
    : _invoke = invoke;
  static const _channel = MethodChannel(
    'br.ufmg.frequencia.frequencia_ufmg/attendance_permissions',
  );
  final AttendancePermissionInvoker? _invoke;

  Future<T?> _call<T>(String method) {
    final arguments = {
      'operation_id':
          currentOperationId ?? newCorrelationId('attendancePermission'),
    };
    return _invoke == null
        ? _channel.invokeMethod<T>(method, arguments)
        : _invoke<T>(method, arguments);
  }

  @override
  Future<AttendancePermissionStatus> read() async {
    final data = await _call<Map<Object?, Object?>>('read');
    if (data == null) throw const PermissionSnapshotException('empty_response');
    return AttendancePermissionStatus.fromMap(data);
  }

  @override
  Future<void> perform(AttendancePermissionAction action) =>
      _call<void>(action.name);
}
