abstract interface class OperationalLogStore {
  Future<void> add(String userId, Map<String, Object?> document);
}
