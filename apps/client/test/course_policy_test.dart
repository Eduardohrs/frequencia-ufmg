import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/backend/python_backend_transport.dart';
import 'package:frequencia_ufmg/data/python_course_repository.dart';
import 'package:frequencia_ufmg/features/attendance/absence_dashboard_page.dart';
import 'package:frequencia_ufmg/features/courses/course_editor_dialog.dart';
import 'package:timezone/data/latest.dart' as tz_data;
import 'package:timezone/timezone.dart' as tz;

final _now = DateTime.utc(2026, 10, 25);
CourseRecord _course(CourseModality modality, CourseAttendancePolicy policy) =>
    CourseRecord(
      id: 'course',
      code: 'DCC203',
      name: 'POO',
      workload: 60,
      term: '2026-2',
      modality: modality,
      attendancePolicy: policy,
      createdAt: _now,
      updatedAt: _now,
    );

void main() {
  tz_data.initializeTimeZones();
  test(
    'policy survives Firestore, API and frequency calculations without a schedule',
    () {
      for (final modality in CourseModality.values) {
        final record = _course(modality, CourseAttendancePolicy.noCall);
        final restored = CourseRecord.fromFirestore(
          record.id,
          record.toFirestore(),
        );
        expect(restored.modality, modality);
        expect(restored.tracksAttendance, isFalse);
        expect(
          restored.policyLabel,
          modality == CourseModality.online ? 'Online' : 'Sem chamada',
        );
        final api = PythonCourse.fromJson({
          'id': record.id,
          'code': record.code,
          'name': record.name,
          'workload': 60,
          'term': record.term,
          'starts_on': null,
          'ends_on': null,
          'created_at': _now.toIso8601String(),
          'updated_at': _now.toIso8601String(),
          'modality': modality.code,
          'attendance_policy': 'no_call',
        });
        expect(api.toJson()['attendance_policy'], 'no_call');
        expect(courseRecordFromPython(api).tracksAttendance, isFalse);
        final summary = CourseAbsenceSummary.from(
          restored,
          [],
          now: _now,
          location: tz.getLocation('America/Sao_Paulo'),
        );
        expect(summary.remainingMeetingsLabel, 'Não se aplica');
        expect(summary.pendingSessions, 0);
      }
      expect(() => CourseModality.fromCode('invalid'), throwsFormatException);
      expect(
        () => CourseAttendancePolicy.fromCode('invalid'),
        throwsFormatException,
      );
      final malformed = _course(
        CourseModality.inPerson,
        CourseAttendancePolicy.required,
      ).toFirestore()..['modality'] = 'online';
      expect(
        () => CourseRecord.fromFirestore('course', malformed),
        throwsFormatException,
      );
      final malformedApi = PythonCourse(
        id: 'course',
        code: 'DCC203',
        name: 'POO',
        workload: 60,
        term: '2026-2',
        startsOn: null,
        endsOn: null,
        createdAt: _now,
        updatedAt: _now,
        modality: 'online',
      ).toJson();
      expect(() => PythonCourse.fromJson(malformedApi), throwsFormatException);
    },
  );

  testWidgets(
    'online can be created without timetable and policy changes require confirmation',
    (tester) async {
      CourseInput? saved;
      Future<void> open(CourseRecord? course) async {
        await tester.pumpWidget(
          MaterialApp(
            home: Builder(
              builder: (context) => Scaffold(
                body: TextButton(
                  onPressed: () => showDialog<void>(
                    context: context,
                    builder: (_) => CourseEditorDialog(
                      course: course,
                      initialTerm: '2026-2',
                      allowedTerms: const ['2026-2', '2027-1'],
                      onValidationFailed: () {},
                      onSave: (value) async {
                        saved = value;
                        return null;
                      },
                    ),
                  ),
                  child: const Text('Open'),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('Open'));
        await tester.pumpAndSettle();
      }

      await open(null);
      await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
      await tester.enterText(find.byKey(const Key('course-name')), 'POO');
      // 55.33: no modo criar, os campos avançados ficam fechados em
      // "Opções avançadas".
      await tester.tap(find.byKey(const Key('course-advanced-options')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('course-modality')));
      await tester.tap(find.byKey(const Key('course-modality')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Online').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(saved!.modality, CourseModality.online);
      expect(saved!.attendancePolicy, CourseAttendancePolicy.noCall);

      saved = null;
      await open(
        _course(CourseModality.inPerson, CourseAttendancePolicy.required),
      );
      await tester.ensureVisible(
        find.byKey(const Key('course-attendance-required')),
      );
      await tester.tap(find.byKey(const Key('course-attendance-required')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sem chamada').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.text('Alterar controle de frequência?'), findsOneWidget);
      await tester.tap(find.widgetWithText(TextButton, 'Cancelar').last);
      await tester.pumpAndSettle();
      expect(saved, isNull);
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Aplicar'));
      await tester.pumpAndSettle();
      expect(saved!.attendancePolicy, CourseAttendancePolicy.noCall);

      await open(_course(CourseModality.online, CourseAttendancePolicy.noCall));
      await tester.ensureVisible(find.byKey(const Key('course-modality')));
      await tester.ensureVisible(find.byKey(const Key('course-modality')));
      await tester.tap(find.byKey(const Key('course-modality')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Presencial').last);
      await tester.pumpAndSettle();
      await tester.ensureVisible(
        find.byKey(const Key('course-attendance-no_call')),
      );
      await tester.tap(find.byKey(const Key('course-attendance-no_call')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Com chamada').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Salvar'));
      await tester.pumpAndSettle();
      expect(find.textContaining('voltará aos cálculos'), findsOneWidget);
      await tester.tap(find.text('Aplicar'));
      await tester.pumpAndSettle();
      expect(saved!.attendancePolicy, CourseAttendancePolicy.required);
    },
  );

  testWidgets(
    '55.33: criar esconde opções avançadas, expande, e applies debounce/atalhos/spinner/48px',
    (tester) async {
      var now = DateTime.utc(2026, 11, 16, 12);
      DateTime clock() => now;
      var saveCount = 0;
      Completer<String?>? gate;
      Future<String?> onSave(CourseInput input) async {
        saveCount++;
        final current = gate;
        if (current != null) return current.future;
        return null;
      }

      Future<void> open() async {
        await tester.pumpWidget(
          MaterialApp(
            home: Builder(
              builder: (context) => Scaffold(
                body: TextButton(
                  onPressed: () => showDialog<void>(
                    context: context,
                    barrierDismissible: false,
                    builder: (_) => CourseEditorDialog(
                      initialTerm: '2026-2',
                      allowedTerms: const ['2026-2', '2027-1'],
                      onValidationFailed: () {},
                      onSave: onSave,
                      clock: clock,
                    ),
                  ),
                  child: const Text('Open'),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('Open'));
        await tester.pumpAndSettle();
      }

      await open();

      // Form simplificado: código e nome visíveis, avançado fechado.
      expect(find.byKey(const Key('course-code')), findsOneWidget);
      expect(find.byKey(const Key('course-name')), findsOneWidget);
      expect(find.text('Opções avançadas'), findsOneWidget);
      await tester.tap(find.text('Opções avançadas'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('course-nickname')), 'POO');

      // Alvos de toque >= 48dp nos botões de ação.
      final cancelBox = tester.renderObject<RenderBox>(
        find.widgetWithText(TextButton, 'Cancelar'),
      );
      final saveBox = tester.renderObject<RenderBox>(
        find.widgetWithText(FilledButton, 'Salvar'),
      );
      expect(cancelBox.size.height, greaterThanOrEqualTo(48));
      expect(saveBox.size.height, greaterThanOrEqualTo(48));

      await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
      await tester.enterText(find.byKey(const Key('course-name')), 'POO');

      // Duplo clique rápido: uma única chamada de save (gate pendente).
      gate = Completer<String?>();
      await tester.tap(find.byType(FilledButton));
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      expect(saveCount, 1);
      // Spinner visível enquanto salva.
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Salvando...'), findsOneWidget);
      // ESC durante o save não fecha o diálogo.
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pump();
      expect(find.byKey(const Key('course-code')), findsOneWidget);
      gate.complete(null);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('course-code')), findsNothing);

      // Após falha de save, o erro aparece inline e o botão volta a funcionar.
      saveCount = 0;
      await open();
      await tester.enterText(find.byKey(const Key('course-code')), 'DCC204');
      await tester.enterText(find.byKey(const Key('course-name')), 'AEDS');
      gate = Completer<String?>();
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      expect(saveCount, 1);
      gate.complete('erro de teste');
      await tester.pumpAndSettle();
      expect(find.text('erro de teste'), findsOneWidget);
      final before = saveCount;
      now = now.add(const Duration(milliseconds: 50));
      gate = null;
      await tester.tap(find.byType(FilledButton));
      await tester.pumpAndSettle();
      expect(saveCount, before + 1);
      expect(find.byKey(const Key('course-code')), findsNothing);

      // Enter no campo salva o formulário.
      saveCount = 0;
      await open();
      await tester.enterText(find.byKey(const Key('course-code')), 'DCC205');
      await tester.enterText(find.byKey(const Key('course-name')), 'Calculo');
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(saveCount, 1);
      expect(find.byKey(const Key('course-code')), findsNothing);

      // ESC fecha o diálogo quando não está salvando.
      await open();
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('course-code')), findsNothing);
    },
  );

  testWidgets(
    '55.33: Enter nos campos de criar dispara o submit via onFieldSubmitted',
    (tester) async {
      var saveCount = 0;
      Future<String?> onSave(CourseInput input) async {
        saveCount++;
        return 'erro';
      }

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () => showDialog<void>(
                  context: context,
                  barrierDismissible: false,
                  builder: (_) => CourseEditorDialog(
                    initialTerm: '2026-2',
                    allowedTerms: const ['2026-2', '2027-1'],
                    onValidationFailed: () {},
                    onSave: onSave,
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('course-code')), 'DCC203');
      await tester.enterText(find.byKey(const Key('course-name')), 'POO');
      // Enter (ação do teclado) em cada campo chama onFieldSubmitted -> submit.
      await tester.tap(find.byKey(const Key('course-code')));
      await tester.testTextInput.receiveAction(TextInputAction.next);
      await tester.pumpAndSettle();
      expect(saveCount, 1);
      await tester.tap(find.byKey(const Key('course-name')));
      await tester.testTextInput.receiveAction(TextInputAction.next);
      await tester.pumpAndSettle();
      expect(saveCount, 2);
      await tester.tap(find.text('Opções avançadas'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('course-nickname')));
      await tester.testTextInput.receiveAction(TextInputAction.next);
      await tester.pumpAndSettle();
      expect(saveCount, 3);
      expect(find.text('erro'), findsOneWidget);
    },
  );

  testWidgets('55.33: Enter no campo de período (editar) dispara o submit', (
    tester,
  ) async {
    var saveCount = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: TextButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (_) => CourseEditorDialog(
                  course: _course(
                    CourseModality.inPerson,
                    CourseAttendancePolicy.required,
                  ),
                  initialTerm: '2026-2',
                  allowedTerms: const ['2026-2', '2027-1'],
                  onValidationFailed: () {},
                  onSave: (input) async {
                    saveCount++;
                    return null;
                  },
                ),
              ),
              child: const Text('Open'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('course-term')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('course-term')));
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(saveCount, 1);
  });

  testWidgets('55.33: no mobile o diálogo aplica escala mínima de fonte', (
    tester,
  ) async {
    Future<void> open() async {
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: TextButton(
                onPressed: () => showDialog<void>(
                  context: context,
                  builder: (_) => CourseEditorDialog(
                    initialTerm: '2026-2',
                    allowedTerms: const ['2026-2', '2027-1'],
                    onValidationFailed: () {},
                    onSave: (_) async => null,
                  ),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
    }

    // Desktop (800x600): nenhuma escala extra aplicada pelo diálogo.
    await open();
    expect(
      find.byWidgetPredicate(
        (w) => w is MediaQuery && w.data.textScaler.scale(1) > 1.01,
      ),
      findsNothing,
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();

    // Mobile (390x844 lógico): o diálogo aplica escala mínima 1.15.
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await open();
    expect(
      find.byWidgetPredicate(
        (w) => w is MediaQuery && w.data.textScaler.scale(1) >= 1.149,
      ),
      findsWidgets,
    );
  });
}
