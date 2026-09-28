import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/features/schedule/course_date_range_picker.dart';

void main() {
  testWidgets('selects a range without typing and counts teaching days', (
    tester,
  ) async {
    DateTimeRange? selected;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () async {
                selected = await showDialog<DateTimeRange>(
                  context: context,
                  builder: (_) => CourseDateRangePickerDialog(
                    initialMonth: DateTime(2026, 10),
                    firstDate: DateTime(2026, 1, 1),
                    lastDate: DateTime(2027, 12, 31),
                    highlightedWeekdays: const {
                      DateTime.monday,
                      DateTime.tuesday,
                    },
                  ),
                );
              },
              child: const Text('Abrir'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Abrir'));
    await tester.pumpAndSettle();

    expect(find.text('Período das aulas'), findsOneWidget);
    expect(find.text('Clique no primeiro e no último dia.'), findsOneWidget);
    expect(find.byIcon(Icons.circle), findsWidgets);
    await tester.tap(find.byKey(const Key('date-2026-10-05')));
    await tester.pumpAndSettle();
    expect(find.text('Escolha o último dia'), findsOneWidget);

    final target = find.byKey(const Key('date-2026-10-12'));
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: Offset.zero);
    await mouse.moveTo(tester.getCenter(target));
    await tester.pumpAndSettle();
    expect(find.text('3 dias de aula no intervalo'), findsOneWidget);

    await tester.tap(target);
    await tester.pumpAndSettle();
    await mouse.removePointer();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar período'));
    await tester.pumpAndSettle();

    expect(selected?.start, DateTime(2026, 10, 5));
    expect(selected?.end, DateTime(2026, 10, 12));
  });

  testWidgets('resets when selecting a new start and supports cancellation', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: CourseDateRangePickerDialog(
          initialMonth: DateTime(2026, 10),
          initialRange: DateTimeRange(
            start: DateTime(2026, 10, 5),
            end: DateTime(2026, 10, 12),
          ),
          firstDate: DateTime(2026, 1, 1),
          lastDate: DateTime(2027, 12, 31),
          highlightedWeekdays: const {DateTime.monday},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('2 dias de aula no intervalo'), findsOneWidget);
    await tester.tap(find.byKey(const Key('date-2026-10-20')));
    await tester.pumpAndSettle();
    expect(find.text('Escolha o último dia'), findsOneWidget);
    await tester.tap(find.byKey(const Key('date-2026-10-10')));
    await tester.pumpAndSettle();
    expect(find.text('Escolha o último dia'), findsOneWidget);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
  });

  testWidgets('navigates months and uses one calendar on a phone', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseDateRangePickerDialog(
          initialMonth: DateTime(2026, 10),
          firstDate: DateTime(2026, 10, 10),
          lastDate: DateTime(2026, 12, 31),
          highlightedWeekdays: const {},
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Outubro 2026'), findsOneWidget);
    expect(find.text('Novembro 2026'), findsNothing);
    await tester.tap(find.byTooltip('Próximo mês'));
    await tester.pumpAndSettle();
    expect(find.text('Novembro 2026'), findsOneWidget);
    await tester.tap(find.byTooltip('Mês anterior'));
    await tester.pumpAndSettle();
    expect(find.text('Outubro 2026'), findsOneWidget);
  });
}
