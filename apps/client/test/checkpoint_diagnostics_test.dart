import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/checkpoint_diagnostics.dart';

void main() {
  test(
    'local diagnostics identify actual schedules, delivery and latest problem',
    () {
      final older = {
        'status': 'location_timeout',
        'updated_at_ms': 10,
        'operation_id': 'old',
      };
      final latest = {
        'status': 'succeeded',
        'delivery_enabled': true,
        'delivery_status': 'retry',
        'delivery_updated_at_ms': 20,
        'operation_id': 'new',
      };
      final next = {
        'status': 'scheduled',
        'checkpoint_expected_at_ms': 200,
        'operation_id': 'next',
      };
      final d = CheckpointDiagnostics([
        older,
        latest,
        next,
        {'status': 'scheduled', 'checkpoint_expected_at_ms': 300},
      ]);
      expect(d.next, same(next));
      expect(d.pendingUploads, 1);
      expect(d.lastProblem, same(latest));
      expect(d.logFields['next_operation_id'], 'next');
      expect(d.logFields['problem_operation_id'], 'new');
      expect(d.logFields['pending_uploads'], 1);
    },
  );
  test(
    'intentional states and successful outside-campus pings are not failures',
    () {
      final d = CheckpointDiagnostics([
        for (final status in ['cancelled', 'superseded', 'succeeded'])
          {'status': status, 'first_ping': 'fora'},
        for (final delivery in [
          'applied',
          'already_applied',
          'preserved',
          'unresolved',
          'discarded',
          'rejected',
        ])
          {
            'status': 'succeeded',
            'delivery_enabled': true,
            'delivery_status': delivery,
            'delivery_updated_at_ms': delivery == 'rejected' ? 2 : 1,
          },
        {'status': 'scheduled', 'checkpoint_expected_at_ms': 'invalid'},
        {
          'status': 'running',
          'delivery_enabled': true,
          'delivery_status': 'pending',
        },
      ]);
      expect(d.next, isNull);
      expect(d.pendingUploads, 0);
      expect(d.lastProblem?['delivery_status'], 'rejected');
      expect(
        CheckpointDiagnostics([
          {'status': 'cancelled'},
          {'status': 'superseded'},
          {'status': 'succeeded', 'first_ping': 'fora'},
        ]).lastProblem,
        isNull,
      );
      expect(CheckpointDiagnostics([]).logFields['next_operation_id'], isNull);
      expect(CheckpointDiagnostics([]).problemDetails, isEmpty);
    },
  );
  test(
    'unknown timestamps are safe and disabled legacy deliveries do not join queue',
    () {
      final bad = {'status': 'enqueue_failed', 'updated_at_ms': 'unknown'};
      final active = {'status': 'running', 'checkpoint_expected_at_ms': 5};
      final d = CheckpointDiagnostics([
        bad,
        {'status': 'failed'},
        active,
        {'status': 'scheduled', 'checkpoint_expected_at_ms': 3},
        {'status': 'succeeded', 'delivery_status': 'pending'},
      ]);
      expect(d.lastProblem, same(bad));
      expect(d.next?['checkpoint_expected_at_ms'], 3);
      expect(d.pendingUploads, 0);
      expect(CheckpointDiagnostics([active]).next, same(active));
      expect(d.problemDetails, containsPair('status', 'enqueue_failed'));
    },
  );
}
