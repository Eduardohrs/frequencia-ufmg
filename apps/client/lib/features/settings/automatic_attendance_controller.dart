import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../data/attendance_permissions.dart';
import '../../data/academic_records.dart';
import '../../domain/attendance.dart';
import '../../data/calendar_status.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';

enum AttendanceSetupNeed {
  locationServices,
  location,
  precise,
  background,
  alarms,
  battery,
  notifications,
}

class AutomaticAttendanceController extends ChangeNotifier {
  AutomaticAttendanceController({
    required this.accountId,
    required this.permissions,
    required this.readReports,
    required this.nativeAction,
    required this.logger,
    required this.now,
    SharedPreferencesAsync? preferences,
  }) : preferences = preferences ?? SharedPreferencesAsync();
  final String accountId;
  final AttendancePermissionsGateway permissions;
  final Future<List<Map<String, Object?>>> Function() readReports;
  final Future<void> Function(String) nativeAction;
  final AppLogger logger;
  final DateTime Function() now;
  final SharedPreferencesAsync preferences;
  AttendancePermissionStatus? status;
  List<Map<String, Object?>> reports = [];
  bool busy = false,
      acting = false,
      permissionError = false,
      reportError = false;
  bool _disposed = false;
  DateTime? _snoozedUntil;
  Future<void>? _refreshing;
  String get _key =>
      'attendance_setup_snooze.v1.${Uri.encodeComponent(accountId)}';
  List<AttendanceSetupNeed> get needs {
    final s = status;
    if (s == null) return [];
    return [
      if (!s.locationServices) AttendanceSetupNeed.locationServices,
      if (!s.foregroundLocation) AttendanceSetupNeed.location,
      if (s.foregroundLocation && !s.preciseLocation)
        AttendanceSetupNeed.precise,
      if (s.foregroundLocation && !s.backgroundLocation)
        AttendanceSetupNeed.background,
      if (s.exactAlarms == false) AttendanceSetupNeed.alarms,
      if (!s.batteryUnrestricted) AttendanceSetupNeed.battery,
      if (!s.notifications) AttendanceSetupNeed.notifications,
    ];
  }

  AttendanceSetupNeed? get next => needs.firstOrNull;
  bool get showReminder =>
      next != null && !(_snoozedUntil?.isAfter(now()) ?? false);
  String get title => permissionError
      ? 'Não foi possível conferir a configuração'
      : status == null
      ? 'Conferindo configuração'
      : next == null
      ? 'Configuração pronta'
      : 'Concluir configuração';
  String get instruction => permissionError
      ? 'Não foi possível conferir agora. Você pode continuar usando o registro manual.'
      : status == null
      ? 'Conferindo o que falta para acompanhar suas aulas.'
      : switch (next) {
          AttendanceSetupNeed.locationServices =>
            'Ligue a localização do aparelho para acompanhar suas aulas.',
          AttendanceSetupNeed.location =>
            'Permita a localização para estimar sua presença no campus.',
          AttendanceSetupNeed.precise =>
            'Ative a localização precisa nas configurações do aplicativo.',
          AttendanceSetupNeed.background =>
            'Permita a localização o tempo todo para acompanhar aulas com a tela apagada.',
          AttendanceSetupNeed.alarms =>
            'Permita alarmes e lembretes para verificar a localização nos horários da aula.',
          AttendanceSetupNeed.battery =>
            'Em Bateria, selecione Sem restrições para reduzir interrupções do Android.',
          AttendanceSetupNeed.notifications =>
            'Permita notificações para receber o resultado e corrigir sua frequência.',
          null =>
            'As aulas com chamada são acompanhadas no Android. Confira o resultado na frequência da disciplina.',
        };
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> refresh({bool afterCurrent = false}) async {
    if (afterCurrent && _refreshing != null) await _refreshing;
    if (_disposed) return;
    await (_refreshing ??= _read().whenComplete(() => _refreshing = null));
  }

  Future<void> _read() async {
    busy = true;
    _notify();
    final id = newCorrelationId('attendance_setup');
    final watch = Stopwatch()..start();
    await Future.wait([
      (() async {
        try {
          final s = await permissions.read().timeout(
            const Duration(seconds: 10),
          );
          if (!_disposed) {
            status = s;
            permissionError = false;
          }
        } catch (error, stack) {
          if (!_disposed) permissionError = true;
          recordOperationalFailure(
            logger,
            error,
            stack,
            'attendance_setup_read',
            {
              'operation_id': id,
              'stage': 'permissions',
              'duration_ms': watch.elapsedMilliseconds,
            },
            failureCode: 'attendance_setup_read_failed',
          );
        }
      })(),
      (() async {
        try {
          final values = await readReports().timeout(
            const Duration(seconds: 10),
          );
          if (!_disposed) {
            reports = values
                .where(
                  (r) =>
                      r['account_id'] == null || r['account_id'] == accountId,
                )
                .toList();
            reportError = false;
          }
        } catch (error, stack) {
          if (!_disposed) reportError = true;
          recordOperationalFailure(
            logger,
            error,
            stack,
            'attendance_setup_read',
            {
              'operation_id': id,
              'stage': 'local_receipts',
              'duration_ms': watch.elapsedMilliseconds,
            },
            failureCode: 'attendance_receipts_read_failed',
          );
        }
      })(),
      (() async {
        try {
          final ms = await preferences.getInt(_key);
          if (!_disposed && ms != null) {
            final stored = DateTime.fromMillisecondsSinceEpoch(ms);
            if (_snoozedUntil == null || stored.isAfter(_snoozedUntil!)) {
              _snoozedUntil = stored;
            }
          }
        } catch (error, stack) {
          recordOperationalFailure(
            logger,
            error,
            stack,
            'attendance_setup_read',
            {
              'operation_id': id,
              'stage': 'snooze_read',
              'duration_ms': watch.elapsedMilliseconds,
            },
            failureCode: 'attendance_snooze_read_failed',
          );
        }
      })(),
    ]);
    emitOperationalEvent(logger, 'attendance_setup_read_completed', {
      'operation_id': id,
      'stage': 'summary',
      'duration_ms': watch.elapsedMilliseconds,
      'missing_count': needs.length,
      'receipt_count': reports.length,
      'permissions_available': !permissionError && status != null,
      'receipts_available': !reportError,
      if (status != null) ...status!.logFields,
    });
    if (!_disposed) {
      busy = false;
      _notify();
    }
  }

  Future<void> defer() async {
    _snoozedUntil = now().add(const Duration(hours: 24));
    _notify();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('attendance_snooze'),
      'stage': 'snooze_write',
      'missing_count': needs.length,
    };
    try {
      await preferences.setInt(_key, _snoozedUntil!.millisecondsSinceEpoch);
      emitOperationalEvent(logger, 'attendance_setup_deferred', fields);
    } catch (error, stack) {
      recordOperationalFailure(
        logger,
        error,
        stack,
        'attendance_setup_defer',
        fields,
        failureCode: 'attendance_snooze_write_failed',
      );
    }
  }

  Future<void> resolveNext() async {
    final need = next;
    if (need == null || acting) return;
    acting = true;
    _notify();
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('attendance_setup'),
      'stage': 'system_settings',
      'need': need.name,
    };
    emitOperationalEvent(logger, 'attendance_setup_action_started', fields);
    try {
      if (need == AttendanceSetupNeed.alarms) {
        await nativeAction('request_alarm_permission');
      } else {
        final action = switch (need) {
          AttendanceSetupNeed.locationServices =>
            AttendancePermissionAction.locationSettings,
          AttendanceSetupNeed.location =>
            status!.locationRequestable
                ? AttendancePermissionAction.requestLocation
                : AttendancePermissionAction.appSettings,
          AttendanceSetupNeed.precise => AttendancePermissionAction.appSettings,
          AttendanceSetupNeed.background =>
            AttendancePermissionAction.backgroundSettings,
          AttendanceSetupNeed.battery =>
            AttendancePermissionAction.batterySettings,
          _ =>
            status!.notificationsRequestable
                ? AttendancePermissionAction.requestNotifications
                : AttendancePermissionAction.notificationSettings,
        };
        await permissions.perform(action);
      }
      await refresh();
      emitOperationalEvent(logger, 'attendance_setup_action_succeeded', {
        ...fields,
        'duration_ms': watch.elapsedMilliseconds,
        'need_resolved': !needs.contains(need),
        'remaining_count': needs.length,
        'permissions_available': !permissionError,
      });
    } catch (error, stack) {
      recordOperationalFailure(
        logger,
        error,
        stack,
        'attendance_setup_action',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        failureCode: 'attendance_setup_action_failed',
      );
      rethrow;
    } finally {
      if (!_disposed) {
        acting = false;
        _notify();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

/// Human meaning of capture evidence; a scheduled job is never called a capture.
String? attendanceEvidence(
  String courseId,
  SessionRecord session,
  DateTime now, {
  List<Map<String, Object?>> reports = const [],
  bool localReadFailed = false,
}) {
  if (!session.calendarStatus.requiresAttendance) return null;
  final matching = reports
      .where(
        (r) =>
            r['course_id'] == courseId &&
            r['session_id'] == session.id &&
            r['starts_at_ms'] == session.startsAt.millisecondsSinceEpoch &&
            r['ends_at_ms'] == session.endsAt.millisecondsSinceEpoch,
      )
      .toList();
  Map<String, Object?>? latest(String moment) {
    final list =
        matching.where((r) => (r['moment'] ?? 'first') == moment).toList()
          ..sort(
            (a, b) => ((b['scheduled_at_ms'] as int?) ?? 0).compareTo(
              (a['scheduled_at_ms'] as int?) ?? 0,
            ),
          );
    return list.firstOrNull;
  }

  String ping(EstadoPing? state) => switch (state) {
    EstadoPing.onCampus => 'no campus',
    EstadoPing.away => 'fora do campus',
    _ => 'sem localização',
  };
  String moment(String label, Map<String, Object?>? report, EstadoPing? saved) {
    if (report == null) {
      return saved == null
          ? '$label: sem informação'
          : '$label: ${ping(saved)}';
    }
    final state = report['status'];
    if (state == 'scheduled') return '$label: verificação agendada';
    if (state == 'running') return '$label: verificando localização';
    if (state == 'succeeded') {
      return '$label: ${switch (report[label == 'Início' ? 'first_ping' : 'second_ping']) {
        'no_campus' => 'no campus',
        'fora' => 'fora do campus',
        _ => 'localização indisponível',
      }}';
    }
    if (state == 'cancelled' || state == 'superseded') {
      return '$label: agendamento cancelado';
    }
    return '$label: localização não obtida';
  }

  if (matching.isEmpty &&
      session.firstPing == null &&
      session.secondPing == null) {
    if (session.attendanceStatus != null) {
      return 'Registro salvo; sem detalhes de localização.';
    }
    if (localReadFailed) {
      return 'Não foi possível conferir a localização desta aula.';
    }
    if (now.isBefore(session.startsAt)) {
      return 'Aula futura; ainda não há localização a conferir.';
    }
    if (now.isBefore(session.endsAt)) {
      return 'Aula em andamento; aguardando verificações de localização.';
    }
    return 'Sem evidência de localização; informe sua frequência.';
  }
  final capture =
      '${moment('Início', latest('first'), session.firstPing)} • ${moment('Fim', latest('second'), session.secondPing)}';
  final completed = [latest('first'), latest('second')]
      .whereType<Map<String, Object?>>()
      .where((r) => r['status'] == 'succeeded')
      .toList();
  if (completed.any(
    (r) =>
        r['delivery_status'] == 'unresolved' ||
        r['delivery_status'] == 'rejected',
  )) {
    return '$capture. Confira e registre sua frequência.';
  }
  if (completed.any(
    (r) =>
        r['delivery_enabled'] == true &&
        !const {
          'applied',
          'already_applied',
          'preserved',
          'discarded',
        }.contains(r['delivery_status']),
  )) {
    return '$capture. Salvo no aparelho; aguardando sincronização.';
  }
  if (completed.any(
    (r) => const {'applied', 'already_applied'}.contains(r['delivery_status']),
  )) {
    return '$capture. Frequência sincronizada.';
  }
  if (completed.any((r) => r['delivery_status'] == 'preserved')) {
    return '$capture. Seu registro anterior foi mantido.';
  }
  return capture;
}
