import 'attendance.dart';

final class GeoPoint {
  GeoPoint(this.latitude, this.longitude) {
    if (!latitude.isFinite ||
        latitude.abs() > 90 ||
        !longitude.isFinite ||
        longitude.abs() > 180) {
      throw ArgumentError('Invalid geographic coordinate');
    }
  }
  final double latitude, longitude;
}

final class LocationReading {
  LocationReading({
    required this.point,
    required this.accuracyMeters,
    required this.recordedAt,
  }) {
    if (!accuracyMeters.isFinite || accuracyMeters < 0) {
      throw ArgumentError('Invalid horizontal accuracy');
    }
  }
  final GeoPoint point;
  final double accuracyMeters;
  final DateTime recordedAt;
}

final class CampusRectangle {
  CampusRectangle({
    required this.south,
    required this.north,
    required this.west,
    required this.east,
  }) {
    GeoPoint(south, west);
    GeoPoint(north, east);
    if (south >= north || west >= east) {
      throw ArgumentError('Invalid campus rectangle');
    }
  }
  final double south, north, west, east;

  bool contains(GeoPoint point) =>
      point.latitude >= south &&
      point.latitude <= north &&
      point.longitude >= west &&
      point.longitude <= east;
}

/// A campus may have separated sites. A few approximate rectangles keep those
/// sites covered without accepting every intervening street or stadium.
final class CampusArea {
  CampusArea({
    required this.id,
    required this.name,
    required List<CampusRectangle> rectangles,
  }) : rectangles = List.unmodifiable(rectangles) {
    if (id.trim().isEmpty || name.trim().isEmpty || rectangles.isEmpty) {
      throw ArgumentError('Invalid campus area');
    }
  }
  final String id, name;
  final List<CampusRectangle> rectangles;

  bool contains(GeoPoint point) => rectangles.any((r) => r.contains(point));
}

enum CampusDetectionReason { inside, outside, poorAccuracy, stale, future }

final class CampusDetection {
  const CampusDetection._(this.state, this.reason, this.diagnostics);
  final EstadoPing state;
  final CampusDetectionReason reason;
  final Map<String, Object> diagnostics;
}

/// Classification only; no attendance mutation or background task is started.
final class CampusDetector {
  CampusDetector({
    required this.area,
    required this.maxAge,
    required this.maxAccuracyMeters,
  }) {
    if (maxAge <= Duration.zero ||
        !maxAccuracyMeters.isFinite ||
        maxAccuracyMeters <= 0) {
      throw ArgumentError('Invalid location policy');
    }
  }
  final CampusArea area;
  final Duration maxAge;
  final double maxAccuracyMeters;

  CampusDetection classify(LocationReading reading, {required DateTime now}) {
    final age = now.difference(reading.recordedAt);
    final CampusDetectionReason reason;
    if (age < const Duration(seconds: -10)) {
      reason = CampusDetectionReason.future;
    } else if (age > maxAge) {
      reason = CampusDetectionReason.stale;
    } else if (reading.accuracyMeters > maxAccuracyMeters) {
      reason = CampusDetectionReason.poorAccuracy;
    } else {
      reason = area.contains(reading.point)
          ? CampusDetectionReason.inside
          : CampusDetectionReason.outside;
    }
    final state = switch (reason) {
      CampusDetectionReason.inside => EstadoPing.onCampus,
      CampusDetectionReason.outside => EstadoPing.away,
      _ => EstadoPing.unavailable,
    };
    return CampusDetection._(
      state,
      reason,
      Map.unmodifiable({
        'campus_id': area.id,
        'campus_name': area.name,
        'area_rectangles': area.rectangles.length,
        'reason': reason.name,
        'ping_state': state.code,
        'accuracy_m': reading.accuracyMeters,
        'reading_age_ms': age.inMilliseconds,
        'max_age_ms': maxAge.inMilliseconds,
        'max_accuracy_m': maxAccuracyMeters,
      }),
    );
  }
}
