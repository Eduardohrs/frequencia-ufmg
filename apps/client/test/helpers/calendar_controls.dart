import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/features/schedule/general_calendar_page.dart';

Future<void> openCalendarFilters(WidgetTester tester) async {
  if (find.byKey(const Key('calendar-course-filter')).evaluate().isNotEmpty) {
    return;
  }
  await tester.tap(find.byKey(const Key('calendar-filters')));
  await tester.pumpAndSettle();
}

Future<void> applyCalendarFilters(WidgetTester tester) async {
  final apply = find.text('Aplicar');
  await tester.ensureVisible(apply);
  await tester.pumpAndSettle();
  await tester.tap(apply);
  await tester.pumpAndSettle();
}

Future<void> calendarDisplay(WidgetTester tester, String label) async {
  await openCalendarFilters(tester);
  final target = find.descendant(
    of: find.byType(SegmentedButton<CalendarDisplay>),
    matching: find.text(label),
  );
  await tester.ensureVisible(target);
  await tester.tap(target);
  await tester.pumpAndSettle();
  await applyCalendarFilters(tester);
}
