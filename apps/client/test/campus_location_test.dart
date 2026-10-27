import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:shared_preferences_platform_interface/in_memory_shared_preferences_async.dart';
import 'package:shared_preferences_platform_interface/shared_preferences_async_platform_interface.dart';
import 'package:frequencia_ufmg/data/campus_location.dart';
import 'package:frequencia_ufmg/domain/campus_areas.dart';
import 'package:frequencia_ufmg/domain/campus_detector.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/observability/error_log_details.dart';
import 'fixtures/campus_location_fixture.dart';

void main() {
  final now = DateTime.utc(2026, 10, 27, 12);
  final area = CampusAreas.defaultArea;
  LocationReading reading({double accuracy = 5, DateTime? at}) =>
      LocationReading(
        point: GeoPoint(-19.869, -43.966),
        accuracyMeters: accuracy,
        recordedAt: at ?? now,
      );
  setUp(
    () => SharedPreferencesAsyncPlatform.instance =
        InMemorySharedPreferencesAsync.empty(),
  );

  test('selection persists locally; unknown IDs cannot overwrite it', () async {
    final store = LocalCampusSelection();
    expect(await store.read(), isNull);
    await store.save('direito');
    expect(await LocalCampusSelection().read(), 'direito');
    await expectLater(store.save('unknown'), throwsArgumentError);
    expect(await store.read(), 'direito');
    await SharedPreferencesAsync().setString(
      LocalCampusSelection.storageKey,
      'old',
    );
    expect(await store.read(), 'old'); // UI must require a new explicit choice.
  });

  test(
    'foreground check works without background/notifications exemptions',
    () async {
      final permission = CampusTestPermissions()
        ..flags.addAll({'background_location': false, 'notifications': false});
      final logger = CampusTestLogger();
      final result = await DeviceCampusCheck(
        permissions: permission,
        logger: logger,
        capture: () async => reading(),
        now: () => now,
      ).check(area);
      expect(result.state, EstadoPing.onCampus);
      final event = logger.events.singleWhere(
        (e) => e.$1 == 'campus_location_result',
      );
      final context = jsonDecode(event.$2!['details']! as String) as Map;
      expect(context['campus_id'], 'pampulha');
      expect(context['reason'], 'inside');
      expect(context['accuracy_m'], 5);
      expect(context['fix_duration_ms'], isNonNegative);
      expect(context['duration_ms'], isNonNegative);
      expect((event.$2!['details']! as String).length, lessThanOrEqualTo(500));
      expect(context.keys, isNot(contains('latitude')));
      final cid = event.$2!['operation_id'];
      expect(
        logger.events
            .where((e) => e.$2?['operation_id'] == cid)
            .map((e) => e.$1),
        containsAll([
          'campus_location_check_started',
          'campus_location_check_succeeded',
          'campus_location_permissions',
        ]),
      );
    },
  );

  test(
    'permission failures explain the exact stage without invoking GPS',
    () async {
      for (final entry in {
        'location_services': 'location_disabled',
        'foreground_location': 'permission_denied',
        'precise_location': 'approximate_location',
      }.entries) {
        final permission = CampusTestPermissions()..flags[entry.key] = false;
        final logger = CampusTestLogger();
        final service = DeviceCampusCheck(
          permissions: permission,
          logger: logger,
          capture: () => throw StateError('must not capture'),
        );
        await expectLater(
          service.check(area),
          throwsA(
            isA<CampusCheckFailure>()
                .having((e) => e.logCode, 'reason', entry.value)
                .having((e) => e.userMessage, 'recovery', isNotEmpty),
          ),
        );
        final error = logger.errors.single.$1 as CampusCheckFailure;
        final serialized = ErrorLogDetails.from(error);
        expect(serialized.message, contains(entry.value));
        expect(
          jsonDecode(serialized.details!)['stage_elapsed_ms'],
          isNonNegative,
        );
        expect(jsonDecode(error.logDetails)['stage'], 'permissions');
        expect(jsonDecode(error.logDetails)['campus_id'], 'pampulha');
        expect(logger.events.last.$1, 'campus_location_check_failed');
      }
    },
  );

  test(
    'provider failures preserve cause and are distinct from preflight',
    () async {
      for (final pair in <(Object, String)>[
        (TimeoutException('no fix'), 'location_timeout'),
        (const PermissionDeniedException('revoked'), 'permission_denied'),
        (const LocationServiceDisabledException(), 'location_disabled'),
        (ArgumentError('invalid latitude'), 'invalid_location_data'),
        (
          PlatformException(code: 'provider_reset', message: 'GPS reset'),
          'provider_error',
        ),
      ]) {
        final logger = CampusTestLogger();
        await expectLater(
          DeviceCampusCheck(
            permissions: CampusTestPermissions(),
            logger: logger,
            capture: () async => throw pair.$1,
          ).check(area),
          throwsA(
            isA<CampusCheckFailure>()
                .having((e) => e.logCode, 'code', pair.$2)
                .having((e) => e.userMessage, 'recovery', isNotEmpty),
          ),
        );
        final details = jsonDecode(
          (logger.errors.single.$1 as CampusCheckFailure).logDetails,
        );
        expect(details['stage'], 'location_fix');
        expect(details['cause_type'], pair.$1.runtimeType.toString());
        if (pair.$1 is PlatformException) {
          expect(details['cause_code'], 'provider_reset');
        }
      }
      final permission = CampusTestPermissions()
        ..error = StateError('native bridge offline');
      final logger = CampusTestLogger();
      await expectLater(
        DeviceCampusCheck(permissions: permission, logger: logger).check(area),
        throwsA(isA<CampusCheckFailure>()),
      );
      expect(
        jsonDecode(
          (logger.errors.single.$1 as CampusCheckFailure).logDetails,
        )['stage'],
        'permissions',
      );
    },
  );

  test(
    'poor accuracy and stale fixes are inconclusive and logging cannot block',
    () async {
      for (final fix in [
        reading(accuracy: 500),
        reading(at: now.subtract(const Duration(minutes: 3))),
      ]) {
        final result = await DeviceCampusCheck(
          permissions: CampusTestPermissions(),
          logger: CampusTestLogger()..failLogging = true,
          capture: () async => fix,
          now: () => now,
        ).check(area);
        expect(result.state, EstadoPing.unavailable);
      }
    },
  );

  testWidgets(
    'a provider that never returns cannot leave the UI waiting forever',
    (tester) async {
      final service = DeviceCampusCheck(
        permissions: CampusTestPermissions(),
        logger: CampusTestLogger(),
        capture: () => Completer<LocationReading>().future,
      );
      final result = expectLater(
        service.check(area),
        throwsA(
          isA<CampusCheckFailure>().having(
            (e) => e.logCode,
            'timeout',
            'location_timeout',
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(seconds: 26));
      await result;
    },
  );

  test(
    'production provider requests one high-accuracy time-limited fix',
    () async {
      final previous = GeolocatorPlatform.instance;
      final platform = _PositionPlatform(now);
      GeolocatorPlatform.instance = platform;
      addTearDown(() => GeolocatorPlatform.instance = previous);
      expect(
        (await DeviceCampusCheck(
          permissions: CampusTestPermissions(),
          logger: CampusTestLogger(),
          now: () => now,
        ).check(area)).state,
        EstadoPing.onCampus,
      );
      expect(platform.settings!.accuracy, LocationAccuracy.high);
      expect(platform.settings!.timeLimit, const Duration(seconds: 20));
    },
  );
}

class _PositionPlatform extends GeolocatorPlatform {
  _PositionPlatform(this.now);
  final DateTime now;
  LocationSettings? settings;
  @override
  Future<Position> getCurrentPosition({
    LocationSettings? locationSettings,
  }) async {
    settings = locationSettings;
    return Position(
      latitude: -19.869,
      longitude: -43.966,
      timestamp: now,
      accuracy: 5,
      altitude: 0,
      altitudeAccuracy: 0,
      heading: 0,
      headingAccuracy: 0,
      speed: 0,
      speedAccuracy: 0,
    );
  }
}
