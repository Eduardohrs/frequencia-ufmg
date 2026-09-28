import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';

final class SessionGenerator {
  const SessionGenerator(this.location);

  final tz.Location location;

  List<SessionRecord> generateMissing({
    required Iterable<MeetingRecord> meetings,
    required Iterable<SessionRecord> existingSessions,
    required DateTime startDate,
    required DateTime endDate,
    required tz.TZDateTime notBefore,
    required DateTime now,
  }) {
    final firstDay = _date(startDate);
    final lastDay = _date(endDate);
    if (lastDay.isBefore(firstDay)) {
      throw ArgumentError('endDate cannot precede startDate');
    }

    final existingIds = {for (final session in existingSessions) session.id};
    final timestamp = now.toUtc();
    final generated = <SessionRecord>[];
    for (
      var day = firstDay;
      !day.isAfter(lastDay);
      day = day.add(const Duration(days: 1))
    ) {
      for (final meeting in meetings) {
        if (meeting.weekday != day.weekday) continue;
        final startsAt = tz.TZDateTime(
          location,
          day.year,
          day.month,
          day.day,
          meeting.startMinutes ~/ 60,
          meeting.startMinutes % 60,
        );
        if (startsAt.isBefore(notBefore)) continue;
        final id = '${_dateId(day)}--${meeting.id}';
        if (existingIds.contains(id)) continue;
        generated.add(
          SessionRecord(
            id: id,
            startsAt: startsAt.toUtc(),
            endsAt: startsAt
                .add(
                  Duration(minutes: meeting.endMinutes - meeting.startMinutes),
                )
                .toUtc(),
            lessonCount: meeting.lessonCount,
            callCount: meeting.callCount,
            createdAt: timestamp,
            updatedAt: timestamp,
          ),
        );
      }
    }
    generated.sort((left, right) => left.startsAt.compareTo(right.startsAt));
    return generated;
  }

  tz.TZDateTime _date(DateTime date) =>
      tz.TZDateTime(location, date.year, date.month, date.day);
}

String _dateId(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';
