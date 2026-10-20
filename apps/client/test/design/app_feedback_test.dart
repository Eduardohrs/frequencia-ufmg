import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/design/app_feedback.dart';
import 'package:frequencia_ufmg/design/app_theme.dart';

void main() {
  testWidgets('inline messages remain readable and announce errors', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 700);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const MediaQuery(
          data: MediaQueryData(textScaler: TextScaler.linear(2)),
          child: Scaffold(
            body: AppInlineMessage(
              tone: AppMessageTone.error,
              message: 'Não foi possível salvar. Tente novamente.',
            ),
          ),
        ),
      ),
    );

    expect(find.byIcon(Icons.error_outline), findsOneWidget);
    expect(
      find.text('Não foi possível salvar. Tente novamente.'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('dialog header gives the task a title and supporting context', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light(),
        home: const Scaffold(
          body: AppDialogHeader(
            icon: Icons.edit_calendar_outlined,
            title: 'Editar período',
            subtitle: 'Ajuste quando as aulas acontecem.',
          ),
        ),
      ),
    );

    expect(find.text('Editar período'), findsOneWidget);
    expect(find.text('Ajuste quando as aulas acontecem.'), findsOneWidget);
    expect(find.byIcon(Icons.edit_calendar_outlined), findsOneWidget);
  });
}
