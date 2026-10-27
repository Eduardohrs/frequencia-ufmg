import 'error_log_details.dart';

Map<String, Object>? sanitizeAnalyticsParameters(
  Map<String, Object>? parameters,
) => parameters?.map(
  (key, value) => MapEntry(key, switch (value) {
    bool value => value ? 1 : 0,
    String value => sanitizeLogText(value) ?? '',
    _ => value,
  }),
);
