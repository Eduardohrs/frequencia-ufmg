import 'package:flutter/material.dart';

import 'app_theme.dart';

class AttendanceProgressBar extends StatelessWidget {
  const AttendanceProgressBar({
    required this.present,
    required this.unresolved,
    required this.absent,
    required this.barKey,
    required this.markerKey,
    super.key,
  });

  final int present;
  final int unresolved;
  final int absent;
  final Key barKey;
  final Key markerKey;

  @override
  Widget build(BuildContext context) {
    final total = present + unresolved + absent;
    final presentShare = total == 0 ? 0.0 : present / total;
    final absentShare = total == 0 ? 0.0 : absent / total;
    final colors = Theme.of(context).colorScheme;
    final semantic = Theme.of(context).extension<AppSemanticColors>();
    final success = semantic?.success ?? colors.primary;
    final neutral = semantic?.separator ?? colors.outlineVariant;

    return Semantics(
      label:
          '$present presenças, $unresolved aulas pendentes ou futuras e '
          '$absent faltas; limite mínimo de presença em 75%',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            key: barKey,
            height: 30,
            child: LayoutBuilder(
              builder: (context, constraints) => Stack(
                clipBehavior: Clip.none,
                alignment: Alignment.centerLeft,
                children: [
                  Positioned.fill(
                    top: 6,
                    bottom: 6,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: neutral,
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ),
                  if (presentShare > 0)
                    Positioned(
                      left: 0,
                      top: 6,
                      bottom: 6,
                      width: constraints.maxWidth * presentShare,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: success,
                          borderRadius: const BorderRadius.horizontal(
                            left: Radius.circular(12),
                          ),
                        ),
                      ),
                    ),
                  if (absentShare > 0)
                    Positioned(
                      right: 0,
                      top: 6,
                      bottom: 6,
                      width: constraints.maxWidth * absentShare,
                      child: DecoratedBox(
                        decoration: BoxDecoration(
                          color: colors.error,
                          borderRadius: const BorderRadius.horizontal(
                            right: Radius.circular(12),
                          ),
                        ),
                      ),
                    ),
                  Positioned(
                    key: markerKey,
                    left: constraints.maxWidth * .75 - 1,
                    top: 0,
                    width: 2,
                    height: 30,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: colors.onSurface,
                        borderRadius: BorderRadius.circular(2),
                        boxShadow: [
                          BoxShadow(
                            color: colors.surface.withValues(alpha: .8),
                            spreadRadius: 2,
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 14,
            runSpacing: 6,
            children: [
              _Legend(color: success, label: '$present presenças'),
              _Legend(color: neutral, label: '$unresolved pendentes/futuras'),
              _Legend(color: colors.error, label: '$absent faltas'),
            ],
          ),
        ],
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label});

  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => ConstrainedBox(
    constraints: const BoxConstraints(maxWidth: 190),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        DecoratedBox(
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          child: const SizedBox.square(dimension: 8),
        ),
        const SizedBox(width: 5),
        Flexible(
          child: Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    ),
  );
}
