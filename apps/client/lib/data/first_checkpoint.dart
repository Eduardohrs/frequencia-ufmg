import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import '../domain/campus_detector.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';

class FirstCheckpointGateway {
  FirstCheckpointGateway({required this.accountId, required this.logger});
  final String accountId;
  final AppLogger logger;
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
      for (final report in reports) {
        log('first_checkpoint_report', {'stage': action, ...report});
      }
      log('first_checkpoint_action_succeeded', {
        'stage': action,
        'duration_ms': watch.elapsedMilliseconds,
        'report_count': reports.length,
      });
      return reports;
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
