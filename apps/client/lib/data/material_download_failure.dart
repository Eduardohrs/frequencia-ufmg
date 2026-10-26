import 'dart:convert';
import '../observability/error_log_details.dart';
import 'material_file_cache.dart';

final class MaterialDownloadFailure extends StateError
    implements StructuredAppError {
  MaterialDownloadFailure({
    required this.fileId,
    required this.fileName,
    required this.code,
    required this.received,
    required this.total,
    this.stage = 'body_complete',
    this.attempt = 0,
    this.elapsedMs = 0,
    this.httpStatus = 0,
    this.workId = '',
  }) : super(code);

  factory MaterialDownloadFailure.fromProgress(
    MaterialDownloadProgress progress,
  ) => MaterialDownloadFailure(
    fileId: progress.id,
    fileName: progress.name,
    code: progress.failureCode.isEmpty ? 'unknown' : progress.failureCode,
    received: progress.downloaded,
    total: progress.total,
    stage: progress.stage,
    attempt: progress.attempt,
    elapsedMs: progress.elapsedMs,
    httpStatus: progress.httpStatus,
    workId: progress.workId,
  );

  final String fileId, fileName, code, stage;
  final int received, total, attempt, elapsedMs, httpStatus;
  final String workId;
  @override
  String get logCode => code;
  @override
  String get logMessage => 'Falha no download de $fileName';
  @override
  String get logDetails => jsonEncode({
    'file_id': fileId,
    if (workId.isNotEmpty) 'work_id': workId,
    'file_name': fileName,
    'stage': stage,
    'received_bytes': received,
    'reported_total_bytes': total,
    if (attempt > 0) 'attempt': attempt,
    if (elapsedMs > 0) 'elapsed_ms': elapsedMs,
    if (httpStatus > 0) 'http_status': httpStatus,
  });
}
