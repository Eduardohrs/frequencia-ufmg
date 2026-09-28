import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';

enum CalendarDisplay { month, list }

class GeneralCalendarPage extends StatefulWidget {
  const GeneralCalendarPage({
    required this.courses,
    required this.repository,
    required this.location,
    required this.now,
    this.initialCourseId,
    super.key,
  });

  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;
  final DateTime Function() now;
  final String? initialCourseId;

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
      final loaded = await Future.wait([
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

  List<_CalendarEntry> get _filtered => _courseId == null
      ? _entries
      : _entries.where((entry) => entry.course.id == _courseId).toList();

  void _moveMonth(int delta) =>
      setState(() => _month = DateTime(_month.year, _month.month + delta));

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Calendário acadêmico')),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980),
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
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
                        onChanged: (value) => setState(() => _courseId = value),
                      ),
                    ),
                    SegmentedButton<CalendarDisplay>(
                      segments: const [
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
                Expanded(child: _content()),
              ],
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
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            TextButton(
              onPressed: () => _moveMonth(-1),
              child: const Text('Anterior'),
            ),
            SizedBox(
              width: 180,
              child: Text(
                '${_monthName(_month.month)} ${_month.year}',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            TextButton(
              onPressed: () => _moveMonth(1),
              child: const Text('Próximo'),
            ),
          ],
        ),
        Row(
          children: [
            for (final day in ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'])
              Expanded(child: Center(child: Text(day))),
          ],
        ),
        const SizedBox(height: 8),
        Expanded(
          child: GridView.builder(
            key: const Key('month-calendar-grid'),
            itemCount: 42,
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 7,
              childAspectRatio: .9,
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
              return Container(
                key: ValueKey(
                  'calendar-day-${day.toIso8601String().substring(0, 10)}',
                ),
                margin: const EdgeInsets.all(2),
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
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
                      style: TextStyle(
                        color: day.month == _month.month
                            ? null
                            : Theme.of(context).disabledColor,
                      ),
                    ),
                    for (final entry in entries.take(2))
                      Text(
                        entry.course.code,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.labelSmall,
                      ),
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
        title: Text('${entry.course.code} • ${_date(local)}'),
        subtitle: Text(
          '${_time(local)} • ${_status(entry.session.calendarStatus)}',
        ),
      ),
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
  SessionCalendarStatus.cancelled => 'Cancelada',
  SessionCalendarStatus.holiday => 'Feriado',
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
