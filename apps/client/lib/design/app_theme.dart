import 'package:flutter/material.dart';

abstract final class AppSpacing {
  static const double xxs = 4;
  static const double xs = 8;
  static const double sm = 12;
  static const double md = 16;
  static const double lg = 24;
  static const double xl = 32;
  static const double xxl = 48;
}

abstract final class AppRadii {
  static const double control = 10;
  static const double card = 16;
  static const double prominent = 24;
}

@immutable
class AppSemanticColors extends ThemeExtension<AppSemanticColors> {
  const AppSemanticColors({
    required this.success,
    required this.warning,
    required this.info,
    required this.subtleSurface,
    required this.separator,
  });

  final Color success;
  final Color warning;
  final Color info;
  final Color subtleSurface;
  final Color separator;

  @override
  AppSemanticColors copyWith({
    Color? success,
    Color? warning,
    Color? info,
    Color? subtleSurface,
    Color? separator,
  }) => AppSemanticColors(
    success: success ?? this.success,
    warning: warning ?? this.warning,
    info: info ?? this.info,
    subtleSurface: subtleSurface ?? this.subtleSurface,
    separator: separator ?? this.separator,
  );

  @override
  AppSemanticColors lerp(AppSemanticColors? other, double t) {
    if (other == null) return this;
    return AppSemanticColors(
      success: Color.lerp(success, other.success, t)!,
      warning: Color.lerp(warning, other.warning, t)!,
      info: Color.lerp(info, other.info, t)!,
      subtleSurface: Color.lerp(subtleSurface, other.subtleSurface, t)!,
      separator: Color.lerp(separator, other.separator, t)!,
    );
  }
}

@immutable
class AppMotion extends ThemeExtension<AppMotion> {
  const AppMotion({
    this.feedback = const Duration(milliseconds: 110),
    this.transition = const Duration(milliseconds: 240),
  });

  final Duration feedback;
  final Duration transition;

  @override
  AppMotion copyWith({Duration? feedback, Duration? transition}) => AppMotion(
    feedback: feedback ?? this.feedback,
    transition: transition ?? this.transition,
  );

  @override
  AppMotion lerp(AppMotion? other, double t) {
    if (other == null) return this;
    return t < .5 ? this : other;
  }
}

class AppPageTransitionsBuilder extends PageTransitionsBuilder {
  const AppPageTransitionsBuilder();

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    final curved = CurvedAnimation(
      parent: animation,
      curve: Curves.easeOutCubic,
      reverseCurve: Curves.easeInCubic,
    );
    final faded = FadeTransition(
      key: const ValueKey('app-page-fade-transition'),
      opacity: curved,
      child: child,
    );
    if (MediaQuery.disableAnimationsOf(context)) return faded;
    return SlideTransition(
      key: const ValueKey('app-page-slide-transition'),
      position: Tween(
        begin: const Offset(.035, 0),
        end: Offset.zero,
      ).animate(curved),
      child: faded,
    );
  }
}

abstract final class AppTheme {
  static const _seed = Color(0xFF006633);

  static ThemeData light({bool highContrast = false}) =>
      _build(brightness: Brightness.light, highContrast: highContrast);

  static ThemeData dark({bool highContrast = false}) =>
      _build(brightness: Brightness.dark, highContrast: highContrast);

  static ThemeData _build({
    required Brightness brightness,
    required bool highContrast,
  }) {
    final dark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: _seed,
      brightness: brightness,
      contrastLevel: highContrast ? 1 : .15,
    );
    final surface = dark ? const Color(0xFF111412) : const Color(0xFFF6F8F6);
    final card = dark ? const Color(0xFF191D1A) : const Color(0xFFFFFFFF);
    final separator = dark
        ? (highContrast ? const Color(0xFF8C958F) : const Color(0xFF343A36))
        : (highContrast ? const Color(0xFF59625C) : const Color(0xFFDCE3DE));
    final baseText = Typography.material2021(
      platform: TargetPlatform.iOS,
    ).black.apply(bodyColor: scheme.onSurface, displayColor: scheme.onSurface);
    final text = baseText.copyWith(
      headlineMedium: baseText.headlineMedium?.copyWith(
        fontWeight: FontWeight.w700,
        height: 1.12,
        letterSpacing: -.6,
      ),
      titleLarge: baseText.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
        height: 1.18,
        letterSpacing: -.25,
      ),
      titleMedium: baseText.titleMedium?.copyWith(
        fontWeight: FontWeight.w600,
        height: 1.25,
        letterSpacing: -.1,
      ),
      bodyLarge: baseText.bodyLarge?.copyWith(height: 1.45, letterSpacing: 0),
      bodyMedium: baseText.bodyMedium?.copyWith(
        height: 1.45,
        letterSpacing: .1,
      ),
      labelLarge: baseText.labelLarge?.copyWith(
        fontWeight: FontWeight.w600,
        height: 1.2,
        letterSpacing: .1,
      ),
    );

    return ThemeData(
      brightness: brightness,
      colorScheme: scheme,
      useMaterial3: true,
      scaffoldBackgroundColor: surface,
      textTheme: text,
      splashFactory: NoSplash.splashFactory,
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: AppPageTransitionsBuilder(),
          TargetPlatform.iOS: AppPageTransitionsBuilder(),
          TargetPlatform.macOS: AppPageTransitionsBuilder(),
          TargetPlatform.windows: AppPageTransitionsBuilder(),
          TargetPlatform.linux: AppPageTransitionsBuilder(),
          TargetPlatform.fuchsia: AppPageTransitionsBuilder(),
        },
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: surface,
        foregroundColor: scheme.onSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        titleTextStyle: text.titleLarge,
      ),
      navigationBarTheme: NavigationBarThemeData(
        elevation: 0,
        height: 68,
        backgroundColor: Colors.transparent,
        indicatorColor: scheme.secondaryContainer,
        labelTextStyle: WidgetStatePropertyAll(text.labelMedium),
      ),
      navigationRailTheme: NavigationRailThemeData(
        elevation: 0,
        minWidth: 84,
        backgroundColor: Colors.transparent,
        indicatorColor: scheme.secondaryContainer,
        selectedLabelTextStyle: text.labelMedium?.copyWith(
          fontWeight: FontWeight.w600,
        ),
        unselectedLabelTextStyle: text.labelMedium,
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: card,
        surfaceTintColor: Colors.transparent,
        elevation: 3,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
        ),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: card,
        surfaceTintColor: Colors.transparent,
        elevation: 8,
        insetPadding: const EdgeInsets.all(AppSpacing.md),
        shape: RoundedRectangleBorder(
          side: BorderSide(color: separator),
          borderRadius: BorderRadius.circular(AppRadii.prominent),
        ),
        titleTextStyle: text.titleLarge,
        contentTextStyle: text.bodyMedium,
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        elevation: 6,
        backgroundColor: scheme.inverseSurface,
        contentTextStyle: text.bodyMedium?.copyWith(
          color: scheme.onInverseSurface,
          fontWeight: FontWeight.w500,
        ),
        actionTextColor: scheme.inversePrimary,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
        ),
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(
        color: scheme.primary,
        linearTrackColor: scheme.surfaceContainerHighest,
        circularTrackColor: scheme.surfaceContainerHighest,
        linearMinHeight: 4,
        borderRadius: BorderRadius.circular(AppRadii.control),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(64, 48),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.control),
          ),
          textStyle: text.labelLarge,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          minimumSize: const Size(48, 48),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadii.control),
          ),
          textStyle: text.labelLarge,
        ),
      ),
      cardTheme: CardThemeData(
        color: card,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          side: BorderSide(color: separator),
          borderRadius: BorderRadius.circular(AppRadii.card),
        ),
      ),
      dividerTheme: DividerThemeData(color: separator, space: 1),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: card,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        border: OutlineInputBorder(
          borderSide: BorderSide(color: separator),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
        enabledBorder: OutlineInputBorder(
          borderSide: BorderSide(color: separator),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
        focusedBorder: OutlineInputBorder(
          borderSide: BorderSide(color: scheme.primary, width: 2),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
        errorBorder: OutlineInputBorder(
          borderSide: BorderSide(color: scheme.error),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderSide: BorderSide(color: scheme.error, width: 2),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
      ),
      extensions: [
        AppSemanticColors(
          success: dark ? const Color(0xFF65D58A) : const Color(0xFF197A3E),
          warning: dark ? const Color(0xFFFFC66B) : const Color(0xFF925900),
          info: dark ? const Color(0xFF71B7FF) : const Color(0xFF1769AA),
          subtleSurface: dark
              ? const Color(0xFF212622)
              : const Color(0xFFEEF2EF),
          separator: separator,
        ),
        const AppMotion(),
      ],
    );
  }
}

extension AppThemeContext on BuildContext {
  AppSemanticColors get semanticColors =>
      Theme.of(this).extension<AppSemanticColors>()!;

  AppMotion get motion =>
      Theme.of(this).extension<AppMotion>() ?? const AppMotion();
}
