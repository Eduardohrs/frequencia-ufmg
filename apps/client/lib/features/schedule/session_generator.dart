import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';

final class SessionReconciliation {
  const SessionReconciliation({
    required this.upserts,
    required this.deleteIds,
    required this.destructiveDeleteCount,
  });

  final List<SessionRecord> upserts;
  final List<String> deleteIds;
  final int destructiveDeleteCount;
}

final class SessionGenerator {
  const SessionGenerator(this.location);

  final tz.Location location;

  SessionReconciliation reconcile({
    required Iterable<MeetingRecord> meetings,
    required Iterable<SessionRecord> existingSessions,
    required DateTime startDate,
    required DateTime endDate,
    required DateTime now,
  }) {
    final desired = _buildDesired(
      meetings: meetings,
      startDate: startDate,
      endDate: endDate,
      now: now,
    );
    final desiredById = {for (final session in desired) session.id: session};
    final existingById = {
      for (final session in existingSessions) session.id: session,
    };
    final upserts = <SessionRecord>[];
    for (final generated in desired) {
      final existing = existingById[generated.id];
      if (existing == null) {
        upserts.add(generated);
      } else if (!_hasEvidence(existing) &&
          !_sameSchedule(existing, generated)) {
        upserts.add(
          SessionRecord(
            id: generated.id,
            startsAt: generated.startsAt,
            endsAt: generated.endsAt,
            lessonCount: generated.lessonCount,
            callCount: generated.callCount,
            calendarStatus: existing.calendarStatus,
            assessmentTitle: existing.assessmentTitle,
            createdAt: existing.createdAt,
            updatedAt: now.toUtc(),
          ),
        );
      }
    }
    final obsolete =
        existingSessions
            .where(
              (session) =>
                  _isGeneratedId(session.id) &&
                  !desiredById.containsKey(session.id),
            )
            .toList()
          ..sort((left, right) => left.id.compareTo(right.id));
    return SessionReconciliation(
      upserts: List.unmodifiable(upserts),
      deleteIds: List.unmodifiable(obsolete.map((session) => session.id)),
      destructiveDeleteCount: obsolete.where(_hasEvidence).length,
    );
  }

  List<SessionRecord> generateMissing({
    required Iterable<MeetingRecord> meetings,
    required Iterable<SessionRecord> existingSessions,
    required DateTime startDate,
    required DateTime endDate,
    required tz.TZDateTime notBefore,
    required DateTime now,
  }) {
    final existingIds = {for (final session in existingSessions) session.id};
    return _buildDesired(
      meetings: meetings,
      startDate: startDate,
      endDate: endDate,
      now: now,
    ).where((session) {
      final startsAt = tz.TZDateTime.from(session.startsAt, location);
      return !startsAt.isBefore(notBefore) && !existingIds.contains(session.id);
    }).toList();
  }

  List<SessionRecord> _buildDesired({
    required Iterable<MeetingRecord> meetings,
    required DateTime startDate,
    required DateTime endDate,
    required DateTime now,
  }) {
    final firstDay = _date(startDate);
    final lastDay = _date(endDate);
    if (lastDay.isBefore(firstDay)) {
      throw ArgumentError('endDate cannot precede startDate');
    }
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
        final id = '${_dateId(day)}--${meeting.id}';
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

bool _isGeneratedId(String id) =>
    RegExp(r'^\d{4}-\d{2}-\d{2}--.+$').hasMatch(id);

bool _hasEvidence(SessionRecord session) =>
    session.firstPing != null ||
    session.secondPing != null ||
    session.attendanceStatus != null ||
    session.absences != null;

bool _sameSchedule(SessionRecord left, SessionRecord right) =>
    left.startsAt == right.startsAt &&
    left.endsAt == right.endsAt &&
    left.lessonCount == right.lessonCount &&
    left.callCount == right.callCount;

String _dateId(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';
