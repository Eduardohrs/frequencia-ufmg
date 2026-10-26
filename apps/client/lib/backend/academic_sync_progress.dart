import 'python_backend_transport.dart';

abstract interface class BackendAcademicSyncProgressGateway
    implements BackendUnifiedAcademicSyncGateway {
  Future<PythonUnifiedAcademicSyncResult> syncWithProgress(String operationId);
  Stream<AcademicSyncProgress> watchSyncProgress(String operationId);
}

final class AcademicSyncProgress {
  const AcademicSyncProgress({
    required this.operationId,
    required this.completed,
    required this.status,
    this.reviewRequired = 0,
  });

  factory AcademicSyncProgress.fromMap(Map<String, Object?> data) {
    final id = data['operationId'];
    final completed = data['completed'];
    final status = data['status'];
    final reviews = data['reviewRequired'];
    if (id is! String ||
        !RegExp(r'^[A-Za-z0-9_-]{8,80}$').hasMatch(id) ||
        completed is! int ||
        completed < 0 ||
        completed > 3 ||
        !['running', 'succeeded', 'partial', 'failed'].contains(status) ||
        reviews is! int ||
        reviews < 0 ||
        reviews > 50 ||
        (status == 'succeeded' || status == 'partial') && completed != 3) {
      throw const FormatException('Invalid sync progress');
    }
    return AcademicSyncProgress(
      operationId: id,
      completed: completed,
      status: status as String,
      reviewRequired: reviews,
    );
  }

  final String operationId;
  final int completed;
  final String status;
  final int reviewRequired;
}
