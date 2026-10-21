import 'package:flutter/material.dart';

import 'app_theme.dart';

class AppStateTransition extends StatelessWidget {
  const AppStateTransition({
    required this.stateKey,
    required this.child,
    super.key,
  });

  final Key stateKey;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    return AnimatedSwitcher(
      duration: reduceMotion
          ? context.motion.feedback
          : context.motion.transition,
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      child: KeyedSubtree(key: stateKey, child: child),
    );
  }
}

class AppPressable extends StatefulWidget {
  const AppPressable({
    required this.child,
    required this.onPressed,
    required this.semanticLabel,
    this.borderRadius = const BorderRadius.all(Radius.circular(AppRadii.card)),
    super.key,
  });

  final Widget child;
  final VoidCallback? onPressed;
  final String semanticLabel;
  final BorderRadius borderRadius;

  @override
  State<AppPressable> createState() => _AppPressableState();
}

class _AppPressableState extends State<AppPressable> {
  bool _pressed = false;

  void _setPressed(bool value) {
    if (widget.onPressed != null && _pressed != value) {
      setState(() => _pressed = value);
    }
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    return Semantics(
      button: true,
      label: widget.semanticLabel,
      enabled: widget.onPressed != null,
      child: InkWell(
        onTap: widget.onPressed,
        onHighlightChanged: _setPressed,
        borderRadius: widget.borderRadius,
        child: AnimatedScale(
          scale: _pressed ? .985 : 1,
          duration: reduceMotion ? Duration.zero : context.motion.feedback,
          curve: Curves.easeOutCubic,
          child: widget.child,
        ),
      ),
    );
  }
}
