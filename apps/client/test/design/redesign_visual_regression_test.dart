import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/app_theme.dart';
import 'package:frequencia_ufmg/design/design_catalog.dart';

void main() {
  Future<void> expectCatalogGolden(
    WidgetTester tester, {
    required Size size,
    required ThemeMode themeMode,
    required bool highContrast,
    required double textScale,
    required String golden,
  }) async {
    await tester.binding.setSurfaceSize(size);
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(highContrast: highContrast),
        darkTheme: AppTheme.dark(highContrast: highContrast),
        themeMode: themeMode,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            highContrast: highContrast,
            textScaler: TextScaler.linear(textScale),
            disableAnimations: true,
          ),
          child: child!,
        ),
        home: RepaintBoundary(
          key: const ValueKey('visual-catalog'),
          child: DesignCatalogPage(key: UniqueKey()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
    await expectLater(tester, meetsGuideline(textContrastGuideline));
    await expectLater(
      find.byKey(const ValueKey('visual-catalog')),
      matchesGoldenFile(golden),
    );
    expect(tester.takeException(), isNull);
  }

  testWidgets('phone light visual baseline', (tester) async {
    await expectCatalogGolden(
      tester,
      size: const Size(390, 844),
      themeMode: ThemeMode.light,
      highContrast: false,
      textScale: 1,
      golden: 'goldens/design_catalog_phone_light.png',
    );
  });

  testWidgets('phone dark baseline remains calm with enlarged text', (
    tester,
  ) async {
    await expectCatalogGolden(
      tester,
      size: const Size(390, 844),
      themeMode: ThemeMode.dark,
      highContrast: false,
      textScale: 2,
      golden: 'goldens/design_catalog_phone_dark_large_text.png',
    );
  });

  testWidgets('desktop high contrast visual baseline', (tester) async {
    await expectCatalogGolden(
      tester,
      size: const Size(1440, 900),
      themeMode: ThemeMode.light,
      highContrast: true,
      textScale: 1,
      golden: 'goldens/design_catalog_desktop_high_contrast.png',
    );
  });
}
