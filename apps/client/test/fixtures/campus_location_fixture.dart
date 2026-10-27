import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/observability/app_logger.dart';
import 'attendance_permission_fixture.dart';

class CampusTestPermissions implements AttendancePermissionsGateway {
  final flags = Map<String, Object>.of(readyPermissionSnapshot);
  Object? error;
  @override
  Future<AttendancePermissionStatus> read() async {
    if (error case final e?) throw e;
    return AttendancePermissionStatus.fromMap(flags);
  }

  @override
  Future<void> perform(AttendancePermissionAction action) async =>
      throw StateError('A check must never request permissions automatically');
}

class CampusTestLogger implements AppLogger {
  final events = <(String, Map<String, Object>?)>[];
  final errors = <(Object, String, Map<String, Object>?)>[];
  bool failLogging = false;
  @override
  Future<void> logEvent(String name, {Map<String, Object>? parameters}) async {
    if (failLogging) throw StateError('logger offline');
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
    if (failLogging) throw StateError('logger offline');
    errors.add((error, context, parameters));
  }
}
