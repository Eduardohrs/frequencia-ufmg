import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/app_theme.dart';
import 'package:frequencia_ufmg/design/course_identity.dart';
import 'package:frequencia_ufmg/design/design_catalog.dart';

void main() {
  test('light and dark themes expose the complete semantic foundation', () {
    for (final theme in [AppTheme.light(), AppTheme.dark()]) {
      expect(theme.useMaterial3, isTrue);
      expect(theme.extension<AppSemanticColors>(), isNotNull);
      expect(theme.extension<AppMotion>(), isNotNull);
      expect(theme.textTheme.titleLarge?.height, greaterThan(1));
      expect(theme.textTheme.bodyMedium?.height, greaterThan(1));
      expect(theme.cardTheme.elevation, 0);
    }

    expect(AppTheme.light().brightness, Brightness.light);
    expect(AppTheme.dark().brightness, Brightness.dark);
  });

  test('semantic extensions copy and interpolate every visual token', () {
    final light = AppTheme.light().extension<AppSemanticColors>()!;
    final dark = AppTheme.dark().extension<AppSemanticColors>()!;
    final copy = light.copyWith(
      success: Colors.green,
      warning: Colors.orange,
      info: Colors.blue,
      subtleSurface: Colors.white,
      separator: Colors.black,
    );

    expect(copy.success, Colors.green);
    expect(copy.warning, Colors.orange);
    expect(copy.info, Colors.blue);
    expect(copy.subtleSurface, Colors.white);
    expect(copy.separator, Colors.black);
    expect(light.copyWith().separator, light.separator);
    expect(light.lerp(null, .5), same(light));
    expect(light.lerp(dark, .5), isNot(light));

    const motion = AppMotion();
    const slower = AppMotion(
      feedback: Duration(seconds: 1),
      transition: Duration(seconds: 2),
    );
    expect(motion.copyWith().feedback, motion.feedback);
    expect(
      motion
          .copyWith(feedback: slower.feedback, transition: slower.transition)
          .transition,
      slower.transition,
    );
    expect(motion.lerp(null, .5), same(motion));
    expect(motion.lerp(slower, .25), same(motion));
    expect(motion.lerp(slower, .75), same(slower));
  });

  test(
    'course identities are stable and never communicate through color only',
    () {
      final calculus = CourseIdentity.fromCode('MAT245');
      final circuits = CourseIdentity.fromCode('ELE028');

      expect(CourseIdentity.fromCode(' mat245 '), calculus);
      expect(calculus.symbol, isNotEmpty);
      expect(calculus.label, isNotEmpty);
      expect(circuits.symbol, isNot(calculus.symbol));
      expect(circuits.color, isNot(calculus.color));
      expect(CourseIdentity.fromCode('DCC001').label, 'Computação');
      expect(CourseIdentity.fromCode('PDS001').label, 'Computação');
      expect(CourseIdentity.fromCode('LET001').label, isNotEmpty);
      expect(calculus.hashCode, CourseIdentity.fromCode('MAT245').hashCode);
      expect(calculus == Object(), isFalse);
    },
  );

  testWidgets('catalog supports dark mode, high contrast and enlarged text', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(highContrast: true),
        darkTheme: AppTheme.dark(highContrast: true),
        themeMode: ThemeMode.dark,
        home: MediaQuery(
          data: const MediaQueryData(textScaler: TextScaler.linear(2)),
          child: const DesignCatalogPage(),
        ),
      ),
    );

    expect(find.text('Fundações visuais'), findsOneWidget);
    expect(find.text('Cálculo III'), findsOneWidget);
    expect(find.byType(CourseMark), findsNWidgets(2));
    expect(
      tester.element(find.byType(DesignCatalogPage)).semanticColors.separator,
      isNotNull,
    );
    await tester.tap(find.text('Cálculo III'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('press feedback is immediate and respects reduced motion', (
    tester,
  ) async {
    var taps = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: MediaQuery(
          data: const MediaQueryData(disableAnimations: true),
          child: Scaffold(
            body: AppPressable(
              semanticLabel: 'Abrir disciplina',
              onPressed: () => taps += 1,
              child: const Text('Disciplina'),
            ),
          ),
        ),
      ),
    );

    final animatedScale = tester.widget<AnimatedScale>(
      find.byType(AnimatedScale),
    );
    expect(animatedScale.duration, Duration.zero);

    await tester.tap(find.text('Disciplina'));
    expect(taps, 1);
  });

  testWidgets('pressable animates press, cancellation, and disabled states', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Column(
            children: [
              AppPressable(
                semanticLabel: 'Ativo',
                onPressed: () {},
                child: const Text('Ativo'),
              ),
              const AppPressable(
                semanticLabel: 'Inativo',
                onPressed: null,
                child: Text('Inativo'),
              ),
            ],
          ),
        ),
      ),
    );

    final gesture = await tester.startGesture(
      tester.getCenter(find.text('Ativo')),
    );
    await tester.pump();
    expect(
      tester.widget<AnimatedScale>(find.byType(AnimatedScale).first).scale,
      .985,
    );
    await gesture.cancel();
    await tester.pump();
    expect(
      tester.widget<AnimatedScale>(find.byType(AnimatedScale).first).scale,
      1,
    );

    await tester.tap(find.text('Inativo'));
    expect(tester.takeException(), isNull);
  });

  testWidgets('pressable supports keyboard activation', (tester) async {
    var taps = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: AppPressable(
            semanticLabel: 'Abrir',
            onPressed: () => taps += 1,
            child: const Text('Abrir'),
          ),
        ),
      ),
    );

    await tester.sendKeyEvent(LogicalKeyboardKey.tab);
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();

    expect(taps, 1);
  });
}
