import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';
import '../observability/operation_diagnostics.dart';

/// A cache request belongs to the account that started it, including fallbacks.
final class CacheRequestOwner {
  CacheRequestOwner(this.currentUserId, this.logger, String operation)
    : userId = currentUserId(),
      operationId = newCorrelationId(operation);

  final String? Function() currentUserId;
  final AppLogger logger;
  final String? userId;
  final String operationId;

  bool accepts(String stage) {
    final activeUserId = currentUserId();
    if (activeUserId == userId) return true;
    emitOperationalEvent(logger, 'academic_cache_result_discarded', {
      'operation_id': operationId,
      'stage': stage,
      'reason': 'authenticated_user_changed',
      'requested_user_id': userId ?? 'none',
      'active_user_id': activeUserId ?? 'none',
    });
    return false;
  }

  void requireCurrent(String stage) {
    if (!accepts(stage)) throw CacheIdentityChanged();
  }
}

final class CacheIdentityChanged extends StateError {
  CacheIdentityChanged()
    : super('Authenticated account changed during cache request');
}
