import 'package:flutter/material.dart';

export 'app_motion.dart' show AppPressable;

import 'app_motion.dart';
import 'app_theme.dart';
import 'course_identity.dart';

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
