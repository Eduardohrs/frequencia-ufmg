import 'package:flutter/material.dart';

import 'app_theme.dart';

enum AppMessageTone { info, success, warning, error }

class AppInlineMessage extends StatelessWidget {
  const AppInlineMessage({
    required this.message,
    this.tone = AppMessageTone.info,
    super.key,
  });

  final String message;
  final AppMessageTone tone;

  @override
  Widget build(BuildContext context) {
    final color = switch (tone) {
      AppMessageTone.info => context.semanticColors.info,
      AppMessageTone.success => context.semanticColors.success,
      AppMessageTone.warning => context.semanticColors.warning,
      AppMessageTone.error => Theme.of(context).colorScheme.error,
    };
    final icon = switch (tone) {
      AppMessageTone.info => Icons.info_outline,
      AppMessageTone.success => Icons.check_circle_outline,
      AppMessageTone.warning => Icons.warning_amber_rounded,
      AppMessageTone.error => Icons.error_outline,
    };

    return Semantics(
      liveRegion: true,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: color.withValues(alpha: .1),
          border: Border.all(color: color.withValues(alpha: .35)),
          borderRadius: BorderRadius.circular(AppRadii.control),
        ),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.sm),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, color: color, size: 22),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Text(
                  message,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: color,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class AppDialogHeader extends StatelessWidget {
  const AppDialogHeader({
    required this.icon,
    required this.title,
    this.subtitle,
    this.destructive = false,
    super.key,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final bool destructive;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = destructive ? scheme.error : scheme.primary;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 44,
          height: 44,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: color.withValues(alpha: .1),
            borderRadius: BorderRadius.circular(AppRadii.card),
          ),
          child: Icon(icon, color: color),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              if (subtitle case final subtitle?) ...[
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  subtitle,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: scheme.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
