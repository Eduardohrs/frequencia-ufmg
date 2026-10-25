import 'package:flutter/material.dart';
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
      await tester.tap(find.byKey(const Key('course-modality')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Presencial').last);
      await tester.pumpAndSettle();
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
}
