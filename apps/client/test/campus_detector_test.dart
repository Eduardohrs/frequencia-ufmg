import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/domain/campus_detector.dart';

void main() {
  final now = DateTime.utc(2026, 10, 27, 12);
  final rectangle = CampusRectangle(south: 0, north: .01, west: 0, east: .01);
  final area = CampusArea(id: 'test', name: 'Test', rectangles: [rectangle]);
  final detector = CampusDetector(
    area: area,
    maxAge: const Duration(minutes: 2),
    maxAccuracyMeters: 100,
  );
  CampusDetection classify(
    double lat,
    double lon, {
    double accuracy = 5,
    DateTime? recordedAt,
  }) => detector.classify(
    LocationReading(
      point: GeoPoint(lat, lon),
      accuracyMeters: accuracy,
      recordedAt: recordedAt ?? now,
    ),
    now: now,
  );

  test('rectangle includes its edges; points beyond each side are outside', () {
    for (final point in [
      (.005, .005),
      (0.0, .005),
      (.005, 0.0),
      (.01, .005),
      (.005, .01),
      (0.0, 0.0),
    ]) {
      expect(classify(point.$1, point.$2).state, EstadoPing.onCampus);
    }
    for (final point in [
      (-.001, .005),
      (.011, .005),
      (.005, -.001),
      (.005, .011),
    ]) {
      expect(classify(point.$1, point.$2).state, EstadoPing.away);
    }
  });
  test('low quality or old readings are unavailable, never absence', () {
    final cases = [
      classify(.02, .005, accuracy: 101),
      classify(
        .005,
        .005,
        recordedAt: now.subtract(const Duration(minutes: 2, milliseconds: 1)),
      ),
      classify(.005, .005, recordedAt: now.add(const Duration(seconds: 11))),
    ];
    expect(cases.map((r) => r.reason), [
      CampusDetectionReason.poorAccuracy,
      CampusDetectionReason.stale,
      CampusDetectionReason.future,
    ]);
    expect(cases.every((r) => r.state == EstadoPing.unavailable), isTrue);
    expect(
      classify(
        .005,
        .005,
        accuracy: 100,
        recordedAt: now.subtract(const Duration(minutes: 2)),
      ).state,
      EstadoPing.onCampus,
    );
    expect(
      classify(
        .005,
        .005,
        accuracy: 0,
        recordedAt: now.add(const Duration(seconds: 10)),
      ).state,
      EstadoPing.onCampus,
    );
  });
  test('diagnostics identify area, decision and reading quality', () {
    final fields = classify(.005, .005).diagnostics;
    expect(fields, containsPair('campus_id', 'test'));
    expect(fields, containsPair('area_rectangles', 1));
    expect(fields, containsPair('campus_name', 'Test'));
    expect(fields, containsPair('reason', 'inside'));
    expect(fields, containsPair('ping_state', 'no_campus'));
    expect(fields, containsPair('accuracy_m', 5.0));
    expect(fields, containsPair('reading_age_ms', 0));
  });
  test('invalid input and policy are rejected before classification', () {
    for (final pair in [
      (double.nan, 0.0),
      (91.0, 0.0),
      (-91.0, 0.0),
      (0.0, 181.0),
      (0.0, -181.0),
      (0.0, double.infinity),
    ]) {
      expect(() => GeoPoint(pair.$1, pair.$2), throwsArgumentError);
    }
    for (final accuracy in [-1.0, double.nan, double.infinity]) {
      expect(
        () => LocationReading(
          point: GeoPoint(0, 0),
          accuracyMeters: accuracy,
          recordedAt: now,
        ),
        throwsArgumentError,
      );
    }
    for (final values in [
      (0.0, 0.0, 0.0, .01),
      (.01, 0.0, 0.0, .01),
      (0.0, .01, .01, 0.0),
    ]) {
      expect(
        () => CampusRectangle(
          south: values.$1,
          north: values.$2,
          west: values.$3,
          east: values.$4,
        ),
        throwsArgumentError,
      );
    }
    expect(
      () => CampusArea(id: '', name: 'Test', rectangles: [rectangle]),
      throwsArgumentError,
    );
    expect(
      () => CampusArea(id: 'test', name: '', rectangles: [rectangle]),
      throwsArgumentError,
    );
    expect(
      () => CampusArea(id: 'empty', name: 'Empty', rectangles: []),
      throwsArgumentError,
    );
    expect(() => area.rectangles.clear(), throwsUnsupportedError);
    expect(
      () => CampusDetector(
        area: area,
        maxAge: Duration.zero,
        maxAccuracyMeters: 10,
      ),
      throwsArgumentError,
    );
    for (final accuracy in [0.0, double.nan, double.infinity]) {
      expect(
        () => CampusDetector(
          area: area,
          maxAge: const Duration(minutes: 1),
          maxAccuracyMeters: accuracy,
        ),
        throwsArgumentError,
      );
    }
  });
}
