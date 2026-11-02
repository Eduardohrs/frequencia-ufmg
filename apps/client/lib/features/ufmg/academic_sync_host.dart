import 'package:flutter/material.dart';
import 'academic_sync_controller.dart';

/// Keeps progress outside the navigator, reserving space on every route.
class AcademicSyncHost extends StatefulWidget {
  const AcademicSyncHost({required this.child, super.key});
  final Widget child;

  static AcademicSyncHostState? maybeOf(BuildContext context) =>
      context.findAncestorStateOfType<AcademicSyncHostState>();

  @override
  State<AcademicSyncHost> createState() => AcademicSyncHostState();
}

class AcademicSyncHostState extends State<AcademicSyncHost> {
  AcademicSyncController? _controller;
  Widget? _banner;

  void show(AcademicSyncController controller, Widget banner) {
    setState(() {
      _controller = controller;
      _banner = banner;
    });
  }

  void clear(AcademicSyncController controller) {
    if (!mounted || !identical(_controller, controller)) return;
    setState(() {
      _controller = null;
      _banner = null;
    });
  }

  @override
  Widget build(BuildContext context) => Overlay.wrap(
    child: Column(
      children: [
        Expanded(child: widget.child),
        ?_banner,
      ],
    ),
  );
}
