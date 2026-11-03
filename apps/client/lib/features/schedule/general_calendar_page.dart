import 'package:shared_preferences/shared_preferences.dart';
import '../../design/course_visuals.dart';
import '../../design/app_feedback.dart';
import 'dart:async';
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

enum CalendarRange { week, fortnight, month }

enum CalendarEntryType { all, lesson, assessment, deadline }

class CalendarNavigationState {
  CalendarRange? range;
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
    this.preferences,
    this.initialCourseId,
    this.initialEntryId,
    this.navigationState,
    this.logger,
    this.onOpenCourse,
    this.onOpenActivities,
    this.initialDate,
    this.initialSessionsByCourse,
    this.overviewUpdates,
    this.datesByCourse = const {},
    this.unavailableDateCourses = const {},
    super.key,
  });

  final SharedPreferencesAsync? preferences;
  final ValueListenable<AcademicOverviewSnapshot?>? overviewUpdates;
  final List<CourseRecord> courses;
  final SessionRepository repository;
  final tz.Location location;
  final DateTime Function() now;
  final String? initialCourseId;
  final String? initialEntryId;
  final DateTime? initialDate;
  final CalendarNavigationState? navigationState;
  final AppLogger? logger;
  final Future<void> Function(CourseRecord)? onOpenCourse;
  final Future<void> Function(CourseRecord)? onOpenActivities;
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
  CalendarRange _range = CalendarRange.week;
  bool _defaultsApplied = false;
  bool _preferenceTouched = false;
  String? _owner;
  late final _preferences = widget.preferences ?? SharedPreferencesAsync();
  Future<void> _preferenceSave = Future.value();
  bool _loading = true;
  bool _initialEntryOpened = false;
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
    _month = DateTime(date.year, date.month, date.day);
    widget.overviewUpdates?.addListener(_overviewChanged);
    _load();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_defaultsApplied) return;
    _defaultsApplied = true;
    final retained = widget.navigationState?.range;
    _range =
        retained ??
        (MediaQuery.sizeOf(context).width >= 900
            ? CalendarRange.fortnight
            : CalendarRange.week);
    _owner = CourseVisualHost.of(context, listen: false)?.owner;
    _remember();
    if (retained == null && _owner != null) unawaited(_restorePreference());
  }

  Future<void> _restorePreference() async {
    final fields = <String, Object>{
      'operation_id': newCorrelationId('calendar_preference'),
      'stage': 'preference_read',
    };
    final watch = Stopwatch()..start();
    try {
      final stored = await _preferences.getString(
        'calendar_view.v1.${Uri.encodeComponent(_owner!)}',
      );
      if (stored != null) {
        final parts = stored.split('/');
        if (parts.length != 2 ||
            !CalendarRange.values.any((r) => r.name == parts[0]) ||
            !CalendarDisplay.values.any((d) => d.name == parts[1])) {
          throw const FormatException('Invalid calendar preference');
        }
        if (mounted && !_preferenceTouched) {
          setState(() {
            _range = CalendarRange.values.byName(parts[0]);
            _display = CalendarDisplay.values.byName(parts[1]);
          });
          _remember();
        }
      }
      _event('calendar_preference_read_succeeded', {
        ...fields,
        'duration_ms': watch.elapsedMilliseconds,
        'applied_to_view': mounted && !_preferenceTouched,
      });
    } catch (error, stack) {
      if (widget.logger case final logger?) {
        recordOperationalFailure(
          logger,
          error,
          stack,
          'calendar_preference_read',
          {...fields, 'duration_ms': watch.elapsedMilliseconds},
          failureCode: 'calendar_preference_failed',
        );
      }
    }
  }

  void _savePreference() {
    if (_owner == null) return;
    final key = 'calendar_view.v1.${Uri.encodeComponent(_owner!)}';
    final value = '${_range.name}/${_display.name}';
    _preferenceSave = _preferenceSave.then((_) async {
      final fields = <String, Object>{
        'operation_id': newCorrelationId('calendar_preference'),
        'stage': 'preference_write',
        'selection': value,
      };
      final watch = Stopwatch()..start();
      try {
        await _preferences.setString(key, value);
        _event('calendar_preference_write_succeeded', {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
        });
      } catch (error, stack) {
        if (widget.logger case final logger?) {
          recordOperationalFailure(
            logger,
            error,
            stack,
            'calendar_preference_write',
            {...fields, 'duration_ms': watch.elapsedMilliseconds},
            failureCode: 'calendar_preference_failed',
          );
        }
      }
    });
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
        'range': _range.name,
        'range_start': _rangeStart.toIso8601String(),
        'range_end_exclusive': _rangeEnd.toIso8601String(),
        'visible_entry_count': _windowEntries.length,
        ...fields,
      });
    }
  }

  void _remember() {
    final state = widget.navigationState;
    if (state != null) {
      state.range = _range;
      state.courseId = _courseId;
      state.month = _month;
      state.display = _display;
      state.type = _type;
    }
  }

  void _change(VoidCallback update, String action) {
    _preferenceTouched = true;
    setState(update);
    _remember();
    if (action == 'range' || action == 'display') _savePreference();
    _event('calendar_view_changed', {
      'action': action,
      'month': _month.toIso8601String(),
      'display': _display.name,
      'range': _range.name,
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
      if (applied) {
        setState(() => _entries = entries);
        if (!_initialEntryOpened && widget.initialEntryId != null) {
          _initialEntryOpened = true;
          final entry = entries
              .where(
                (item) =>
                    item.course.id == widget.initialCourseId &&
                    (item.session.session?.id ?? item.session.date?.id) ==
                        widget.initialEntryId,
              )
              .firstOrNull;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted) return;
            if (entry != null) {
              unawaited(_openEntry(entry));
            } else {
              _event('calendar_entry_not_found', {
                'operation_id': operationId,
                'stage': 'entry_lookup',
                'course_id': widget.initialCourseId!,
                'entry_id': widget.initialEntryId!,
              });
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Esta data não está mais disponível.'),
                ),
              );
            }
          });
        }
      }
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

  DateTime get _rangeStart {
    if (_range == CalendarRange.month) {
      return DateTime(_month.year, _month.month);
    }
    return DateTime(
      _month.year,
      _month.month,
      _month.day,
    ).subtract(Duration(days: _month.weekday - 1));
  }

  DateTime get _rangeEnd => _range == CalendarRange.month
      ? DateTime(_month.year, _month.month + 1)
      : _rangeStart.add(Duration(days: _range == CalendarRange.week ? 7 : 14));
  List<_CalendarEntry> get _windowEntries => _filtered.where((entry) {
    final local = tz.TZDateTime.from(entry.session.startsAt, widget.location);
    final day = DateTime(local.year, local.month, local.day);
    return !day.isBefore(_rangeStart) && day.isBefore(_rangeEnd);
  }).toList();
  void _moveMonth(int delta) => _change(() {
    _month = _range == CalendarRange.month
        ? DateTime(_month.year, _month.month + delta)
        : _month.add(
            Duration(days: delta * (_range == CalendarRange.week ? 7 : 14)),
          );
  }, 'period');
  void _today() => _change(() {
    final local = tz.TZDateTime.from(widget.now(), widget.location);
    _month = DateTime(local.year, local.month, local.day);
  }, 'today');
  Widget _periodBar() => Row(
    children: [
      IconButton(
        tooltip: 'Período anterior',
        constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
        onPressed: () => _moveMonth(-1),
        icon: const Icon(Icons.chevron_left_rounded),
      ),
      Expanded(
        child: Text(
          _range == CalendarRange.month
              ? '${_monthName(_month.month)} ${_month.year}'
              : '${_date(_rangeStart)} – ${_date(_rangeEnd.subtract(const Duration(days: 1)))}',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.titleSmall,
        ),
      ),
      TextButton(
        style: TextButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          minimumSize: const Size(40, 40),
        ),
        onPressed: _today,
        child: const Text('Hoje'),
      ),
      IconButton(
        tooltip: 'Próximo período',
        constraints: const BoxConstraints(minWidth: 40, minHeight: 40),
        onPressed: () => _moveMonth(1),
        icon: const Icon(Icons.chevron_right_rounded),
      ),
    ],
  );

  Future<void> _filters() async {
    final operationId = newCorrelationId('calendar_filters');
    final watch = Stopwatch()..start();
    _event('calendar_filters_opened', {
      'operation_id': operationId,
      'stage': 'filters',
    });
    var courseId = _courseId;
    var type = _type;
    var range = _range;
    var display = _display;
    final result = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (sheet) => StatefulBuilder(
        builder: (sheet, refresh) => Padding(
          padding: EdgeInsets.fromLTRB(
            20,
            16,
            20,
            20 + MediaQuery.viewInsetsOf(sheet).bottom,
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        'Sua agenda',
                        style: Theme.of(sheet).textTheme.titleLarge,
                      ),
                    ),
                    IconButton(
                      tooltip: 'Fechar filtros',
                      onPressed: () => Navigator.pop(sheet),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String?>(
                  key: const Key('calendar-course-filter'),
                  initialValue: courseId,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Disciplina'),
                  items: [
                    const DropdownMenuItem(value: null, child: Text('Todas')),
                    for (final course in widget.courses)
                      DropdownMenuItem(
                        value: course.id,
                        child: Text(course.displayName),
                      ),
                  ],
                  onChanged: (value) => refresh(() => courseId = value),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<CalendarEntryType>(
                  key: const Key('calendar-type-filter'),
                  initialValue: type,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Tipo'),
                  items: [
                    for (final value in CalendarEntryType.values)
                      DropdownMenuItem(
                        value: value,
                        child: Text(_typeLabel(value)),
                      ),
                  ],
                  onChanged: (value) => refresh(() => type = value!),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<CalendarRange>(
                  key: ValueKey('calendar-range-${range.name}'),
                  initialValue: range,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Período'),
                  items: const [
                    DropdownMenuItem(
                      value: CalendarRange.week,
                      child: Text('Semana'),
                    ),
                    DropdownMenuItem(
                      value: CalendarRange.fortnight,
                      child: Text('2 semanas'),
                    ),
                    DropdownMenuItem(
                      value: CalendarRange.month,
                      child: Text('Mês'),
                    ),
                  ],
                  onChanged: (value) => refresh(() => range = value!),
                ),
                const SizedBox(height: 16),
                SegmentedButton<CalendarDisplay>(
                  key: const Key('calendar-display'),
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(
                      value: CalendarDisplay.month,
                      label: Text('Agenda'),
                    ),
                    ButtonSegment(
                      value: CalendarDisplay.list,
                      label: Text('Lista'),
                    ),
                  ],
                  selected: {display},
                  onSelectionChanged: (value) =>
                      refresh(() => display = value.single),
                ),
                const SizedBox(height: 20),
                Wrap(
                  alignment: WrapAlignment.spaceBetween,
                  spacing: 12,
                  children: [
                    TextButton(
                      onPressed: () => refresh(() {
                        courseId = null;
                        type = CalendarEntryType.all;
                      }),
                      child: const Text('Limpar filtros'),
                    ),
                    FilledButton(
                      onPressed: () => Navigator.pop(sheet, true),
                      child: const Text('Aplicar'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (result != true || !mounted) {
      _event('calendar_filters_closed', {
        'operation_id': operationId,
        'stage': 'filters',
        'outcome': mounted ? 'cancelled' : 'disposed',
        'duration_ms': watch.elapsedMilliseconds,
      });
      return;
    }
    _change(() {
      _courseId = courseId;
      _type = type;
      _range = range;
      _display = display;
    }, 'filters');
    _savePreference();
    _event('calendar_filters_closed', {
      'operation_id': operationId,
      'stage': 'filters',
      'outcome': 'applied',
      'duration_ms': watch.elapsedMilliseconds,
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Agenda'),
      actions: [
        if (MediaQuery.sizeOf(context).width < 360 ||
            MediaQuery.textScalerOf(context).scale(14) > 20)
          IconButton(
            key: const Key('calendar-filters'),
            tooltip: 'Filtros e visualização',
            onPressed: _filters,
            icon: const Icon(Icons.tune),
          )
        else
          TextButton.icon(
            key: const Key('calendar-filters'),
            onPressed: _filters,
            icon: const Icon(Icons.tune),
            label: Text(
              (_courseId != null || _type != CalendarEntryType.all)
                  ? 'Filtros • ${(_courseId != null ? 1 : 0) + (_type != CalendarEntryType.all ? 1 : 0)}'
                  : 'Filtros',
            ),
          ),
        const SizedBox(width: 8),
      ],
    ),
    body: SafeArea(
      top: false,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _periodBar(),
                if (_courseId != null || _type != CalendarEntryType.all)
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          [
                            if (_courseId != null)
                              widget.courses
                                  .firstWhere((c) => c.id == _courseId)
                                  .displayName,
                            if (_type != CalendarEntryType.all)
                              _typeLabel(_type),
                          ].join(' • '),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ),
                      if (widget.onOpenActivities != null && _courseId != null)
                        TextButton.icon(
                          key: const Key('calendar-open-activities'),
                          onPressed: () => _openActivities(
                            widget.courses.firstWhere((c) => c.id == _courseId),
                          ),
                          icon: const Icon(Icons.assignment_outlined, size: 18),
                          label: const Text('Atividades'),
                        ),
                      IconButton(
                        tooltip: 'Limpar filtros ativos',
                        onPressed: () => _change(() {
                          _courseId = null;
                          _type = CalendarEntryType.all;
                        }, 'clear_filters'),
                        icon: const Icon(Icons.close, size: 18),
                      ),
                    ],
                  ),
                if (_unavailableDateCourses.isNotEmpty)
                  const Text(
                    'Algumas datas não puderam ser atualizadas. As aulas continuam disponíveis.',
                  ),
                const SizedBox(height: 4),
                Expanded(
                  child: SizedBox(
                    key: const Key('calendar-content'),
                    child: _content(),
                  ),
                ),
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
    return _range == CalendarRange.month ? _calendar() : _weeks();
  }

  Widget _weeks() => LayoutBuilder(
    builder: (context, constraints) {
      final weeks = _range == CalendarRange.fortnight ? 2 : 1;
      final columns = weeks == 2 && constraints.maxWidth >= 850;
      final window = _windowEntries;
      Widget days(int offset, int count) => ListView(
        children: [
          for (var i = offset; i < offset + count; i++)
            _dayAgenda(_rangeStart.add(Duration(days: i)), window),
        ],
      );
      return columns
          ? Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: days(0, 7)),
                const SizedBox(width: 16),
                Expanded(child: days(7, 7)),
              ],
            )
          : days(0, weeks * 7);
    },
  );
  Widget _dayAgenda(DateTime day, List<_CalendarEntry> window) {
    final entries = window.where((e) {
      final local = tz.TZDateTime.from(e.session.startsAt, widget.location);
      return local.year == day.year &&
          local.month == day.month &&
          local.day == day.day;
    }).toList();
    final today = DateUtils.isSameDay(
      day,
      tz.TZDateTime.from(widget.now(), widget.location),
    );
    if (entries.isEmpty) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Text(
          '${const ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'][day.weekday - 1]} • ${_date(day)} • ${_type == CalendarEntryType.all ? 'Sem aulas ou prazos' : 'Nenhum item para este filtro'}',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '${const ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'][day.weekday - 1]} • ${_date(day)}${today ? ' • Hoje' : ''}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 6),
          for (final entry in entries) _entryTile(entry, showDate: false),
        ],
      ),
    );
  }

  Widget _list() {
    final entries = _windowEntries;
    if (entries.isEmpty) {
      return const AppEmptyState(
        icon: Icons.event_available_outlined,
        title: 'Nenhuma sessão encontrada',
        message: 'Experimente outro filtro para ver suas aulas e datas.',
      );
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
              mainAxisExtent:
                  MediaQuery.textScalerOf(context).scale(14) * 3 +
                  (compactDays ? 16 : 50),
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
                    if (compactDays && entries.isNotEmpty)
                      InkWell(
                        key: ValueKey(
                          'calendar-count-${day.toIso8601String().substring(0, 10)}',
                        ),
                        onTap: () => _openDay(day, entries),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 3),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Wrap(
                                spacing: 2,
                                runSpacing: 2,
                                children: [
                                  for (final entry in entries.take(3))
                                    Container(
                                      width: 5,
                                      height: 5,
                                      decoration: BoxDecoration(
                                        color: courseColor(
                                          context,
                                          entry.course.code,
                                          CourseIdentity.fromCode(
                                            entry.course.code,
                                          ).color,
                                        ),
                                        shape: BoxShape.circle,
                                      ),
                                    ),
                                ],
                              ),
                              Text(
                                '${entries.length}',
                                style: Theme.of(context).textTheme.labelSmall,
                              ),
                            ],
                          ),
                        ),
                      ),
                    if (!compactDays)
                      for (final entry in entries.take(2))
                        InkWell(
                          onTap: () => _openEntry(entry),
                          child: _CalendarEventLabel(entry: entry),
                        ),
                    if (!compactDays && entries.length > 2)
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
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  entry.session.title ?? 'Aula de ${entry.course.displayName}',
                  style: Theme.of(sheet).textTheme.titleLarge,
                ),
                Text(entry.course.displayName),
                Text(
                  '${_date(tz.TZDateTime.from(entry.session.startsAt, widget.location))} • ${_time(tz.TZDateTime.from(entry.session.startsAt, widget.location))}',
                ),
                Text(
                  entry.session.session == null
                      ? _typeLabel(entry.type)
                      : _status(entry.session.session!.calendarStatus),
                ),
                if (widget.onOpenActivities != null &&
                    entry.session.title != null)
                  TextButton(
                    onPressed: () => Navigator.pop(sheet, false),
                    child: const Text('Ver atividades e plano'),
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
      ),
    );
    _event('calendar_entry_closed', {...fields, 'open_course': open == true});
    if (!mounted) return;
    if (open == false) {
      await _openActivities(entry.course);
      return;
    }
    if (open != true) return;
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

  Future<void> _openActivities(CourseRecord course) async {
    final fields = <String, Object>{
      'operation_id': newCorrelationId('calendar_activities'),
      'course_id': course.id,
      'course_name': course.displayName,
      'stage': 'activities_navigation',
    };
    _event('calendar_activities_open_started', fields);
    try {
      await widget.onOpenActivities!(course);
      _event('calendar_activities_open_succeeded', {
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
          'calendar_activities_navigation',
          fields,
          failureCode: 'calendar_navigation_failed',
        );
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Não foi possível abrir as atividades. Tente novamente.',
            ),
          ),
        );
      }
    }
  }

  Widget _entryTile(_CalendarEntry entry, {bool showDate = true}) {
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
        title: Text(
          showDate
              ? '${entry.course.displayName} • ${_date(local)}'
              : entry.course.displayName,
        ),
        subtitle: Text(
          [
            '${_time(local)}${entry.session.session == null ? '' : ' – ${_time(tz.TZDateTime.from(entry.session.session!.endsAt, widget.location))}'} • ${(entry.session.session == null ? 'Prazo' : _status(entry.session.session!.calendarStatus))}',
            if (entry.session.session != null && !entry.course.tracksAttendance)
              'Sem chamada',
            if (entry.session.title case final title?)
              '${entry.type == CalendarEntryType.deadline ? 'Prazo' : 'Avaliação'}: ${compactAcademicTitle(title)}',
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
            color: courseColor(context, entry.course.code, identity.color),
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            '${entry.course.shortName}${entry.isNoCall ? ' · Sem chamada' : ''}',
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
