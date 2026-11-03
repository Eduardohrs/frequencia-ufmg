import 'dart:async';
import 'package:frequencia_ufmg/data/attendance_permissions.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/calendar_status.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/settings/automatic_attendance_controller.dart';
import 'package:frequencia_ufmg/observability/firestore_app_logger.dart';
import 'package:frequencia_ufmg/observability/operational_log_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

final experienceNow = DateTime.utc(2026, 11, 3, 12);
final experienceCourse = CourseRecord(
  id: 'poo',
  code: 'DCC203',
  name: 'Programação Orientada a Objetos',
  nickname: 'POO',
  term: '2026-2',
  workload: 60,
  createdAt: experienceNow,
  updatedAt: experienceNow,
);
SessionRecord experienceSession({
  String id = 'lesson',
  DateTime? start,
  EstadoPing? first,
  EstadoPing? second,
  SituacaoFrequencia? status,
  SessionCalendarStatus calendar = SessionCalendarStatus.scheduled,
}) {
  final begins = start ?? experienceNow.subtract(const Duration(days: 1));
  return SessionRecord(
    id: id,
    startsAt: begins,
    endsAt: begins.add(const Duration(hours: 2)),
    lessonCount: QuantidadeAulas.two,
    callCount: NumeroChamadas.one,
    firstPing: first,
    secondPing: second,
    attendanceStatus: status,
    absences: status == SituacaoFrequencia.present ? 0 : null,
    calendarStatus: calendar,
    createdAt: experienceNow,
    updatedAt: experienceNow,
  );
}

Map<String, Object?> experienceReceipt(
  SessionRecord s, {
  String state = 'succeeded',
  String? moment = 'first',
  String? ping = 'no_campus',
  String? delivery = 'applied',
  bool enabled = true,
}) => {
  'account_id': 'owner',
  'course_id': 'poo',
  'session_id': s.id,
  'starts_at_ms': s.startsAt.millisecondsSinceEpoch,
  'ends_at_ms': s.endsAt.millisecondsSinceEpoch,
  'status': state,
  'moment': moment,
  'first_ping': ping,
  'second_ping': ping,
  'delivery_enabled': enabled,
  'delivery_status': delivery,
  'scheduled_at_ms': s.startsAt.millisecondsSinceEpoch,
};

class ExperiencePermissions implements AttendancePermissionsGateway {
  final flags = <String, Object?>{
    'sdk': 36,
    'exact_alarms': true,
    'power_save_mode': false,
    'location_services': true,
    'foreground_location': true,
    'precise_location': true,
    'background_location': true,
    'notifications': true,
    'battery_unrestricted': true,
    'location_requestable': true,
    'notifications_requestable': true,
    'background_option_label': 'Permitir o tempo todo',
  };
  Object? readError, actionError;
  Completer<AttendancePermissionStatus>? pending;
  bool grant = true;
  final actions = <AttendancePermissionAction>[];
  int reads = 0;
  @override
  Future<AttendancePermissionStatus> read() async {
    reads++;
    if (readError != null) throw readError!;
    return pending?.future ?? AttendancePermissionStatus.fromMap(flags);
  }

  @override
  Future<void> perform(AttendancePermissionAction action) async {
    actions.add(action);
    if (actionError != null) throw actionError!;
    if (!grant) return;
    switch (action) {
      case AttendancePermissionAction.locationSettings:
        flags['location_services'] = true;
      case AttendancePermissionAction.requestLocation:
      case AttendancePermissionAction.appSettings:
        flags['foreground_location'] = true;
        flags['precise_location'] = true;
      case AttendancePermissionAction.backgroundSettings:
        flags['background_location'] = true;
      case AttendancePermissionAction.batterySettings:
        flags['battery_unrestricted'] = true;
      case AttendancePermissionAction.requestNotifications:
      case AttendancePermissionAction.notificationSettings:
        flags['notifications'] = true;
    }
  }
}

class ExperienceLogStore implements OperationalLogStore {
  final rows = <Map<String, Object?>>[];
  @override
  Future<void> add(String id, Map<String, Object?> row) async {
    rows.add(row);
  }
}

class ExperienceHarness {
  ExperienceHarness({SharedPreferencesAsync? preferences})
    : preferences = preferences ?? SharedPreferencesAsync();
  final SharedPreferencesAsync preferences;
  final permissions = ExperiencePermissions();
  final store = ExperienceLogStore();
  late final logger = FirestoreAppLogger(
    store: store,
    currentUserId: () => 'owner',
    platform: 'android',
  );
  final nativeActions = <String>[];
  Object? nativeError, reportError;
  Completer<List<Map<String, Object?>>>? pendingReports;
  List<Map<String, Object?>> reports = [];
  DateTime time = experienceNow;
  bool disposed = false;
  late final controller = AutomaticAttendanceController(
    accountId: 'owner',
    permissions: permissions,
    readReports: () async {
      if (reportError != null) throw reportError!;
      return pendingReports?.future ?? List.of(reports);
    },
    nativeAction: (action) async {
      nativeActions.add(action);
      if (nativeError != null) throw nativeError!;
      if (permissions.grant) permissions.flags['exact_alarms'] = true;
    },
    logger: logger,
    now: () => time,
    preferences: preferences,
  );
  void dispose() {
    if (disposed) return;
    disposed = true;
    controller.dispose();
  }
}
