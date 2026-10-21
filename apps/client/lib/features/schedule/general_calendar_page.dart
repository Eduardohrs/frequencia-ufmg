import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../design/course_identity.dart';

enum CalendarDisplay { month, list }

class GeneralCalendarPage extends StatefulWidget {
  const GeneralCalendarPage({
    required this.courses,
    required this.repository,
    required this.location,
    required this.now,
    this.initialCourseId,
    this.initialSessionsByCourse,
    super.key,
  });

  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;
  final DateTime Function() now;
  final String? initialCourseId;
  final Map<String, List<SessionRecord>>? initialSessionsByCourse;

  @override
  State<GeneralCalendarPage> createState() => _GeneralCalendarPageState();
}

class _GeneralCalendarPageState extends State<GeneralCalendarPage> {
  List<_CalendarEntry> _entries = const [];
  late String? _courseId;
  late DateTime _month;
  CalendarDisplay _display = CalendarDisplay.month;
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _courseId = widget.initialCourseId;
    final localNow = tz.TZDateTime.from(widget.now(), widget.location);
    _month = DateTime(localNow.year, localNow.month);
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final initial = widget.initialSessionsByCourse;
      final loaded = initial != null
          ? [
              for (final course in widget.courses)
                [
                  for (final session
                      in initial[course.id] ?? const <SessionRecord>[])
                    _CalendarEntry(course, session),
                ],
            ]
          : await Future.wait([
              for (final course in widget.courses)
                widget.repository
                    .listSessions(course.id)
                    .then(
                      (sessions) => [
                        for (final session in sessions)
                          _CalendarEntry(course, session),
                      ],
                    ),
            ]);
      final entries = loaded.expand((items) => items).toList()
        ..sort((a, b) => a.session.startsAt.compareTo(b.session.startsAt));
      if (mounted) setState(() => _entries = entries);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<_CalendarEntry> get _filtered => _entries.where((entry) {
    final operational =
        entry.session.calendarStatus == SessionCalendarStatus.scheduled ||
        entry.session.calendarStatus == SessionCalendarStatus.makeup;
    return operational && (_courseId == null || entry.course.id == _courseId);
  }).toList();

  void _moveMonth(int delta) =>
      setState(() => _month = DateTime(_month.year, _month.month + delta));

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Calendário')),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980),
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: LayoutBuilder(
              builder: (context, constraints) {
                final enlargedText =
                    MediaQuery.textScalerOf(context).scale(14) > 20;
                final scrollWholePage =
                    constraints.maxWidth < 320 || enlargedText;
                final children = <Widget>[
                  Text(
                    'Calendário operacional',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Aulas, reposições e avaliações em uma visão só.',
                    style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 20),
                  Wrap(
                    spacing: 12,
                    runSpacing: 12,
                    children: [
                      SizedBox(
                        width: 260,
                        child: DropdownButtonFormField<String?>(
                          key: const Key('calendar-course-filter'),
                          initialValue: _courseId,
                          decoration: const InputDecoration(
                            labelText: 'Disciplina',
                          ),
                          items: [
                            const DropdownMenuItem(
                              value: null,
                              child: Text('Todas'),
                            ),
                            for (final course in widget.courses)
                              DropdownMenuItem(
                                value: course.id,
                                child: Text(course.code),
                              ),
                          ],
                          onChanged: (value) =>
                              setState(() => _courseId = value),
                        ),
                      ),
                      SegmentedButton<CalendarDisplay>(
                        showSelectedIcon: false,
                        segments:
                            MediaQuery.sizeOf(context).width < 420 ||
                                MediaQuery.textScalerOf(context).scale(14) > 20
                            ? const [
                                ButtonSegment(
                                  value: CalendarDisplay.month,
                                  icon: Icon(Icons.calendar_month_outlined),
                                  label: Text('Mês'),
                                ),
                                ButtonSegment(
                                  value: CalendarDisplay.list,
                                  icon: Icon(Icons.view_agenda_outlined),
                                  label: Text('Lista'),
                                ),
                              ]
                            : const [
                                ButtonSegment(
                                  value: CalendarDisplay.month,
                                  label: Text('Calendário'),
                                ),
                                ButtonSegment(
                                  value: CalendarDisplay.list,
                                  label: Text('Lista'),
                                ),
                              ],
                        selected: {_display},
                        onSelectionChanged: (value) =>
                            setState(() => _display = value.single),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (scrollWholePage)
                    SizedBox(height: 520, child: _content())
                  else
                    Expanded(child: _content()),
                ];
                if (scrollWholePage) {
                  return ListView(children: children);
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: children,
                );
              },
            ),
          ),
        ),
      ),
    ),
  );

  Widget _content() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_failed) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Não foi possível carregar o calendário.'),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _load,
              child: const Text('Tentar novamente'),
            ),
          ],
        ),
      );
    }
    if (_display == CalendarDisplay.list) return _list();
    return _calendar();
  }

  Widget _list() {
    final entries = _filtered;
    if (entries.isEmpty) {
      return const Center(child: Text('Nenhuma sessão encontrada'));
    }
    return ListView.separated(
      itemCount: entries.length,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (_, index) => _entryTile(entries[index]),
    );
  }

  Widget _calendar() {
    final first = DateTime(_month.year, _month.month, 1);
    final firstCell = first.subtract(Duration(days: first.weekday - 1));
    final textScale = MediaQuery.textScalerOf(context).scale(14) / 14;
    final compactDays =
        MediaQuery.sizeOf(context).width < 420 || textScale > 1.4;
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (compactDays)
              IconButton(
                tooltip: 'Mês anterior',
                onPressed: () => _moveMonth(-1),
                icon: const Icon(Icons.chevron_left_rounded),
              )
            else
              TextButton(
                onPressed: () => _moveMonth(-1),
                child: const Text('Anterior'),
              ),
            Expanded(
              child: Text(
                '${_monthName(_month.month)} ${_month.year}',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            if (compactDays)
              IconButton(
                tooltip: 'Próximo mês',
                onPressed: () => _moveMonth(1),
                icon: const Icon(Icons.chevron_right_rounded),
              )
            else
              TextButton(
                onPressed: () => _moveMonth(1),
                child: const Text('Próximo'),
              ),
          ],
        ),
        Row(
          children: [
            for (final day in ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'])
              Expanded(child: Center(child: Text(compactDays ? day[0] : day))),
          ],
        ),
        const SizedBox(height: 8),
        Expanded(
          child: GridView.builder(
            key: const Key('month-calendar-grid'),
            itemCount: 42,
            gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 7,
              childAspectRatio: compactDays ? .42 : .9,
            ),
            itemBuilder: (_, index) {
              final day = firstCell.add(Duration(days: index));
              final entries = _filtered.where((entry) {
                final local = tz.TZDateTime.from(
                  entry.session.startsAt,
                  widget.location,
                );
                return local.year == day.year &&
                    local.month == day.month &&
                    local.day == day.day;
              }).toList();
              final isToday = DateUtils.isSameDay(day, widget.now());
              return Container(
                key: ValueKey(
                  'calendar-day-${day.toIso8601String().substring(0, 10)}',
                ),
                margin: const EdgeInsets.all(2),
                padding: EdgeInsets.all(compactDays ? 2 : 6),
                decoration: BoxDecoration(
                  color: isToday
                      ? Theme.of(context).colorScheme.primaryContainer
                      : day.month == _month.month
                      ? Theme.of(context).colorScheme.surface
                      : Colors.transparent,
                  border: Border.all(
                    color: Theme.of(context).colorScheme.outlineVariant,
                  ),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${day.day}',
                      maxLines: 1,
                      softWrap: false,
                      style: TextStyle(
                        color: day.month == _month.month
                            ? null
                            : Theme.of(context).disabledColor,
                      ),
                    ),
                    for (final entry in entries.take(2))
                      _CalendarEventLabel(entry: entry),
                    if (entries.length > 2) Text('+${entries.length - 2}'),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _entryTile(_CalendarEntry entry) {
    final local = tz.TZDateTime.from(entry.session.startsAt, widget.location);
    return Card(
      elevation: 0,
      child: ListTile(
        leading: CourseMark(
          key: Key('calendar-course-mark-${entry.course.id}'),
          code: entry.course.code,
          size: 40,
        ),
        title: Text('${entry.course.code} • ${_date(local)}'),
        subtitle: Text(
          [
            '${_time(local)} • ${_status(entry.session.calendarStatus)}',
            if (entry.session.assessmentTitle case final title?)
              'Avaliação: $title',
          ].join('\n'),
        ),
        trailing: entry.session.assessmentTitle == null
            ? null
            : const Icon(Icons.assignment_outlined),
      ),
    );
  }
}

class _CalendarEventLabel extends StatelessWidget {
  const _CalendarEventLabel({required this.entry});

  final _CalendarEntry entry;

  @override
  Widget build(BuildContext context) {
    final identity = CourseIdentity.fromCode(entry.course.code);
    return Row(
      children: [
        Container(
          width: 4,
          height: 14,
          decoration: BoxDecoration(
            color: identity.color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            entry.course.code,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ),
        if (entry.session.assessmentTitle != null)
          const Padding(
            padding: EdgeInsets.only(left: 2),
            child: Icon(Icons.assignment_outlined, size: 12),
          ),
      ],
    );
  }
}

final class _CalendarEntry {
  const _CalendarEntry(this.course, this.session);
  final CourseRecord course;
  final SessionRecord session;
}

String _date(DateTime value) =>
    '${value.day.toString().padLeft(2, '0')}/${value.month.toString().padLeft(2, '0')}/${value.year}';
String _time(DateTime value) =>
    '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
String _status(SessionCalendarStatus status) => switch (status) {
  SessionCalendarStatus.scheduled => 'Programada',
  SessionCalendarStatus.cancelled ||
  SessionCalendarStatus.holiday => 'Cancelada/feriado',
  SessionCalendarStatus.noCall => 'Aula sem chamada',
  SessionCalendarStatus.makeup => 'Reposição',
};
String _monthName(int month) => const [
  'Janeiro',
  'Fevereiro',
  'Março',
  'Abril',
  'Maio',
  'Junho',
  'Julho',
  'Agosto',
  'Setembro',
  'Outubro',
  'Novembro',
  'Dezembro',
][month - 1];
