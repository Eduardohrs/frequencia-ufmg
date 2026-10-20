import 'package:flutter/material.dart';

class AdaptiveAppShell extends StatelessWidget {
  const AdaptiveAppShell({
    required this.title,
    required this.selectedIndex,
    required this.onDestinationSelected,
    required this.body,
    this.actions = const [],
    super.key,
  });

  static const desktopBreakpoint = 840.0;
  static const contentMaxWidth = 1040.0;

  final String title;
  final int selectedIndex;
  final ValueChanged<int> onDestinationSelected;
  final Widget body;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final separator =
        Theme.of(context).dividerTheme.color ??
        Theme.of(context).colorScheme.outlineVariant;
    return LayoutBuilder(
      builder: (context, constraints) {
        final usesRail = constraints.maxWidth >= desktopBreakpoint;
        return Scaffold(
          appBar: AppBar(
            title: Text(title),
            actions: actions,
            bottom: PreferredSize(
              preferredSize: const Size.fromHeight(1),
              child: Divider(color: separator),
            ),
          ),
          bottomNavigationBar: usesRail
              ? null
              : _NavigationMaterial(
                  child: NavigationBar(
                    backgroundColor: Colors.transparent,
                    selectedIndex: selectedIndex,
                    onDestinationSelected: onDestinationSelected,
                    destinations: _bottomDestinations,
                  ),
                ),
          body: SafeArea(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (usesRail) ...[
                  _NavigationMaterial(
                    child: NavigationRail(
                      backgroundColor: Colors.transparent,
                      selectedIndex: selectedIndex,
                      labelType: NavigationRailLabelType.all,
                      onDestinationSelected: onDestinationSelected,
                      destinations: _railDestinations,
                    ),
                  ),
                  VerticalDivider(width: 1, color: separator),
                ],
                Expanded(
                  child: Center(
                    child: ConstrainedBox(
                      key: const Key('app-shell-content'),
                      constraints: const BoxConstraints(
                        maxWidth: contentMaxWidth,
                      ),
                      child: body,
                    ),
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

class _NavigationMaterial extends StatelessWidget {
  const _NavigationMaterial({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final highContrast = MediaQuery.highContrastOf(context);
    final base = Theme.of(context).colorScheme.surface;
    return Material(
      key: const Key('app-shell-navigation-material'),
      color: highContrast ? base : base.withValues(alpha: .92),
      child: child,
    );
  }
}

const _bottomDestinations = [
  NavigationDestination(
    icon: Icon(Icons.home_outlined, key: Key('nav-home')),
    selectedIcon: Icon(Icons.home, key: Key('nav-home')),
    label: 'Início',
  ),
  NavigationDestination(
    icon: Icon(Icons.calendar_month_outlined, key: Key('nav-general-calendar')),
    selectedIcon: Icon(Icons.calendar_month),
    label: 'Calendário',
  ),
  NavigationDestination(
    icon: Icon(Icons.donut_small_outlined, key: Key('nav-absence-dashboard')),
    selectedIcon: Icon(Icons.donut_small),
    label: 'Faltas',
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
    selectedIcon: Icon(Icons.calendar_month),
    label: Text('Calendário'),
  ),
  NavigationRailDestination(
    icon: Icon(Icons.donut_small_outlined, key: Key('nav-absence-dashboard')),
    selectedIcon: Icon(Icons.donut_small),
    label: Text('Faltas'),
  ),
];
