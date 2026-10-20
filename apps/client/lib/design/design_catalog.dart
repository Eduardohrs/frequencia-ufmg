import 'package:flutter/material.dart';

import 'app_theme.dart';
import 'course_identity.dart';

class AppPressable extends StatefulWidget {
  const AppPressable({
    required this.child,
    required this.onPressed,
    required this.semanticLabel,
    super.key,
  });

  final Widget child;
  final VoidCallback? onPressed;
  final String semanticLabel;

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
        borderRadius: BorderRadius.circular(AppRadii.card),
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

class DesignCatalogPage extends StatelessWidget {
  const DesignCatalogPage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Fundações visuais')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.md),
          children: [
            Text(
              'Disciplinas com identidade, informações em repouso.',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: AppSpacing.lg),
            const _CatalogCourse(
              code: 'MAT245',
              name: 'Cálculo III',
              detail: 'Próxima aula hoje, 19h',
            ),
            const SizedBox(height: AppSpacing.sm),
            const _CatalogCourse(
              code: 'ELE028',
              name: 'Laboratório de Circuitos',
              detail: 'Tudo em dia',
            ),
          ],
        ),
      ),
    );
  }
}

class _CatalogCourse extends StatelessWidget {
  const _CatalogCourse({
    required this.code,
    required this.name,
    required this.detail,
  });

  final String code;
  final String name;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return AppPressable(
      semanticLabel: 'Abrir $name',
      onPressed: () {},
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CourseMark(code: code),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      '$code · $detail',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded),
            ],
          ),
        ),
      ),
    );
  }
}
