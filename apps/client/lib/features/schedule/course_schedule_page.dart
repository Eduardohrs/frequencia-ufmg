import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../domain/attendance.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../attendance/attendance_page.dart';
import 'course_date_range_picker.dart';
import 'general_calendar_page.dart';
import 'calendar_exceptions_page.dart';
import 'session_generator.dart';

typedef MeetingIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

enum _ScheduleAction { attendance, calendar, exceptions }

class CourseSchedulePage extends StatefulWidget {
  // Runtime defaults keep production callers free from utility objects.
  // ignore: prefer_const_constructors_in_immutables
  CourseSchedulePage({
    required this.course,
    required this.repository,
    required this.sessionRepository,
    required this.logger,
    this.courseRepository,
    Iterable<CourseRecord>? allCourses,
    Iterable<String>? allCourseIds,
    this.generator,
    MeetingIdGenerator? idGenerator,
    CurrentTime? now,
    super.key,
  }) : idGenerator = idGenerator ?? _newMeetingId,
       allCourses = List.unmodifiable(allCourses ?? [course]),
       allCourseIds = List.unmodifiable(
         allCourseIds ?? (allCourses ?? [course]).map((item) => item.id),
       ),
       now = now ?? DateTime.now;

  final CourseRecord course;
  final MeetingRepository repository;
  final SessionRepository sessionRepository;
  final CourseRepository? courseRepository;
  final AppLogger logger;
  final List<CourseRecord> allCourses;
  final List<String> allCourseIds;
  final SessionGenerator? generator;
  final MeetingIdGenerator idGenerator;
  final CurrentTime now;

  @override
  State<CourseSchedulePage> createState() => _CourseSchedulePageState();
}

class _CourseSchedulePageState extends State<CourseSchedulePage> {
  late CourseRecord _course;
  List<MeetingRecord> _meetings = const [];
  bool _loading = true;
  bool _loadFailed = false;
  String? _deletingId;
  bool _syncing = false;

  SessionGenerator get _generator =>
      widget.generator ?? SessionGenerator(tz.getLocation('America/Sao_Paulo'));

  @override
  void initState() {
    super.initState();
    _course = widget.course;
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadFailed = false;
    });
    try {
      final meetings = await widget.repository.listMeetings(widget.course.id);
      if (!mounted) return;
      setState(() => _meetings = _sorted(meetings));
    } catch (_) {
      if (mounted) setState(() => _loadFailed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openEditor([MeetingRecord? meeting]) => showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (context) => _MeetingEditorDialog(
      meeting: meeting,
      onSave: (input) => _save(meeting, input),
    ),
  );

  Future<String?> _save(MeetingRecord? existing, _MeetingInput input) async {
    try {
      final endMinutes = input.startMinutes + input.lessonCount.value * 50;
      for (final courseId in widget.allCourseIds) {
        final meetings = courseId == widget.course.id
            ? _meetings
            : await widget.repository.listMeetings(courseId);
        final overlap = meetings.any(
          (meeting) =>
              !(courseId == widget.course.id && meeting.id == existing?.id) &&
              meeting.weekday == input.weekday &&
              input.startMinutes < meeting.endMinutes &&
              meeting.startMinutes < endMinutes,
        );
        if (overlap) {
          return 'Esse horário se sobrepõe a outra aula cadastrada.';
        }
      }
      final timestamp = widget.now().toUtc();
      final meeting = MeetingRecord(
        id: existing?.id ?? widget.idGenerator(),
        weekday: input.weekday,
        startMinutes: input.startMinutes,
        endMinutes: endMinutes,
        lessonCount: input.lessonCount,
        callCount: input.callCount,
        createdAt: existing?.createdAt ?? timestamp,
        updatedAt: timestamp,
      );
      final proposedMeetings = _sorted([
        for (final item in _meetings)
          if (item.id != meeting.id) item,
        meeting,
      ]);
      final plan = await _planFor(proposedMeetings);
      if (!await _allowDestructive(plan)) {
        return 'Alteração cancelada para preservar frequências registradas.';
      }
      await widget.repository.saveMeeting(widget.course.id, meeting);
      if (mounted) {
        setState(() {
          _meetings = proposedMeetings;
          _syncing = plan != null;
        });
      }
      if (plan != null) unawaited(_applyPlanInBackground(plan));
      return null;
    } catch (_) {
      return 'Não foi possível salvar o horário.';
    }
  }

  Future<void> _confirmDelete(MeetingRecord meeting) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Excluir horário?'),
        content: Text(
          '${_weekdayLabel(meeting.weekday)}, ${_time(meeting.startMinutes)}–'
          '${_time(meeting.endMinutes)}',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Excluir'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deletingId = meeting.id);
    try {
      final proposedMeetings = _meetings
          .where((item) => item.id != meeting.id)
          .toList(growable: false);
      final plan = await _planFor(proposedMeetings);
      if (!await _allowDestructive(plan)) return;
      await widget.repository.deleteMeeting(widget.course.id, meeting.id);
      await _applyPlan(plan);
      if (mounted) {
        setState(() => _meetings = proposedMeetings);
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Não foi possível excluir o horário.')),
        );
      }
    } finally {
      if (mounted) setState(() => _deletingId = null);
    }
  }

  Future<void> _choosePeriod() async {
    final now = widget.now();
    final currentRange = _course.startsOn == null
        ? null
        : DateTimeRange(start: _course.startsOn!, end: _course.endsOn!);
    final range = await showDialog<DateTimeRange>(
      context: context,
      barrierDismissible: false,
      builder: (_) => CourseDateRangePickerDialog(
        initialMonth: currentRange?.start ?? now,
        firstDate: DateTime(now.year - 5),
        lastDate: DateTime(now.year + 5, 12, 31),
        highlightedWeekdays: _meetings.map((item) => item.weekday).toSet(),
        initialRange: currentRange,
      ),
    );
    if (range == null || !mounted) return;
    if (widget.courseRepository == null) {
      _message('Não foi possível salvar o período.');
      return;
    }
    setState(() => _syncing = true);
    try {
      final plan = await _planFor(
        _meetings,
        startDate: range.start,
        endDate: range.end,
      );
      if (!await _allowDestructive(plan)) return;
      final updated = _copyCourseWithRange(_course, range, widget.now());
      await widget.courseRepository!.saveCourse(updated);
      await _applyPlan(plan);
      if (mounted) setState(() => _course = updated);
      _message('Período salvo e calendário atualizado.');
    } catch (_) {
      if (mounted) {
        _message('Não foi possível salvar o período e atualizar o calendário.');
      }
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  Future<SessionReconciliation?> _planFor(
    List<MeetingRecord> meetings, {
    DateTime? startDate,
    DateTime? endDate,
  }) async {
    final start = startDate ?? _course.startsOn;
    final end = endDate ?? _course.endsOn;
    if (start == null || end == null) return null;
    final existing = await widget.sessionRepository.listSessions(
      widget.course.id,
    );
    return _generator.reconcile(
      meetings: meetings,
      existingSessions: existing,
      startDate: start,
      endDate: end,
      now: widget.now(),
    );
  }

  Future<bool> _allowDestructive(SessionReconciliation? plan) async {
    final count = plan?.destructiveDeleteCount ?? 0;
    if (count == 0 || !mounted) return true;
    return await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (context) => AlertDialog(
            title: const Text('Há frequências registradas'),
            content: Text(
              '$count ${count == 1 ? 'aula registrada será removida' : 'aulas registradas serão removidas'} com esta alteração.',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(context).pop(false),
                child: const Text('Manter como está'),
              ),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(true),
                child: const Text('Alterar mesmo assim'),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _applyPlan(SessionReconciliation? plan) async {
    if (plan == null) return;
    await runAuditedOperation<void>(
      logger: widget.logger,
      operation: AuditedOperation.sessionGeneration,
      action: () async {
        for (final session in plan.upserts) {
          await widget.sessionRepository.saveSession(widget.course.id, session);
        }
        for (final id in plan.deleteIds) {
          await widget.sessionRepository.deleteSession(widget.course.id, id);
        }
      },
    );
  }

  Future<void> _applyPlanInBackground(SessionReconciliation plan) async {
    try {
      await _applyPlan(plan);
    } catch (_) {
      if (mounted) {
        _message(
          'Horário salvo, mas não foi possível sincronizar o calendário.',
        );
      }
    } finally {
      if (mounted) setState(() => _syncing = false);
    }
  }

  void _message(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openCalendarExceptions() => Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => CalendarExceptionsPage(
        courseId: widget.course.id,
        repository: widget.sessionRepository,
        logger: widget.logger,
        location: _generator.location,
      ),
    ),
  );

  Future<void> _openAttendance() => Navigator.of(context).push<void>(
    MaterialPageRoute(
      builder: (_) => AttendancePage(
        courseId: widget.course.id,
        repository: widget.sessionRepository,
        logger: widget.logger,
        location: _generator.location,
        now: widget.now,
      ),
    ),
  );

  void _selectAction(_ScheduleAction action) {
    switch (action) {
      case _ScheduleAction.attendance:
        _openAttendance();
        return;
      case _ScheduleAction.calendar:
        Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => GeneralCalendarPage(
              courses: widget.allCourses,
              repository: widget.sessionRepository,
              location: _generator.location,
              initialCourseId: widget.course.id,
              now: widget.now,
            ),
          ),
        );
        return;
      case _ScheduleAction.exceptions:
        _openCalendarExceptions();
        return;
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text('Grade • ${_course.code}'),
      actions: [
        PopupMenuButton<_ScheduleAction>(
          tooltip: 'Ações da disciplina',
          enabled: !_syncing,
          onSelected: _selectAction,
          itemBuilder: (_) => const [
            PopupMenuItem(
              value: _ScheduleAction.attendance,
              child: Text('Registrar frequência'),
            ),
            PopupMenuItem(
              value: _ScheduleAction.calendar,
              child: Text('Ver calendário'),
            ),
            PopupMenuItem(
              value: _ScheduleAction.exceptions,
              child: Text('Exceções de calendário'),
            ),
          ],
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Center(child: Text(_syncing ? 'Sincronizando…' : 'Ações')),
          ),
        ),
      ],
    ),
    floatingActionButton: FloatingActionButton.extended(
      key: const Key('add-meeting'),
      onPressed: _syncing ? null : _openEditor,
      icon: const Icon(Icons.add),
      label: const Text('Adicionar horário'),
    ),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 24, 20, 96),
            child: _content(),
          ),
        ),
      ),
    ),
  );

  Widget _content() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_loadFailed) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Não foi possível carregar a grade.'),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _load,
              child: const Text('Tentar novamente'),
            ),
          ],
        ),
      );
    }
    return ListView(
      children: [
        _PeriodCard(
          course: _course,
          syncing: _syncing,
          onPressed: _choosePeriod,
        ),
        const SizedBox(height: 16),
        if (_meetings.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 48),
            child: Column(
              children: [
                Icon(Icons.calendar_view_week_outlined, size: 48),
                SizedBox(height: 16),
                Text('Nenhum horário cadastrado'),
                SizedBox(height: 6),
                Text('Adicione os encontros semanais desta disciplina.'),
              ],
            ),
          )
        else
          for (final meeting in _meetings) ...[
            Builder(
              builder: (context) {
                final weekday = _weekdayLabel(meeting.weekday);
                return Card(
                  elevation: 0,
                  child: ListTile(
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 8,
                    ),
                    title: Text(
                      '$weekday • ${_time(meeting.startMinutes)}–'
                      '${_time(meeting.endMinutes)}',
                    ),
                    subtitle: Text(
                      '${meeting.lessonCount.value} '
                      '${meeting.lessonCount.value == 1 ? 'aula' : 'aulas'} • '
                      '${meeting.callCount.value} '
                      '${meeting.callCount.value == 1 ? 'chamada' : 'chamadas'}',
                    ),
                    trailing: _deletingId == meeting.id
                        ? const SizedBox.square(
                            dimension: 24,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                tooltip:
                                    'Editar horário de ${weekday.toLowerCase()}',
                                onPressed: _syncing
                                    ? null
                                    : () => _openEditor(meeting),
                                icon: const Icon(Icons.edit_outlined),
                              ),
                              IconButton(
                                tooltip:
                                    'Excluir horário de ${weekday.toLowerCase()}',
                                onPressed: _syncing
                                    ? null
                                    : () => _confirmDelete(meeting),
                                icon: const Icon(Icons.delete_outline),
                              ),
                            ],
                          ),
                  ),
                );
              },
            ),
            const SizedBox(height: 8),
          ],
      ],
    );
  }
}

class _PeriodCard extends StatelessWidget {
  const _PeriodCard({
    required this.course,
    required this.syncing,
    required this.onPressed,
  });

  final CourseRecord course;
  final bool syncing;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final hasRange = course.startsOn != null;
    return Card(
      elevation: 0,
      child: ListTile(
        leading: const Icon(Icons.date_range_outlined),
        title: const Text('Período das aulas'),
        subtitle: Text(
          hasRange
              ? '${_shortDate(course.startsOn!)} – ${_shortDate(course.endsOn!)}'
              : 'Defina o início e o fim para montar o calendário.',
        ),
        trailing: TextButton(
          key: const Key('edit-course-period'),
          onPressed: syncing ? null : onPressed,
          child: Text(hasRange ? 'Alterar' : 'Definir'),
        ),
      ),
    );
  }
}

final class _MeetingInput {
  const _MeetingInput({
    required this.weekday,
    required this.startMinutes,
    required this.lessonCount,
    required this.callCount,
  });

  final int weekday;
  final int startMinutes;
  final QuantidadeAulas lessonCount;
  final NumeroChamadas callCount;
}

class _MeetingEditorDialog extends StatefulWidget {
  const _MeetingEditorDialog({required this.onSave, this.meeting});

  final MeetingRecord? meeting;
  final Future<String?> Function(_MeetingInput input) onSave;

  @override
  State<_MeetingEditorDialog> createState() => _MeetingEditorDialogState();
}

class _MeetingEditorDialogState extends State<_MeetingEditorDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _start;
  late int _weekday;
  late QuantidadeAulas _lessons;
  late NumeroChamadas _calls;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final meeting = widget.meeting;
    _weekday = meeting?.weekday ?? DateTime.monday;
    _lessons = meeting?.lessonCount ?? QuantidadeAulas.two;
    _calls = meeting?.callCount ?? NumeroChamadas.one;
    _start = TextEditingController(
      text: meeting == null ? '' : _time(meeting.startMinutes),
    );
  }

  @override
  void dispose() {
    _start.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final startMinutes = _parseTime(_start.text)!;
    if (startMinutes + _lessons.value * 50 > 1440) {
      setState(() => _error = 'O horário termina depois da meia-noite.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final error = await widget.onSave(
      _MeetingInput(
        weekday: _weekday,
        startMinutes: startMinutes,
        lessonCount: _lessons,
        callCount: _calls,
      ),
    );
    if (!mounted) return;
    if (error == null) {
      Navigator.of(context).pop();
    } else {
      setState(() {
        _saving = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.meeting == null ? 'Novo horário' : 'Editar horário'),
    content: SizedBox(
      width: 480,
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<int>(
                key: const Key('meeting-weekday'),
                initialValue: _weekday,
                decoration: const InputDecoration(labelText: 'Dia da semana'),
                items: [
                  for (var day = DateTime.monday; day <= DateTime.sunday; day++)
                    DropdownMenuItem(
                      value: day,
                      child: Text(_weekdayLabel(day)),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (value) => setState(() => _weekday = value!),
              ),
              const SizedBox(height: 16),
              TextFormField(
                key: const Key('meeting-start'),
                controller: _start,
                enabled: !_saving,
                keyboardType: TextInputType.datetime,
                decoration: const InputDecoration(
                  labelText: 'Horário de início',
                  hintText: '08:00',
                ),
                validator: (value) => _parseTime(value ?? '') == null
                    ? 'Use um horário válido no formato HH:MM.'
                    : null,
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<QuantidadeAulas>(
                key: const Key('meeting-lessons'),
                initialValue: _lessons,
                decoration: const InputDecoration(labelText: 'Duração'),
                items: [
                  for (final option in QuantidadeAulas.values)
                    DropdownMenuItem(
                      value: option,
                      child: Text(
                        '${option.value} '
                        '${option.value == 1 ? 'aula' : 'aulas'}',
                      ),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (value) => setState(() {
                        _lessons = value!;
                        if (_lessons == QuantidadeAulas.one) {
                          _calls = NumeroChamadas.one;
                        }
                      }),
              ),
              const SizedBox(height: 16),
              KeyedSubtree(
                key: const Key('meeting-calls'),
                child: DropdownButtonFormField<NumeroChamadas>(
                  key: ValueKey('meeting-calls-${_calls.value}'),
                  initialValue: _calls,
                  decoration: const InputDecoration(labelText: 'Chamadas'),
                  items: [
                    for (final option in NumeroChamadas.values)
                      DropdownMenuItem(
                        value: option,
                        enabled:
                            !(_lessons == QuantidadeAulas.one &&
                                option == NumeroChamadas.two),
                        child: Text(
                          '${option.value} '
                          '${option.value == 1 ? 'chamada' : 'chamadas'}',
                        ),
                      ),
                  ],
                  onChanged: _saving
                      ? null
                      : (value) => setState(() => _calls = value!),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
            ],
          ),
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: _saving ? null : () => Navigator.of(context).pop(),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: _saving ? null : _submit,
        child: _saving
            ? const SizedBox.square(
                dimension: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : const Text('Salvar'),
      ),
    ],
  );
}

List<MeetingRecord> _sorted(Iterable<MeetingRecord> meetings) =>
    meetings.toList(growable: false)..sort((left, right) {
      final day = left.weekday.compareTo(right.weekday);
      return day != 0 ? day : left.startMinutes.compareTo(right.startMinutes);
    });

int? _parseTime(String value) {
  final match = RegExp(r'^(\d{2}):(\d{2})$').firstMatch(value.trim());
  if (match == null) return null;
  final hour = int.parse(match.group(1)!);
  final minute = int.parse(match.group(2)!);
  if (hour > 23 || minute > 59) return null;
  return hour * 60 + minute;
}

String _time(int minutes) =>
    '${(minutes ~/ 60).toString().padLeft(2, '0')}:'
    '${(minutes % 60).toString().padLeft(2, '0')}';

String _weekdayLabel(int weekday) => const {
  DateTime.monday: 'Segunda-feira',
  DateTime.tuesday: 'Terça-feira',
  DateTime.wednesday: 'Quarta-feira',
  DateTime.thursday: 'Quinta-feira',
  DateTime.friday: 'Sexta-feira',
  DateTime.saturday: 'Sábado',
  DateTime.sunday: 'Domingo',
}[weekday]!;

String _shortDate(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}/'
    '${date.month.toString().padLeft(2, '0')}/${date.year}';

CourseRecord _copyCourseWithRange(
  CourseRecord course,
  DateTimeRange range,
  DateTime now,
) => CourseRecord(
  id: course.id,
  code: course.code,
  name: course.name,
  workload: course.workload,
  term: course.term,
  startsOn: DateTime.utc(range.start.year, range.start.month, range.start.day),
  endsOn: DateTime.utc(range.end.year, range.end.month, range.end.day),
  createdAt: course.createdAt,
  updatedAt: now.toUtc(),
);

String _newMeetingId() {
  final random = Random.secure();
  return '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${random.nextInt(1 << 30).toRadixString(36)}';
}
