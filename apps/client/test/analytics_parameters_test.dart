import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/observability/analytics_parameters.dart';

void main() {
  test('permission flags remain SDK-valid while secrets are redacted', () {
    final result = sanitizeAnalyticsParameters({
      'precise_location': true,
      'background_location': false,
      'sdk': 36,
      'duration': 1.5,
      'message': 'stage=read password=unsafe-example',
    });
    expect(result?['precise_location'], 1);
    expect(result?['background_location'], 0);
    expect(result?['sdk'], 36);
    expect(result?['duration'], 1.5);
    expect(
      result?['message'],
      allOf(contains('stage=read'), isNot(contains('unsafe-example'))),
    );
    expect(result!.values.every((v) => v is String || v is num), isTrue);
    expect(sanitizeAnalyticsParameters(null), isNull);
  });
}
