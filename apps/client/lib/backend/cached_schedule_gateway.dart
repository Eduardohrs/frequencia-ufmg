import '../data/cache_request_owner.dart';
import '../observability/operation_diagnostics.dart';
import 'dart:convert';

import '../observability/app_logger.dart';
import 'python_backend_transport.dart';

typedef CurrentScheduleUserId = String? Function();

abstract interface class ScheduleCache {
  Future<String?> read(String userId, String courseId);

  Future<void> write(String userId, String courseId, String value);

  Future<void> remove(String userId, String courseId);
}

final class CachedScheduleGateway implements LocalFirstScheduleGateway {
  const CachedScheduleGateway({
    required this.remote,
    required this.cache,
    required this.currentUserId,
    required this.logger,
  });

  final BackendScheduleGateway remote;
  final ScheduleCache cache;
  final CurrentScheduleUserId currentUserId;
  final AppLogger logger;

  @override
  Future<PythonSchedule> getSchedule(String courseId) async {
    final owner = CacheRequestOwner(currentUserId, logger, 'scheduleCache');
    try {
      final schedule = await remote.getSchedule(courseId);
      owner.requireCurrent('schedule_remote_read');
      await _writeBestEffort(courseId, schedule, owner);
      return schedule;
    } on CacheIdentityChanged {
      rethrow;
    } catch (remoteError, remoteStackTrace) {
      owner.requireCurrent('schedule_remote_failure');
      final schedule = await getCachedSchedule(courseId);
      owner.requireCurrent('schedule_cache_fallback');
      if (schedule != null) return schedule;
      Error.throwWithStackTrace(remoteError, remoteStackTrace);
    }
  }

  @override
  Future<PythonSchedule?> getCachedSchedule(String courseId) async {
    final owner = CacheRequestOwner(currentUserId, logger, 'scheduleCacheRead');
    final userId = owner.userId;
    if (userId == null) return null;
    late final String? encoded;
    try {
      encoded = await cache.read(userId, courseId);
    } catch (error, stackTrace) {
      _error(error, stackTrace, 'schedule_cache_read');
      return null;
    }
    if (!owner.accepts('schedule_cache_read')) return null;
    if (encoded == null) {
      _event('schedule_cache_miss');
      return null;
    }
    try {
      final schedule = _decode(encoded);
      _event('schedule_cache_hit');
      return schedule;
    } catch (error, stackTrace) {
      _error(error, stackTrace, 'schedule_cache_decode');
      await _removeBestEffort(userId, courseId);
      return null;
    }
  }

  @override
  Future<PythonSchedule> saveSchedule({
    required String courseId,
    required DateTime? startsOn,
    required DateTime? endsOn,
    required List<PythonMeeting> meetings,
    required bool confirmDestructive,
  }) async {
    final owner = CacheRequestOwner(currentUserId, logger, 'scheduleCacheSave');
    final schedule = await remote.saveSchedule(
      courseId: courseId,
      startsOn: startsOn,
      endsOn: endsOn,
      meetings: meetings,
      confirmDestructive: confirmDestructive,
    );
    owner.requireCurrent('schedule_remote_save');
    await _writeBestEffort(courseId, schedule, owner);
    return schedule;
  }

  Future<void> _writeBestEffort(
    String courseId,
    PythonSchedule schedule,
    CacheRequestOwner owner,
  ) async {
    final userId = owner.userId;
    if (userId == null) return;
    try {
      await cache.write(userId, courseId, _encode(schedule));
      owner.requireCurrent('schedule_cache_write');
      _event('schedule_cache_write_succeeded');
    } on CacheIdentityChanged {
      rethrow;
    } catch (error, stackTrace) {
      owner.requireCurrent('schedule_cache_write_failure');
      _error(error, stackTrace, 'schedule_cache_write');
    }
  }

  Future<void> _removeBestEffort(String userId, String courseId) async {
    try {
      await cache.remove(userId, courseId);
    } catch (error, stackTrace) {
      _error(error, stackTrace, 'schedule_cache_remove');
    }
  }

  void _event(String name) =>
      emitOperationalEvent(logger, name, {'stage': name});

  void _error(Object error, StackTrace stackTrace, String context) =>
      recordOperationalFailure(logger, error, stackTrace, context, {
        'stage': context,
      }, failureCode: context);
}

String _encode(PythonSchedule schedule) => jsonEncode({
  'version': 1,
  'schedule': {
    'course': _courseJson(schedule.course),
    'meetings': [
      for (final meeting in schedule.meetings) _meetingJson(meeting),
    ],
    'changes': _changesJson(schedule.changes),
  },
});

PythonSchedule _decode(String encoded) {
  final root = Map<String, Object?>.from(jsonDecode(encoded) as Map);
  if (root.length != 2 ||
      root['version'] != 1 ||
      !root.containsKey('schedule')) {
    throw const FormatException();
  }
  final schedule = PythonSchedule.fromJson(
    Map<String, Object?>.from(root['schedule']! as Map),
  );
  return PythonSchedule(
    course: schedule.course,
    meetings: schedule.meetings,
    changes: schedule.changes,
    isLocalCopy: true,
  );
}

Map<String, Object?> _courseJson(PythonCourse course) => {
  'modality': course.modality,
  'attendance_policy': course.attendancePolicy,
  'id': course.id,
  'code': course.code,
  'name': course.name,
  'workload': course.workload,
  'term': course.term,
  'starts_on': course.startsOn?.toUtc().toIso8601String(),
  'ends_on': course.endsOn?.toUtc().toIso8601String(),
  'created_at': course.createdAt.toUtc().toIso8601String(),
  'updated_at': course.updatedAt.toUtc().toIso8601String(),
};

Map<String, Object?> _meetingJson(PythonMeeting meeting) => {
  'id': meeting.id,
  'weekday': meeting.weekday,
  'start_minutes': meeting.startMinutes,
  'end_minutes': meeting.endMinutes,
  'lesson_count': meeting.lessonCount,
  'call_count': meeting.callCount,
  'created_at': meeting.createdAt.toUtc().toIso8601String(),
  'updated_at': meeting.updatedAt.toUtc().toIso8601String(),
};

Map<String, Object> _changesJson(PythonScheduleChanges changes) => {
  'meeting_upserts': changes.meetingUpserts,
  'meeting_deletes': changes.meetingDeletes,
  'session_upserts': changes.sessionUpserts,
  'session_deletes': changes.sessionDeletes,
  'destructive_deletes': changes.destructiveDeletes,
};
