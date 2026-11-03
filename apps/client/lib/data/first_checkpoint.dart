import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import '../domain/campus_detector.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';

class FirstCheckpointGateway {
  FirstCheckpointGateway({
    required this.accountId,
    required this.logger,
    this.logReports = true,
  });
  final bool logReports;
  final String accountId;
  final AppLogger logger;
  static const deliveryChannelName =
      'br.ufmg.frequencia.frequencia_ufmg/checkpoint_delivery_events';
  static final Stream<Map<String, Object?>> deliveryUpdates =
      const EventChannel(deliveryChannelName).receiveBroadcastStream().map(
        (event) => Map<String, Object?>.from(event as Map),
      );
  static const channel = MethodChannel(
    'br.ufmg.frequencia.frequencia_ufmg/first_checkpoint',
  );
  Future<List<Map<String, Object?>>> perform(
    String action, [
    Map<String, Object?> fields = const {},
  ]) async {
    final id = newCorrelationId('firstCheckpoint');
    final watch = Stopwatch()..start();
    void log(String event, Map<String, Object?> details) {
      unawaited(
        logger
            .logEvent(
              event,
              parameters: {
                'operation_id': id,
                'action': action,
                'details': jsonEncode(details),
              },
            )
            .catchError((Object error) {
              debugPrint(
                'first_checkpoint_log_delivery_failed type=${error.runtimeType}',
              );
            }),
      );
    }

    log('first_checkpoint_action_started', {'stage': action, ...fields});
    try {
      final raw = await channel.invokeListMethod<Object?>(action, {
        'account_id': accountId,
        ...fields,
      });
      final reports = (raw ?? [])
          .map((value) => Map<String, Object?>.from(value! as Map))
          .toList();
      final captures = <Map<String, Object?>>[];
      for (final report in reports) {
        if (report.containsKey('notification_report')) {
          final metadata = report['notification_report'];
          if (metadata is Map && metadata['account_id'] == accountId) {
            if (logReports || action == 'read') {
              log(
                'checkpoint_notification_report',
                Map<String, Object?>.from(metadata),
              );
            }
          } else {
            log('checkpoint_notification_report_invalid', {
              'stage': action,
              'reason': 'invalid_or_foreign_notification_report',
            });
          }
        } else {
          captures.add(report);
          if (logReports || action == 'read') {
            log('first_checkpoint_report', {'stage': action, ...report});
          }
        }
      }
      log('first_checkpoint_action_succeeded', {
        'stage': action,
        'duration_ms': watch.elapsedMilliseconds,
        'report_count': captures.length,
      });
      return captures;
    } catch (error, stack) {
      unawaited(
        logger
            .recordError(
              error,
              stack,
              context: 'first_checkpoint_$action',
              parameters: {
                'operation_id': id,
                'action': action,
                'details': jsonEncode({
                  'stage': action,
                  'duration_ms': watch.elapsedMilliseconds,
                  ...fields,
                }),
              },
            )
            .catchError((Object e) {
              debugPrint(
                'first_checkpoint_log_delivery_failed type=${e.runtimeType}',
              );
            }),
      );
      rethrow;
    }
  }

  static Future<void> deactivate() async {
    await channel.invokeMethod<void>('deactivate');
  }

  static List<Map<String, double>> rectangles(CampusArea campus) => [
    for (final r in campus.rectangles)
      {'south': r.south, 'north': r.north, 'west': r.west, 'east': r.east},
  ];
}
