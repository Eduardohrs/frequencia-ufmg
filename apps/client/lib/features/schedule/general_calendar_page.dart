import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';
import 'package:flutter/foundation.dart';
import '../../data/python_overview_repository.dart';
import '../../backend/python_backend_transport.dart';
import '../../data/academic_agenda.dart';
import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../design/course_identity.dart';

enum CalendarDisplay { month, list }

enum CalendarEntryType { all, lesson, assessment, deadline }

class CalendarNavigationState {
  String? courseId;
  DateTime? month;
  CalendarDisplay display = CalendarDisplay.month;
  CalendarEntryType type = CalendarEntryType.all;
}

class GeneralCalendarPage extends StatefulWidget {
  const GeneralCalendarPage({
    required this.courses,
    required this.repository,
    required this.location,
    required this.now,
    this.initialCourseId,
    this.navigationState,
    this.logger,
    this.onOpenCourse,
    this.initialDate,
    this.initialSessionsByCourse,
    this.overviewUpdates,
    this.datesByCourse = const {},
    this.unavailableDateCourses = const {},
    super.key,
  });

  final ValueListenable<AcademicOverviewSnapshot?>? overviewUpdates;
  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;
  final DateTime Function() now;
  final String? initialCourseId;
  final DateTime? initialDate;
  final CalendarNavigationState? navigationState;
  final AppLogger? logger;
  final Future<void> Function(CourseRecord)? onOpenCourse;
  final Map<String, List<SessionRecord>>? initialSessionsByCourse;
  final Map<String, List<PythonMoodleDate>> datesByCourse;
  final Set<String> unavailableDateCourses;

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
  int _loadVersion = 0;
  CalendarEntryType _type = CalendarEntryType.all;

  @override
  void initState() {
    super.initState();
    _courseId = widget.initialCourseId ?? widget.navigationState?.courseId;
    if (!widget.courses.any((course) => course.id == _courseId)) {
      _courseId = null;
    }
    _display = widget.navigationState?.display ?? CalendarDisplay.month;
    _type = widget.navigationState?.type ?? CalendarEntryType.all;
    final localNow = tz.TZDateTime.from(widget.now(), widget.location);
    final date =
        widget.initialDate ?? widget.navigationState?.month ?? localNow;
    _month = DateTime(date.year, date.month);
    _remember();
    widget.overviewUpdates?.addListener(_overviewChanged);
    _load();
  }

  @override
  void dispose() {
    widget.overviewUpdates?.removeListener(_overviewChanged);
    super.dispose();
  }

  void _overviewChanged() {
    _load();
  }

  Map<String, List<PythonMoodleDate>> get _datesByCourse =>
      widget.overviewUpdates?.value?.datesByCourse ?? widget.datesByCourse;
  Set<String> get _unavailableDateCourses =>
      widget.overviewUpdates?.value?.unavailableDateCourses ??
      widget.unavailableDateCourses;

  void _event(String event, Map<String, Object> fields) {
    final logger = widget.logger;
    if (logger != null) {
      emitOperationalEvent(logger, event, {
        'screen': 'calendar',
        'operation_id': newCorrelationId('calendar'),
        'course_id': _courseId ?? 'all',
        ...fields,
      });
    }
  }

  void _remember() {
    final state = widget.navigationState;
    if (state != null) {
      state.courseId = _courseId;
      state.month = _month;
      state.display = _display;
      state.type = _type;
    }
  }

  void _change(VoidCallback update, String action) {
    setState(update);
    _remember();
    _event('calendar_view_changed', {
      'action': action,
      'month': _month.toIso8601String(),
      'display': _display.name,
      'type': _type.name,
    });
  }

  Future<void> _load() async {
    final version = ++_loadVersion;
    final watch = Stopwatch()..start();
    final operationId = newCorrelationId('calendar_read');
    _event('calendar_read_started', {
      'load_version': version,
      'operation_id': operationId,
    });
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final loaded = await Future.wait([
        for (final course in widget.courses)
          () async {
            final sessions =
                (widget.overviewUpdates?.value?.sessionsByCourse ??
                    widget.initialSessionsByCourse)?[course.id] ??
                await widget.repository.listSessions(course.id);
            return [
              for (final event in courseAgenda(
                course,
                sessions,
                _datesByCourse[course.id] ?? [],
                includeLessons: true,
              ))
                _CalendarEntry(course, event),
            ];
          }(),
      ]);
      final entries = loaded.expand((items) => items).toList()
        ..sort((a, b) => a.session.startsAt.compareTo(b.session.startsAt));
      final applied = mounted && version == _loadVersion;
      if (applied) setState(() => _entries = entries);
      _event('calendar_read_succeeded', {
        'load_version': version,
        'operation_id': operationId,
        'applied_to_view': applied,
        'item_count': entries.length,
        'duration_ms': watch.elapsedMilliseconds,
      });
    } catch (error, stack) {
      final logger = widget.logger;
      if (logger != null) {
        recordOperationalFailure(logger, error, stack, 'calendar_read', {
          'screen': 'calendar',
          'operation_id': operationId,
          'load_version': version,
          'duration_ms': watch.elapsedMilliseconds,
          'applied_to_view': mounted && version == _loadVersion,
        }, failureCode: 'calendar_read_failed');
      }
      if (mounted && version == _loadVersion) setState(() => _failed = true);
    } finally {
      if (mounted && version == _loadVersion) setState(() => _loading = false);
    }
  }

  List<_CalendarEntry> get _filtered => _entries.where((entry) {
    return (_courseId == null || entry.course.id == _courseId) &&
        (_type == CalendarEntryType.all || entry.type == _type);
  }).toList();

  void _moveMonth(int delta) => _change(
    () => _month = DateTime(_month.year, _month.month + delta),
    'month',
  );

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
                          isExpanded: true,
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
                              _change(() => _courseId = value, 'course_filter'),
                        ),
                      ),
                      SizedBox(
                        width: 200,
                        child: DropdownButtonFormField<CalendarEntryType>(
                          key: const Key('calendar-type-filter'),
                          isExpanded: true,
                          initialValue: _type,
                          decoration: const InputDecoration(labelText: 'Tipo'),
                          items: [
                            for (final type in CalendarEntryType.values)
                              DropdownMenuItem(
                                value: type,
                                child: Text(_typeLabel(type)),
                              ),
                          ],
                          onChanged: (value) =>
                              _change(() => _type = value!, 'type_filter'),
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
                            _change(() => _display = value.single, 'display'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  if (_unavailableDateCourses.isNotEmpty)
                    const Text(
                      'Algumas datas não puderam ser atualizadas. As aulas continuam disponíveis.',
                    ),
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
                    InkWell(
                      onTap: () => _openDay(day, entries),
                      child: Text(
                        '${day.day}',
                        maxLines: 1,
                        softWrap: false,
                        style: TextStyle(
                          color: day.month == _month.month
                              ? null
                              : Theme.of(context).disabledColor,
                        ),
                      ),
                    ),
                    for (final entry in entries.take(2))
                      InkWell(
                        onTap: () => _openEntry(entry),
                        child: _CalendarEventLabel(entry: entry),
                      ),
                    if (entries.length > 2)
                      InkWell(
                        onTap: () => _openDay(day, entries),
                        child: Text('+${entries.length - 2}'),
                      ),
                  ],
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  Future<void> _openDay(DateTime day, List<_CalendarEntry> entries) async {
    _event('calendar_day_opened', {
      'date': day.toIso8601String(),
      'item_count': entries.length,
    });
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(sheet).height * .7,
          child: Column(
            children: [
              ListTile(
                title: Text(_date(day)),
                trailing: IconButton(
                  tooltip: 'Fechar dia',
                  onPressed: () => Navigator.pop(sheet),
                  icon: const Icon(Icons.close),
                ),
              ),
              Expanded(
                child: entries.isEmpty
                    ? const Center(child: Text('Nenhum item neste dia.'))
                    : ListView(
                        children: [
                          for (final entry in entries) _entryTile(entry),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _openEntry(_CalendarEntry entry) async {
    final fields = <String, Object>{
      'operation_id': newCorrelationId('calendar_entry'),
      'course_id': entry.course.id,
      'entry_id': entry.session.session?.id ?? entry.session.date?.id ?? '',
      'date': entry.session.startsAt.toIso8601String(),
      'type': entry.type.name,
    };
    _event('calendar_entry_opened', fields);
    final open = await showModalBottomSheet<bool>(
      context: context,
      builder: (sheet) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                entry.session.title ?? 'Aula de ${entry.course.code}',
                style: Theme.of(sheet).textTheme.titleLarge,
              ),
              Text(entry.course.name),
              Text(
                '${_date(tz.TZDateTime.from(entry.session.startsAt, widget.location))} • ${_time(tz.TZDateTime.from(entry.session.startsAt, widget.location))}',
              ),
              Text(
                entry.session.session == null
                    ? _typeLabel(entry.type)
                    : _status(entry.session.session!.calendarStatus),
              ),
              if (widget.onOpenCourse != null)
                TextButton(
                  onPressed: () => Navigator.pop(sheet, true),
                  child: const Text('Abrir disciplina'),
                ),
              TextButton(
                onPressed: () => Navigator.pop(sheet),
                child: const Text('Fechar'),
              ),
            ],
          ),
        ),
      ),
    );
    _event('calendar_entry_closed', {...fields, 'open_course': open == true});
    if (open != true || !mounted) return;
    try {
      await widget.onOpenCourse!(entry.course);
      _event('calendar_course_navigation_finished', {
        ...fields,
        'applied_to_view': mounted,
      });
    } catch (error, stack) {
      final logger = widget.logger;
      if (logger != null) {
        recordOperationalFailure(
          logger,
          error,
          stack,
          'calendar_course_navigation',
          fields,
          failureCode: 'calendar_navigation_failed',
        );
      }
    }
  }

  Widget _entryTile(_CalendarEntry entry) {
    final local = tz.TZDateTime.from(entry.session.startsAt, widget.location);
    return Card(
      elevation: 0,
      child: ListTile(
        onTap: () => _openEntry(entry),
        leading: CourseMark(
          key: Key('calendar-course-mark-${entry.course.id}'),
          code: entry.course.code,
          size: 40,
        ),
        title: Text('${entry.course.code} • ${_date(local)}'),
        subtitle: Text(
          [
            '${_time(local)} • ${(entry.session.session == null ? 'Prazo' : _status(entry.session.session!.calendarStatus))}',
            if (entry.session.session != null && !entry.course.tracksAttendance)
              'Sem chamada',
            if (entry.session.title case final title?)
              '${entry.type == CalendarEntryType.deadline ? 'Prazo' : 'Avaliação'}: $title',
          ].join('\n'),
        ),
        trailing: entry.session.title == null
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
            '${entry.course.code}${entry.isNoCall ? ' · Sem chamada' : ''}',
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: !entry.isNoCall || entry.session.title != null
                  ? null
                  : Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        if (entry.session.title != null)
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
  final AgendaEntry session;
  CalendarEntryType get type => session.session != null
      ? (session.title == null
            ? CalendarEntryType.lesson
            : CalendarEntryType.assessment)
      : (session.date?.kind == 'assessment' || session.date?.kind == 'quiz'
            ? CalendarEntryType.assessment
            : CalendarEntryType.deadline);
  bool get isNoCall =>
      session.session != null &&
      (!course.tracksAttendance ||
          session.session!.calendarStatus == SessionCalendarStatus.noCall);
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

String _typeLabel(CalendarEntryType value) => switch (value) {
  CalendarEntryType.all => 'Todos',
  CalendarEntryType.lesson => 'Aulas',
  CalendarEntryType.assessment => 'Avaliações',
  CalendarEntryType.deadline => 'Entregas e prazos',
};
