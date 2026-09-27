import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/firestore_configuration.dart';

void main() {
  test('web transport automatically falls back to long polling', () {
    expect(firestoreWebSettings.webExperimentalAutoDetectLongPolling, isTrue);
    expect(firestoreWebSettings.webExperimentalForceLongPolling, isNull);
  });
}
