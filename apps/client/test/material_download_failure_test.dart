import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/material_download_failure.dart';
import 'package:frequencia_ufmg/data/material_file_cache.dart';
import 'package:frequencia_ufmg/observability/error_log_details.dart';

void main() {
  test(
    'native failures preserve actionable diagnostics through the logger',
    () {
      const progress = MaterialDownloadProgress(
        id: 'course/plan',
        name: 'Plano.pdf',
        state: MaterialDownloadState.failed,
        downloaded: 3,
        total: 11,
        failureCode: 'incomplete_body',
        stage: 'body_complete',
        attempt: 2,
        elapsedMs: 1234,
        httpStatus: 200,
        workId: 'work-uuid',
      );
      final details = ErrorLogDetails.from(
        MaterialDownloadFailure.fromProgress(progress),
      );
      expect(progress.failureKey, 'work-uuid');
      expect(details.code, 'incomplete_body');
      expect(details.message, contains('Plano.pdf'));
      expect(jsonDecode(details.details!), {
        'file_id': 'course/plan',
        'file_name': 'Plano.pdf',
        'work_id': 'work-uuid',
        'stage': 'body_complete',
        'received_bytes': 3,
        'reported_total_bytes': 11,
        'attempt': 2,
        'elapsed_ms': 1234,
        'http_status': 200,
      });
    },
  );

  test('older native results retain safe diagnostic defaults', () {
    const progress = MaterialDownloadProgress(
      id: 'file',
      name: 'File.pdf',
      state: MaterialDownloadState.failed,
      downloaded: 0,
      total: 0,
    );
    expect(progress.failureKey, 'file');
    final failure = MaterialDownloadFailure.fromProgress(progress);
    expect(failure.logCode, 'unknown');
    expect(jsonDecode(failure.logDetails), {
      'file_id': 'file',
      'file_name': 'File.pdf',
      'stage': 'native_worker',
      'received_bytes': 0,
      'reported_total_bytes': 0,
    });
  });
}
