/// Read-only summary of the current account's local checkpoint reports.
class CheckpointDiagnostics {
  CheckpointDiagnostics(List<Map<String, Object?>> reports) {
    final scheduled =
        reports
            .where(
              (r) => _capturing(r) && r['checkpoint_expected_at_ms'] is int,
            )
            .toList()
          ..sort(
            (a, b) => (a['checkpoint_expected_at_ms'] as int).compareTo(
              b['checkpoint_expected_at_ms'] as int,
            ),
          );
    next = scheduled.firstOrNull;
    pendingUploads = reports
        .where(
          (r) =>
              r['delivery_enabled'] == true &&
              !_capturing(r) &&
              !delivered.contains(r['delivery_status']),
        )
        .length;
    for (final r in reports) {
      final status = r['status'];
      final captureFailed =
          status is String &&
          !const {
            'scheduled',
            'running',
            'succeeded',
            'cancelled',
            'superseded',
          }.contains(status);
      final deliveryFailed = const {
        'retry',
        'rejected',
        'unresolved',
      }.contains(r['delivery_status']);
      if ((captureFailed || deliveryFailed) &&
          (lastProblem == null || _time(r) > _time(lastProblem!))) {
        lastProblem = r;
      }
    }
  }
  static const delivered = {
    'applied',
    'already_applied',
    'preserved',
    'unresolved',
    'discarded',
    'rejected',
  };
  late final Map<String, Object?>? next;
  late final int pendingUploads;
  Map<String, Object?>? lastProblem;
  static bool _capturing(Map<String, Object?> r) =>
      const {'scheduled', 'running'}.contains(r['status']);
  static int _time(Map<String, Object?> r) => [
    r['delivery_updated_at_ms'],
    r['updated_at_ms'],
    r['captured_at_ms'],
    r['scheduled_at_ms'],
  ].whereType<int>().fold(0, (a, b) => a > b ? a : b);
  Map<String, Object?> get logFields => {
    'next_operation_id': next?['operation_id'],
    'next_expected_at_ms': next?['checkpoint_expected_at_ms'],
    'pending_uploads': pendingUploads,
    'problem_operation_id': lastProblem?['operation_id'],
    'problem_status': lastProblem?['status'],
    'problem_delivery_status': lastProblem?['delivery_status'],
  };
  Map<String, Object?> get problemDetails => {
    for (final field in const [
      'operation_id',
      'course_code',
      'session_id',
      'moment',
      'status',
      'stage',
      'cause_type',
      'cause_message',
      'updated_at_ms',
      'checkpoint_expected_at_ms',
      'delivery_status',
      'delivery_reason',
      'delivery_stage',
      'delivery_request_id',
      'delivery_http_status',
      'delivery_attempt',
      'delivery_duration_ms',
      'delivery_timings',
      'delivery_enqueue_failure',
    ])
      if (lastProblem?.containsKey(field) == true) field: lastProblem![field],
  };
}
