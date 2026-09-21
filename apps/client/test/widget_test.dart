import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/main.dart' as app;

void main() {
  testWidgets('shows the product name', (tester) async {
    app.main();
    await tester.pump();

    expect(find.text('Frequência UFMG'), findsOneWidget);
  });
}
