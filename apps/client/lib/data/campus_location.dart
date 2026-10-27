import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../domain/campus_areas.dart';
import '../domain/campus_detector.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../observability/error_log_details.dart';
import 'attendance_permissions.dart';

abstract interface class CampusSelectionGateway {
  Future<String?> read();
  Future<void> save(String campusId);
}

final class LocalCampusSelection implements CampusSelectionGateway {
  LocalCampusSelection({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();
  static const storageKey = 'attendance.campus.v1';
  final SharedPreferencesAsync _preferences;
  @override
  Future<String?> read() => _preferences.getString(storageKey);
  @override
  Future<void> save(String campusId) async {
    if (CampusAreas.find(campusId) == null) {
      throw ArgumentError('Unknown campus');
    }
    await _preferences.setString(storageKey, campusId);
  }
}

abstract interface class CampusCheckGateway {
  Future<CampusDetection> check(CampusArea area);
}

/// One explicit foreground check. No attendance writes or scheduled tracking.
final class DeviceCampusCheck implements CampusCheckGateway {
  DeviceCampusCheck({
    required this.permissions,
    required this.logger,
    Future<LocationReading> Function()? capture,
    DateTime Function()? now,
  }) : _capture = capture ?? _deviceReading,
       _now = now ?? DateTime.now;
  final AttendancePermissionsGateway permissions;
  final AppLogger logger;
  final Future<LocationReading> Function() _capture;
  final DateTime Function() _now;

  @override
  Future<CampusDetection> check(CampusArea area) => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.campusLocationCheck,
    action: () async {
      var stage = 'permissions';
      final stageWatch = Stopwatch()..start();
      CampusCheckFailure failure(String code, [Object? cause]) =>
          CampusCheckFailure(
            code,
            stage,
            area.id,
            cause: cause,
            stageElapsedMs: stageWatch.elapsedMilliseconds,
          );
      try {
        final status = await permissions.read();
        emitCampusEvent(logger, 'campus_location_permissions', {
          'campus_id': area.id,
          'stage': stage,
          'duration_ms': stageWatch.elapsedMilliseconds,
          ...status.logFields,
        });
        if (!status.locationServices) {
          throw failure('location_disabled');
        }
        if (!status.foregroundLocation) {
          throw failure('permission_denied');
        }
        if (!status.preciseLocation) {
          throw failure('approximate_location');
        }
        stage = 'location_fix';
        emitCampusEvent(logger, 'campus_location_fix_started', {
          'campus_id': area.id,
          'stage': stage,
          'provider_timeout_ms': 20000,
          'watchdog_timeout_ms': 25000,
        });
        stageWatch.reset();
        final reading = await _capture().timeout(const Duration(seconds: 25));
        final fixDurationMs = stageWatch.elapsedMilliseconds;
        stage = 'classification';
        stageWatch.reset();
        final result = CampusDetector(
          area: area,
          maxAge: const Duration(minutes: 2),
          maxAccuracyMeters: 100,
        ).classify(reading, now: _now());
        emitCampusEvent(logger, 'campus_location_result', {
          'stage': stage,
          'fix_duration_ms': fixDurationMs,
          'duration_ms': stageWatch.elapsedMilliseconds,
          ...result.diagnostics,
        });
        return result;
      } on CampusCheckFailure {
        rethrow;
      } catch (error) {
        final code = switch (error) {
          TimeoutException() => 'location_timeout',
          PermissionDeniedException() => 'permission_denied',
          LocationServiceDisabledException() => 'location_disabled',
          ArgumentError() => 'invalid_location_data',
          _ => 'provider_error',
        };
        throw failure(code, error);
      }
    },
  );

  static Future<LocationReading> _deviceReading() async {
    final position = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
        timeLimit: Duration(seconds: 20),
      ),
    );
    return LocationReading(
      point: GeoPoint(position.latitude, position.longitude),
      accuracyMeters: position.accuracy,
      recordedAt: position.timestamp,
    );
  }
}

final class CampusCheckFailure implements StructuredAppError {
  const CampusCheckFailure(
    this.logCode,
    this.stage,
    this.campusId, {
    this.cause,
    this.stageElapsedMs,
  });
  @override
  final String logCode;
  final String stage, campusId;
  final Object? cause;
  final int? stageElapsedMs;
  String get userMessage => switch (logCode) {
    'location_disabled' => 'Ative a localização do aparelho e tente novamente.',
    'permission_denied' => 'Permita a localização na tela de permissões.',
    'approximate_location' =>
      'Permita a localização precisa para verificar o campus.',
    'location_timeout' =>
      'A localização demorou a responder. Tente novamente em um local aberto.',
    _ => 'Não foi possível obter a localização. Tente novamente.',
  };
  @override
  String get logMessage => 'Campus location check failed: $logCode';
  @override
  String get logDetails {
    final error = cause == null ? null : ErrorLogDetails.from(cause!);
    return jsonEncode({
      'stage': stage,
      'campus_id': campusId,
      'stage_elapsed_ms': ?stageElapsedMs,
      'cause_type': ?error?.type,
      'cause_code': ?error?.code,
      'cause_message': ?error?.message,
    });
  }
}

/// Preserve bounded operational context in the production Firestore transport.
/// Raw device coordinates stay in memory; only decision/quality data is emitted.
void emitCampusEvent(
  AppLogger logger,
  String event,
  Map<String, Object> fields,
) {
  final correlation = currentOperationId ?? newCorrelationId('campus');
  unawaited(
    Future<void>.sync(
      () => logger.logEvent(
        event,
        parameters: {
          ...fields,
          'operation_id': correlation,
          'details': jsonEncode(fields),
        },
      ),
    ).catchError((Object error) {
      debugPrint(
        'campus_log_delivery_failed event=$event type=${error.runtimeType}',
      );
    }),
  );
}
