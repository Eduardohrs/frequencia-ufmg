import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import '../../design/adaptive_app_shell.dart';
import '../settings/automatic_attendance_controller.dart';

/// Owns the navigation chrome above the app Navigator, including detail routes.
class ProductNavigation extends StatefulWidget {
  const ProductNavigation({required this.builder, super.key});
  final Widget Function(ProductNavigationController) builder;
  static ProductNavigationController? of(BuildContext context) =>
      context.getInheritedWidgetOfExactType<_NavigationScope>()?.notifier;
  @override
  State<ProductNavigation> createState() => _ProductNavigationState();
}

class _ProductNavigationState extends State<ProductNavigation> {
  final controller = ProductNavigationController();
  @override
  Widget build(BuildContext context) => widget.builder(controller);
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }
}

class ProductNavigationController extends ChangeNotifier {
  late final observer = _ProductObserver(this);
  Object? _owner;
  Future<void> Function(int)? _open;
  bool _disposed = false, _queued = false;
  int selected = 0;
  bool modal = false;
  AutomaticAttendanceController? attendance;
  AppLogger? logger;
  bool get active => _open != null;
  void bind(
    Object owner,
    Future<void> Function(int) open, {
    AutomaticAttendanceController? attendance,
    AppLogger? logger,
  }) {
    if (identical(_owner, owner)) return;
    _owner = owner;
    _open = open;
    this.attendance = attendance;
    this.logger = logger;
    _changed();
  }

  void unbind(Object owner) {
    if (!identical(_owner, owner)) return;
    _owner = null;
    _open = null;
    attendance = null;
    selected = 0;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_disposed && _owner == null) {
        observer.navigator?.popUntil((route) => route.isFirst);
      }
    });
    _changed();
  }

  Future<void> select(int destination) async {
    final open = _open;
    if (open == null || modal) return;
    final operation = newCorrelationId('navigation');
    final watch = Stopwatch()..start();
    if (logger case final log?) {
      emitOperationalEvent(log, 'app_navigation_selected', {
        'operation_id': operation,
        'stage': 'destination',
        'from': selected,
        'to': destination,
      });
    }
    observer.navigator?.popUntil((route) => route.isFirst);
    selected = destination;
    _changed();
    if (destination != 0) {
      unawaited(
        open(destination).catchError((Object error, StackTrace stack) {
          if (logger case final log?) {
            recordOperationalFailure(log, error, stack, 'app_navigation', {
              'operation_id': operation,
              'duration_ms': watch.elapsedMilliseconds,
              'stage': 'destination',
              'to': destination,
            }, failureCode: 'app_navigation_failed');
          }
        }),
      );
    }
  }

  void _changed() {
    if (_disposed || _queued) return;
    _queued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _queued = false;
      if (!_disposed) notifyListeners();
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  Widget frame(BuildContext context, Widget child) => Overlay.wrap(
    child: _NavigationScope(
      notifier: this,
      child: LayoutBuilder(
        builder: (context, constraints) => AnimatedBuilder(
          animation: this,
          builder: (context, _) {
            final rail =
                constraints.maxWidth >= AdaptiveAppShell.desktopBreakpoint &&
                constraints.maxHeight >= 600;
            Widget guarded(Widget navigation) => IgnorePointer(
              ignoring: modal,
              child: Opacity(opacity: modal ? .4 : 1, child: navigation),
            );
            return Scaffold(
              bottomNavigationBar: !active || rail
                  ? null
                  : guarded(
                      AppBottomNavigation(
                        selectedIndex: selected,
                        onSelected: (i) => unawaited(select(i)),
                      ),
                    ),
              body: Row(
                children: [
                  if (active && rail)
                    guarded(
                      AppSideNavigation(
                        selectedIndex: selected,
                        onSelected: (i) => unawaited(select(i)),
                      ),
                    ),
                  Expanded(child: child),
                ],
              ),
            );
          },
        ),
      ),
    ),
  );
  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

class _NavigationScope extends InheritedNotifier<ProductNavigationController> {
  const _NavigationScope({required super.notifier, required super.child});
}

class _ProductObserver extends NavigatorObserver {
  _ProductObserver(this.controller);
  final ProductNavigationController controller;
  final _sections = <Route<dynamic>, int>{};
  Route<dynamic>? _current;
  int _section(Route<dynamic>? route) => _sections[route] ?? 0;
  void _show(Route<dynamic>? route) {
    _current = route;
    controller.selected = _section(route);
    controller.modal = route is PopupRoute;
    controller._changed();
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _sections[route] = switch (route.settings.name) {
      'agenda' => 1,
      'absences' => 2,
      'settings' => 3,
      'course' => 0,
      _ => _section(previousRoute),
    };
    _show(route);
  }

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _sections.remove(route);
    _show(previousRoute);
  }

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) {
    _sections.remove(route);
    if (identical(route, _current)) _show(previousRoute);
  }

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    final section = _section(oldRoute);
    _sections.remove(oldRoute);
    if (newRoute != null) _sections[newRoute] = section;
    if (identical(oldRoute, _current)) _show(newRoute);
  }
}
