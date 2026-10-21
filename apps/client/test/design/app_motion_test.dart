import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/app_motion.dart';
import 'package:frequencia_ufmg/design/app_theme.dart';

void main() {
  testWidgets('page transitions use a symmetric spatial path', (tester) async {
    const builder = AppPageTransitionsBuilder();
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Builder(
            builder: (context) => builder.buildTransitions<void>(
              MaterialPageRoute(builder: (_) => const SizedBox()),
              context,
              const AlwaysStoppedAnimation(.5),
              const AlwaysStoppedAnimation(0),
              const Text('Destino'),
            ),
          ),
        ),
      ),
    );

    final slide = tester.widget<SlideTransition>(
      find.byKey(const ValueKey('app-page-slide-transition')),
    );
    expect(slide.position.value.dx, greaterThan(0));
    expect(
      find.byKey(const ValueKey('app-page-fade-transition')),
      findsOneWidget,
    );
  });

  testWidgets('reduced motion replaces movement with a crossfade', (
    tester,
  ) async {
    const builder = AppPageTransitionsBuilder();
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(disableAnimations: true),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Builder(
            builder: (context) => builder.buildTransitions<void>(
              MaterialPageRoute(builder: (_) => const SizedBox()),
              context,
              const AlwaysStoppedAnimation(.5),
              const AlwaysStoppedAnimation(0),
              const Text('Destino'),
            ),
          ),
        ),
      ),
    );

    expect(
      find.byKey(const ValueKey('app-page-slide-transition')),
      findsNothing,
    );
    expect(
      find.byKey(const ValueKey('app-page-fade-transition')),
      findsOneWidget,
    );
  });

  testWidgets('state changes preserve context and respect reduced motion', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const MediaQuery(
          data: MediaQueryData(disableAnimations: true),
          child: AppStateTransition(
            stateKey: ValueKey('loaded'),
            child: Text('Conteúdo carregado'),
          ),
        ),
      ),
    );

    final switcher = tester.widget<AnimatedSwitcher>(
      find.byType(AnimatedSwitcher),
    );
    expect(switcher.duration, const AppMotion().feedback);
    expect(find.text('Conteúdo carregado'), findsOneWidget);
  });
}
