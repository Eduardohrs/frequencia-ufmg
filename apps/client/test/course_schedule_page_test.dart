import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/data/academic_records.dart';
import 'package:frequencia_ufmg/data/academic_repositories.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';
import 'package:frequencia_ufmg/features/schedule/course_schedule_page.dart';

void main() {
  final now = DateTime.utc(2026, 9, 27, 12);
  final course = CourseRecord(
    id: 'poo',
    code: 'DCC203',
    name: 'POO',
    workload: 60,
    term: '2026-2',
    createdAt: now,
    updatedAt: now,
  );

  testWidgets('creates, edits, lists, and deletes a weekly meeting', (
    tester,
  ) async {
    final repository = _FakeMeetingRepository();
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          now: () => now,
          idGenerator: () => 'meeting-1',
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.meetings.single.id, 'meeting-1');
    expect(repository.meetings.single.weekday, DateTime.monday);
    expect(repository.meetings.single.startMinutes, 480);
    expect(repository.meetings.single.endMinutes, 580);
    expect(repository.meetings.single.lessonCount, QuantidadeAulas.two);
    expect(repository.meetings.single.callCount, NumeroChamadas.one);
    expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);
    expect(find.text('2 aulas • 1 chamada'), findsOneWidget);

    await tester.tap(find.byTooltip('Editar horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meeting-weekday')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Terça-feira').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '10:00');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('4 aulas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('meeting-calls')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('2 chamadas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    expect(repository.meetings.single.startMinutes, 600);
    expect(repository.meetings.single.weekday, DateTime.tuesday);
    expect(repository.meetings.single.endMinutes, 800);
    expect(repository.meetings.single.lessonCount, QuantidadeAulas.four);
    expect(repository.meetings.single.callCount, NumeroChamadas.two);
    expect(find.text('Terça-feira • 10:00–13:20'), findsOneWidget);

    await tester.tap(find.byTooltip('Excluir horário de terça-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();

    expect(repository.meetings, isEmpty);
    expect(find.text('Nenhum horário cadastrado'), findsOneWidget);
  });

  testWidgets('validates time, configuration, and duplicate weekly slots', (
    tester,
  ) async {
    final existing = MeetingRecord(
      id: 'existing',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(meetings: [existing]);
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(
          course: course,
          repository: repository,
          now: () => now,
          idGenerator: () => 'new-meeting',
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();

    await tester.enterText(find.byKey(const Key('meeting-start')), '25:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use um horário válido no formato HH:MM.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '08:00');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Já existe um horário nessa disciplina nesse dia e hora.'),
      findsOneWidget,
    );
    expect(repository.meetings, [existing]);
  });

  testWidgets('recovers from loading and persistence failures', (tester) async {
    final existing = MeetingRecord(
      id: 'existing',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(meetings: [existing])
      ..listError = StateError('offline');
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(course: course, repository: repository),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível carregar a grade.'), findsOneWidget);

    repository.listError = null;
    await tester.tap(find.text('Tentar novamente'));
    await tester.pumpAndSettle();
    expect(find.text('Segunda-feira • 08:00–09:40'), findsOneWidget);

    repository.saveError = StateError('offline');
    await tester.tap(find.byTooltip('Editar horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível salvar o horário.'), findsOneWidget);
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancelar'));
    await tester.pumpAndSettle();
    expect(repository.meetings, [existing]);

    repository.deleteError = StateError('offline');
    await tester.tap(find.byTooltip('Excluir horário de segunda-feira'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Excluir'));
    await tester.pumpAndSettle();
    expect(find.text('Não foi possível excluir o horário.'), findsOneWidget);
    expect(repository.meetings, [existing]);
  });

  testWidgets('handles late endings, one lesson, sorting, and default ids', (
    tester,
  ) async {
    final tuesday = MeetingRecord(
      id: 'tuesday',
      weekday: DateTime.tuesday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final mondayLate = MeetingRecord(
      id: 'monday-late',
      weekday: DateTime.monday,
      startMinutes: 600,
      endMinutes: 700,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final mondayEarly = MeetingRecord(
      id: 'monday-early',
      weekday: DateTime.monday,
      startMinutes: 480,
      endMinutes: 580,
      lessonCount: QuantidadeAulas.two,
      callCount: NumeroChamadas.one,
      createdAt: now,
      updatedAt: now,
    );
    final repository = _FakeMeetingRepository(
      meetings: [tuesday, mondayLate, mondayEarly],
    );
    await tester.pumpWidget(
      MaterialApp(
        home: CourseSchedulePage(course: course, repository: repository),
      ),
    );
    await tester.pumpAndSettle();

    final earlyY = tester
        .getTopLeft(find.text('Segunda-feira • 08:00–09:40'))
        .dy;
    final lateY = tester
        .getTopLeft(find.text('Segunda-feira • 10:00–11:40'))
        .dy;
    final tuesdayY = tester
        .getTopLeft(find.text('Terça-feira • 08:00–09:40'))
        .dy;
    expect(earlyY, lessThan(lateY));
    expect(lateY, lessThan(tuesdayY));

    await tester.tap(find.byKey(const Key('add-meeting')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('meeting-start')), '08:99');
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('Use um horário válido no formato HH:MM.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '23:30');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('4 aulas').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();
    expect(
      find.text('O horário termina depois da meia-noite.'),
      findsOneWidget,
    );

    await tester.enterText(find.byKey(const Key('meeting-start')), '14:00');
    await tester.tap(find.byKey(const Key('meeting-lessons')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('1 aula').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Salvar'));
    await tester.pumpAndSettle();

    final created = repository.meetings.singleWhere(
      (meeting) => meeting.startMinutes == 840,
    );
    expect(created.id, isNotEmpty);
    expect(created.lessonCount, QuantidadeAulas.one);
    expect(created.callCount, NumeroChamadas.one);
    expect(created.endMinutes, 890);
  });
}

final class _FakeMeetingRepository implements MeetingRepository {
  _FakeMeetingRepository({List<MeetingRecord>? meetings})
    : meetings = meetings ?? [];

  final List<MeetingRecord> meetings;
  Object? listError;
  Object? saveError;
  Object? deleteError;

  @override
  Future<void> deleteMeeting(String courseId, String meetingId) async {
    if (deleteError case final error?) throw error;
    meetings.removeWhere((meeting) => meeting.id == meetingId);
  }

  @override
  Future<List<MeetingRecord>> listMeetings(String courseId) async {
    if (listError case final error?) throw error;
    return List.of(meetings);
  }

  @override
  Future<void> saveMeeting(String courseId, MeetingRecord meeting) async {
    if (saveError case final error?) throw error;
    meetings.removeWhere((item) => item.id == meeting.id);
    meetings.add(meeting);
  }
}
