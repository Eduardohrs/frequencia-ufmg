import 'package:flutter/material.dart';

class AdaptiveAppShell extends StatelessWidget {
  const AdaptiveAppShell({
    required this.title,
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
    this.actions = const [],
    this.externalNavigation = false,
    super.key,
  });

  static const desktopBreakpoint = 840.0;
  static const contentMaxWidth = 1040.0;

  final String title;
  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;
  final List<Widget> actions;
  final bool externalNavigation;

  @override
  Widget build(BuildContext context) {
    final separator =
        Theme.of(context).dividerTheme.color ??
        Theme.of(context).colorScheme.outlineVariant;
    return LayoutBuilder(
      builder: (context, constraints) {
        final usesRail = constraints.maxWidth >= desktopBreakpoint;
        return Scaffold(
          appBar: usesRail
              ? null
              : AppBar(
                  title: Text(title),
                  actions: actions,
                  bottom: PreferredSize(
                    preferredSize: const Size.fromHeight(1),
                    child: Divider(color: separator),
                  ),
                ),
          bottomNavigationBar: usesRail || externalNavigation
              ? null
              : AppBottomNavigation(
                  selectedIndex: selectedIndex,
                  onSelected: onDestinationSelected,
                ),
          body: SafeArea(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (usesRail && !externalNavigation) ...[
                  AppSideNavigation(
                    selectedIndex: selectedIndex,
                    onSelected: onDestinationSelected,
                  ),
                  VerticalDivider(width: 1, color: separator),
                ],
                Expanded(
                  child: Stack(
                    children: [
                      Center(
                        child: ConstrainedBox(
                          key: const Key('app-shell-content'),
                          constraints: const BoxConstraints(
                            maxWidth: contentMaxWidth,
                          ),
                          child: body,
                        ),
                      ),
                      if (usesRail && actions.isNotEmpty)
                        Positioned(
                          top: 18,
                          right: 20,
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: actions,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class AppBottomNavigation extends StatelessWidget {
  const AppBottomNavigation({
    required this.selectedIndex,
    required this.onSelected,
    super.key,
  });
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  @override
  Widget build(BuildContext context) => SafeArea(
    minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
    child: _NavigationMaterial(
      rounded: true,
      child: NavigationBar(
        backgroundColor: Colors.transparent,
        selectedIndex: selectedIndex,
        onDestinationSelected: onSelected,
        destinations: _bottomDestinations,
      ),
    ),
  );
}

class AppSideNavigation extends StatelessWidget {
  const AppSideNavigation({
    required this.selectedIndex,
    required this.onSelected,
    super.key,
  });
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  @override
  Widget build(BuildContext context) => _NavigationMaterial(
    child: SizedBox(
      width: 104,
      child: Column(
        children: [
          const SizedBox(height: 24),
          const _BrandMark(),
          Expanded(
            child: NavigationRail(
              backgroundColor: Colors.transparent,
              selectedIndex: selectedIndex,
              labelType: NavigationRailLabelType.all,
              onDestinationSelected: onSelected,
              destinations: _railDestinations,
            ),
          ),
        ],
      ),
    ),
  );
}

class _NavigationMaterial extends StatelessWidget {
  const _NavigationMaterial({required this.child, this.rounded = false});

  final Widget child;
  final bool rounded;

  @override
  Widget build(BuildContext context) {
    final highContrast = MediaQuery.highContrastOf(context);
    final base = Theme.of(context).colorScheme.surface;
    return Material(
      key: const Key('app-shell-navigation-material'),
      color: highContrast ? base : base.withValues(alpha: .92),
      elevation: rounded && !highContrast ? 2 : 0,
      clipBehavior: Clip.antiAlias,
      shape: rounded
          ? RoundedRectangleBorder(borderRadius: BorderRadius.circular(22))
          : null,
      child: child,
    );
  }
}

class _BrandMark extends StatelessWidget {
  const _BrandMark();

  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Frequência UFMG',
    child: ExcludeSemantics(
      child: Container(
        width: 46,
        height: 46,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.primary,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: Theme.of(
                context,
              ).colorScheme.primary.withValues(alpha: .2),
              blurRadius: 20,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Text(
          'F',
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            color: Theme.of(context).colorScheme.onPrimary,
          ),
        ),
      ),
    ),
  );
}

const _bottomDestinations = [
  NavigationDestination(
    icon: Icon(Icons.home_outlined, key: Key('nav-home')),
    selectedIcon: Icon(Icons.home, key: Key('nav-home')),
    label: 'Início',
  ),
  NavigationDestination(
    icon: Icon(Icons.calendar_month_outlined, key: Key('nav-general-calendar')),
    selectedIcon: Icon(Icons.calendar_month, key: Key('nav-general-calendar')),
    label: 'Calendário',
  ),
  NavigationDestination(
    icon: Icon(Icons.donut_small_outlined, key: Key('nav-absence-dashboard')),
    selectedIcon: Icon(Icons.donut_small, key: Key('nav-absence-dashboard')),
    label: 'Faltas',
  ),
  NavigationDestination(
    icon: Icon(Icons.settings_outlined, key: Key('nav-settings')),
    selectedIcon: Icon(Icons.settings, key: Key('nav-settings')),
    label: 'Ajustes',
  ),
];

const _railDestinations = [
  NavigationRailDestination(
    icon: Icon(Icons.home_outlined, key: Key('nav-home')),
    selectedIcon: Icon(Icons.home, key: Key('nav-home')),
    label: Text('Início'),
  ),
  NavigationRailDestination(
    icon: Icon(Icons.calendar_month_outlined, key: Key('nav-general-calendar')),
    selectedIcon: Icon(Icons.calendar_month, key: Key('nav-general-calendar')),
    label: Text('Calendário'),
  ),
  NavigationRailDestination(
    icon: Icon(Icons.donut_small_outlined, key: Key('nav-absence-dashboard')),
    selectedIcon: Icon(Icons.donut_small, key: Key('nav-absence-dashboard')),
    label: Text('Faltas'),
  ),
  NavigationRailDestination(
    icon: Icon(Icons.settings_outlined, key: Key('nav-settings')),
    selectedIcon: Icon(Icons.settings, key: Key('nav-settings')),
    label: Text('Ajustes'),
  ),
];
