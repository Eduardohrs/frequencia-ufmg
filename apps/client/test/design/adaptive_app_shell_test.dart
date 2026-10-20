import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/adaptive_app_shell.dart';

void main() {
  Widget app({required double width, bool highContrast = false}) {
    return MaterialApp(
      home: MediaQuery(
        data: MediaQueryData(
          size: Size(width, 900),
          highContrast: highContrast,
        ),
        child: AdaptiveAppShell(
          title: 'Início',
          selectedIndex: 0,
          onDestinationSelected: (_) {},
          actions: const [
            IconButton(onPressed: null, icon: Icon(Icons.person)),
          ],
          body: const Text('Conteúdo'),
        ),
      ),
    );
  }

  testWidgets('uses bottom navigation below the desktop breakpoint', (
    tester,
  ) async {
    for (final width in [320.0, 768.0]) {
      await tester.binding.setSurfaceSize(Size(width, 900));
      await tester.pumpWidget(app(width: width));
      await tester.pump();

      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(NavigationRail), findsNothing);
      expect(find.byKey(const Key('app-shell-content')), findsOneWidget);
      expect(tester.takeException(), isNull, reason: 'width $width');
    }
    await tester.binding.setSurfaceSize(null);
  });

  testWidgets('uses a rail and bounded content at desktop widths', (
    tester,
  ) async {
    for (final width in [1024.0, 1440.0]) {
      await tester.binding.setSurfaceSize(Size(width, 900));
      await tester.pumpWidget(app(width: width));
      await tester.pump();

      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byKey(const Key('app-shell-content')), findsOneWidget);
      expect(tester.takeException(), isNull, reason: 'width $width');
    }
    await tester.binding.setSurfaceSize(null);
  });

  testWidgets('keeps established destination keys and reports selection', (
    tester,
  ) async {
    var selected = -1;
    await tester.binding.setSurfaceSize(const Size(390, 844));
    await tester.pumpWidget(
      MaterialApp(
        home: AdaptiveAppShell(
          title: 'Início',
          selectedIndex: 0,
          onDestinationSelected: (index) => selected = index,
          body: const Text('Conteúdo'),
        ),
      ),
    );

    expect(find.byKey(const Key('nav-home')), findsOneWidget);
    expect(find.byKey(const Key('nav-general-calendar')), findsOneWidget);
    expect(find.byKey(const Key('nav-absence-dashboard')), findsOneWidget);
    await tester.tap(find.byKey(const Key('nav-general-calendar')));
    expect(selected, 1);
    await tester.binding.setSurfaceSize(null);
  });

  testWidgets('uses an opaque navigation material in high contrast', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    await tester.pumpWidget(app(width: 390, highContrast: true));
    await tester.pump();

    final material = tester.widget<Material>(
      find.byKey(const Key('app-shell-navigation-material')),
    );
    expect(material.color?.a, 1);
    await tester.binding.setSurfaceSize(null);
  });
}
