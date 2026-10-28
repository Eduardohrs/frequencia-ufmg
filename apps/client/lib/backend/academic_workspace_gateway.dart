part of 'python_backend_transport.dart';

abstract interface class BackendCourseSyncPolicyGateway {
  Future<bool> coursePlanSyncPaused(String courseId);
  Future<void> setCoursePlanSyncPaused(String courseId, {required bool paused});
}

abstract interface class BackendAcademicWorkspaceGateway {
  Future<PythonCourseActivitySnapshot> loadCourseActivitySnapshot(
    String courseId,
  );
  Future<List<PythonMoodleDate>> listCourseDates(String courseId);
  Future<void> saveCourseDate(
    String courseId,
    String dateId, {
    required String title,
    required DateTime dueAt,
    required String kind,
  });
  Future<void> deleteCourseDate(String courseId, String dateId);
  Future<Map<String, Object?>?> loadCoursePlan(String courseId);
  Future<List<PythonMoodleActivity>> listCourseActivities(String courseId);
  Future<PythonMoodleActivityDetail> loadCourseActivity(
    String courseId,
    String sourceId,
  );
}

final class PythonCourseActivitySnapshot {
  PythonCourseActivitySnapshot.fromJson(Map<String, Object?> value)
    : courseId = value['course_id']! as String,
      term = value['term']! as String,
      syncedAt = _utcDate(value['synced_at']),
      details = List.unmodifiable(
        (value['activities']! as List).map(
          (e) => PythonMoodleActivityDetail.fromJson(
            Map<String, Object?>.from(e as Map),
          ),
        ),
      ) {
    if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(courseId) ||
        !RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term) ||
        details.length > 500 ||
        details.map((e) => e.activity.id).toSet().length != details.length) {
      throw const FormatException('Invalid activity snapshot');
    }
    for (final raw in value['activities']! as List) {
      if ((raw as Map)['files'] is! List ||
          (raw['files'] as List).isNotEmpty ||
          raw['term'] != term) {
        throw const FormatException(
          'Snapshot must not contain download credentials',
        );
      }
    }
  }
  final String courseId, term;
  final DateTime syncedAt;
  final List<PythonMoodleActivityDetail> details;
  List<PythonMoodleActivity> get activities => [
    for (final detail in details) detail.activity,
  ];
  Map<String, Object?> toJson() => {
    'course_id': courseId,
    'term': term,
    'synced_at': syncedAt.toIso8601String(),
    'activities': [
      for (final detail in details)
        {
          'source_id': detail.activity.id,
          'title': detail.activity.title,
          'kind': detail.activity.kind,
          'url': detail.activity.url.toString(),
          'origin': detail.activity.origin,
          'description': detail.description,
          'dates_text': detail.datesText,
          'has_due_date': detail.hasDueDate,
          'submission_state': detail.submissionState,
          'submission_text': detail.submissionText,
          'term': detail.term,
          'attachments': [
            for (final name in detail.attachmentNames) {'name': name},
          ],
          'files': [],
        },
    ],
  };
}

final class PythonMoodleActivity {
  const PythonMoodleActivity({
    required this.id,
    required this.title,
    required this.kind,
    required this.url,
    this.origin = 'canonical',
  });
  factory PythonMoodleActivity.fromJson(Map<String, Object?> value) {
    final id = value['source_id'];
    final title = value['title'];
    final kind = value['kind'];
    final rawUrl = value['url'];
    final origin = value['origin'] ?? 'canonical';
    final url = rawUrl is String ? Uri.tryParse(rawUrl) : null;
    if (id is! String ||
        !RegExp(r'^[1-9][0-9]{0,9}$').hasMatch(id) ||
        title is! String ||
        title.trim().isEmpty ||
        title.length > 1024 ||
        !const {'assign', 'quiz'}.contains(kind) ||
        url == null ||
        url.scheme != 'https' ||
        url.host != 'virtual.ufmg.br' ||
        url.hasPort ||
        url.userInfo.isNotEmpty ||
        url.hasFragment ||
        url.pathSegments.length != 4 ||
        !_moodlePeriod.hasMatch(url.pathSegments[0]) ||
        url.pathSegments[1] != 'mod' ||
        url.pathSegments[2] != kind ||
        url.pathSegments[3] != 'view.php' ||
        url.queryParameters.length != 1 ||
        url.queryParameters['id'] != id ||
        !const {'canonical', 'metaturma'}.contains(origin)) {
      throw const FormatException('Invalid course activity');
    }
    return PythonMoodleActivity(
      id: id,
      title: title,
      kind: kind! as String,
      url: url,
      origin: origin as String,
    );
  }
  final String id, title, kind, origin;
  final Uri url;
}

final class PythonMoodleActivityDetail {
  const PythonMoodleActivityDetail({
    required this.activity,
    required this.description,
    required this.datesText,
    required this.hasDueDate,
    required this.submissionState,
    required this.submissionText,
    required this.files,
    required this.attachmentCount,
    required this.term,
    this.attachmentNames = const [],
  });
  factory PythonMoodleActivityDetail.fromJson(Map<String, Object?> value) {
    final activity = PythonMoodleActivity.fromJson(value);
    String text(String key, int maximum) {
      final v = value[key];
      if (v is! String || v.length > maximum) throw const FormatException();
      return v;
    }

    final due = value['has_due_date'];
    final attachments = value['attachments'];
    final files = value['files'];
    final state = text('submission_state', 40);
    final term = text('term', 6);
    if (due is! bool ||
        attachments is! List ||
        attachments.length > 100 ||
        files is! List ||
        files.length > 100 ||
        !const {
          'submitted',
          'not_submitted',
          'draft',
          'unknown',
        }.contains(state) ||
        !RegExp(r'^20[2-9][0-9]-[12]$').hasMatch(term)) {
      throw const FormatException();
    }
    return PythonMoodleActivityDetail(
      activity: activity,
      description: text('description', 20000),
      datesText: text('dates_text', 2000),
      hasDueDate: due,
      submissionState: state,
      submissionText: text('submission_text', 500),
      files: List.unmodifiable(
        files.map(
          (e) => PythonMoodleMaterialFile.fromJson(
            Map<String, Object?>.from(e as Map),
          ),
        ),
      ),
      attachmentCount: attachments.length,
      attachmentNames: List.unmodifiable(
        attachments.map(
          (e) =>
              e is Map && e['name'] is String ? e['name'] as String : 'Anexo',
        ),
      ),
      term: term,
    );
  }
  final PythonMoodleActivity activity;
  final String description, datesText, submissionState, submissionText, term;
  final bool hasDueDate;
  final int attachmentCount;
  final List<String> attachmentNames;
  final List<PythonMoodleMaterialFile> files;
}

final class _AcademicWorkspaceTransport
    implements BackendAcademicWorkspaceGateway, BackendCourseSyncPolicyGateway {
  const _AcademicWorkspaceTransport(this.transport);
  final PythonBackendTransport transport;
  @override
  Future<bool> coursePlanSyncPaused(String courseId) async {
    final response = await transport._authenticatedRequest(
      path: _path(courseId, 'plan-sync'),
    );
    final value = Map<String, Object?>.from(jsonDecode(response.body) as Map);
    if (!_hasExactKeys(value, const {'paused'}) || value['paused'] is! bool) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
    return value['paused']! as bool;
  }

  @override
  Future<void> setCoursePlanSyncPaused(
    String courseId, {
    required bool paused,
  }) async {
    final response = await transport._authenticatedRequest(
      path: _path(courseId, 'plan-sync'),
      method: _BackendMethod.put,
      body: {'paused': paused},
    );
    final value = Map<String, Object?>.from(jsonDecode(response.body) as Map);
    if (value['paused'] != paused) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  String _path(String courseId, String section, [String? id]) {
    for (final segment in [courseId, ?id]) {
      if (!RegExp(r'^[A-Za-z0-9_-]{1,128}$').hasMatch(segment)) {
        throw ArgumentError('Invalid workspace identifier');
      }
    }
    return '/v1/courses/$courseId/$section${id == null ? '' : '/$id'}';
  }

  Future<T> _read<T>(
    String path,
    T Function(Map<String, Object?>) decode, {
    _BackendMethod method = _BackendMethod.get,
    Map<String, Object?>? body,
  }) async {
    final response = await transport._authenticatedRequest(
      path: path,
      method: method,
      body: body,
    );
    try {
      return decode(
        Map<String, Object?>.from(jsonDecode(response.body) as Map),
      );
    } catch (_) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
  }

  @override
  Future<PythonCourseActivitySnapshot> loadCourseActivitySnapshot(
    String courseId,
  ) => _read(_path(courseId, 'activities'), (value) {
    final snapshot = PythonCourseActivitySnapshot.fromJson(value);
    if (snapshot.courseId != courseId) throw const FormatException();
    return snapshot;
  });
  @override
  Future<List<PythonMoodleDate>> listCourseDates(String courseId) =>
      _read(_path(courseId, 'dates'), (value) {
        final dates = value['dates'];
        if (dates is! List || dates.length > 500) throw const FormatException();
        return List.unmodifiable(
          dates.map(
            (e) =>
                PythonMoodleDate.fromJson(Map<String, Object?>.from(e as Map)),
          ),
        );
      });
  @override
  Future<void> saveCourseDate(
    String courseId,
    String dateId, {
    required String title,
    required DateTime dueAt,
    required String kind,
  }) => _read(
    _path(courseId, 'dates', dateId),
    (value) {
      PythonMoodleDate.fromJson(
        Map<String, Object?>.from(value['date']! as Map),
      );
    },
    method: _BackendMethod.put,
    body: {
      'title': title,
      'due_at': dueAt.toUtc().toIso8601String(),
      'kind': kind,
    },
  );
  @override
  Future<void> deleteCourseDate(String courseId, String dateId) =>
      _read(_path(courseId, 'dates', dateId), (value) {
        if (value['deleted'] != true) throw const FormatException();
      }, method: _BackendMethod.delete);
  @override
  Future<Map<String, Object?>?> loadCoursePlan(String courseId) =>
      _read(_path(courseId, 'plan'), (value) {
        if (!value.containsKey('plan')) throw const FormatException();
        if (value['plan'] == null) return null;
        final saved = Map<String, Object?>.from(value['plan']! as Map);
        final plan = Map<String, Object?>.from(saved['plan']! as Map);
        if (plan['criteria'] is! List ||
            plan['schedule'] is! List ||
            plan['assessments'] is! List) {
          throw const FormatException();
        }
        for (final section in const ['criteria', 'schedule', 'assessments']) {
          final rows = plan[section]! as List;
          if (rows.length > 1000) throw const FormatException();
          final requiredFields = section == 'criteria'
              ? const ['description', 'value']
              : section == 'schedule'
              ? const ['subject', 'date', 'starts_at']
              : const ['title', 'scheduled_at', 'value'];
          for (final row in rows) {
            if (row is! Map) throw const FormatException();
            for (final field in requiredFields) {
              final v = row[field];
              if (v is! String || v.isEmpty || v.length > 500) {
                throw const FormatException();
              }
            }
          }
        }
        return plan;
      });
  @override
  Future<List<PythonMoodleActivity>> listCourseActivities(String courseId) =>
      _read(_path(courseId, 'activities'), (value) {
        final activities = value['activities'];
        if (activities is! List || activities.length > 500) {
          throw const FormatException();
        }
        return List.unmodifiable(
          activities.map(
            (e) => PythonMoodleActivity.fromJson(
              Map<String, Object?>.from(e as Map),
            ),
          ),
        );
      });
  @override
  Future<PythonMoodleActivityDetail> loadCourseActivity(
    String courseId,
    String sourceId,
  ) => _read(
    _path(courseId, 'activities', sourceId),
    PythonMoodleActivityDetail.fromJson,
  );
}
