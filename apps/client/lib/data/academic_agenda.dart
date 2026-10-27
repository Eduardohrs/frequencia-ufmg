import 'dart:async';
import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';

import '../backend/python_backend_transport.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../observability/error_log_details.dart';
import 'academic_records.dart';
import 'calendar_status.dart';
import 'document_store.dart';
import 'firestore_schema.dart';

abstract interface class AcademicDateRepository {
  Future<List<PythonMoodleDate>> listDates(String courseId);
}

final class FirestoreAcademicDateRepository implements AcademicDateRepository {
  const FirestoreAcademicDateRepository({
    required this.userId,
    required this.store,
    required this.logger,
  });

  final String userId;
  final DocumentStore store;
  final AppLogger logger;

  @override
  Future<List<PythonMoodleDate>> listDates(
    String courseId,
  ) => runAuditedOperation(
    logger: logger,
    operation: AuditedOperation.moodleDateList,
    action: () async {
      final timer = Stopwatch()..start();
      final parameters = <String, Object>{
        'course_id': courseId,
        'operation_id': currentOperationId!,
        'stage': 'store_read',
      };
      try {
        final documents = await store.list(
          '${FirestoreSchema.courseDocument(userId, courseId)}/academicDates',
        );
        if (documents.length > 500) {
          throw const FormatException('Too many academic dates');
        }
        final dates = <PythonMoodleDate>[];
        parameters['stage'] = 'date_document_decode';
        for (final document in documents) {
          parameters['document_id'] = document.id;
          if (document.data['schemaVersion'] != 1) {
            throw const FormatException('Invalid academic date schema version');
          }
          dates.add(
            PythonMoodleDate.fromJson({
              'id': document.id,
              'course_id': courseId,
              'course_code': courseId,
              'title': document.data['title'],
              'kind': document.data['kind'],
              'source': document.data['source'],
              'source_id': document.data['sourceId'],
              'due_at': _instant(document.data['dueAt']),
              'created_at': _instant(document.data['createdAt']),
              'updated_at': _instant(document.data['updatedAt']),
            }),
          );
        }
        parameters.remove('document_id');
        parameters['stage'] = 'academic_dates_read';
        emitAgendaEvent(logger, 'agenda_dates_read_succeeded', {
          ...parameters,
          'count': dates.length,
          'duration_ms': timer.elapsedMilliseconds,
        });
        return dates;
      } catch (error, stack) {
        recordAgendaFailure(logger, error, stack, 'agenda_dates_read', {
          ...parameters,
          'duration_ms': timer.elapsedMilliseconds,
          'reason': error is FormatException
              ? 'invalid_date_document'
              : 'store_read_failed',
        });
        rethrow;
      }
    },
  );
}

String _instant(Object? value) {
  if (value is! Timestamp) {
    throw const FormatException('Invalid academic date timestamp');
  }
  return value.toDate().toUtc().toIso8601String();
}

void _deliver(Future<void> delivery) =>
    unawaited(delivery.catchError((Object _) {}));

/// Presentation only: never creates attendance sessions for standalone deadlines.
final class AgendaEntry {
  const AgendaEntry({required this.startsAt, this.title, this.session});
  final DateTime startsAt;
  final String? title;
  final SessionRecord? session;
}

List<AgendaEntry> courseAgenda(
  CourseRecord course,
  List<SessionRecord> sessions,
  List<PythonMoodleDate> dates, {
  bool includeLessons = false,
}) {
  final entries = <AgendaEntry>[];
  final unique = <String, PythonMoodleDate>{};
  for (final date in dates) {
    if (date.courseId != course.id) continue;
    unique.putIfAbsent(
      '${date.dueAt.toUtc().microsecondsSinceEpoch}|${_title(date.title)}',
      () => date,
    );
  }
  final remaining = unique.values.toList();
  for (final session in sessions) {
    if (course.modality == CourseModality.online ||
        session.calendarStatus == SessionCalendarStatus.cancelled ||
        session.calendarStatus == SessionCalendarStatus.holiday) {
      continue;
    }
    final title = session.assessmentTitle;
    if (!includeLessons && title == null) continue;
    final index = title == null
        ? -1
        : remaining.indexWhere(
            (date) =>
                _title(date.title) == _title(title) &&
                !date.dueAt.isBefore(session.startsAt) &&
                date.dueAt.isBefore(session.endsAt),
          );
    final linked = index < 0 ? null : remaining.removeAt(index);
    entries.add(
      AgendaEntry(
        startsAt: linked?.dueAt ?? session.startsAt,
        title: linked?.title ?? title,
        session: session,
      ),
    );
  }
  entries.addAll(
    remaining.map(
      (date) => AgendaEntry(startsAt: date.dueAt, title: date.title),
    ),
  );
  entries.sort((a, b) {
    final time = a.startsAt.compareTo(b.startsAt);
    return time != 0 ? time : (a.title ?? '').compareTo(b.title ?? '');
  });
  return entries;
}

String _title(String value) =>
    value.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

void recordAgendaPresentation({
  required AppLogger logger,
  required String screen,
  required int importedCount,
  required int entryCount,
  required Iterable<String> unavailableCourses,
  bool isLocalCopy = false,
}) => emitAgendaEvent(logger, 'agenda_presented', {
  'operation_id': newCorrelationId('agenda'),
  'stage': 'presentation',
  'screen': screen,
  'imported_count': importedCount,
  'entry_count': entryCount,
  'unavailable_count': unavailableCourses.length,
  'unavailable_courses': unavailableCourses.take(50).join(','),
  'is_local_copy': isLocalCopy,
});

void emitAgendaEvent(
  AppLogger logger,
  String event,
  Map<String, Object> fields,
) => _deliver(
  Future<void>.sync(
    () => logger.logEvent(
      event,
      parameters: {...fields, 'details': _agendaDetails(fields)},
    ),
  ),
);

void recordAgendaFailure(
  AppLogger logger,
  Object error,
  StackTrace stack,
  String context,
  Map<String, Object> fields,
) => _deliver(
  Future<void>.sync(
    () => logger.recordError(
      _AgendaReadFailure(error, fields),
      stack,
      context: context,
      parameters: fields,
    ),
  ),
);

String _agendaDetails(Map<String, Object> fields) {
  final details = Map<String, Object>.of(fields)
    ..remove('operation_id')
    ..remove('duration_ms')
    ..remove('screen');
  var encoded = jsonEncode(details);
  if (encoded.length <= 500) return encoded;
  details['truncated'] = true;
  // Shrink values before encoding; never cut the serialized JSON in the store.
  while ((encoded = jsonEncode(details)).length > 500) {
    final longest = details.entries
        .where((e) => e.value is String)
        .reduce(
          (a, b) =>
              (a.value as String).length >= (b.value as String).length ? a : b,
        );
    final value = longest.value as String;
    details[longest.key] = value.substring(0, value.length ~/ 2);
  }
  return encoded;
}

final class _AgendaReadFailure implements StructuredAppError {
  _AgendaReadFailure(this.cause, Map<String, Object> fields)
    : fields = Map.unmodifiable(fields);
  final Object cause;
  final Map<String, Object> fields;
  @override
  String get logCode => 'agenda_read_failed';
  @override
  String? get logMessage => ErrorLogDetails.from(cause).message;
  @override
  String get logDetails {
    final error = ErrorLogDetails.from(cause);
    return _agendaDetails({
      ...fields,
      'cause_type': error.type,
      'cause_code': ?error.code,
    });
  }
}
