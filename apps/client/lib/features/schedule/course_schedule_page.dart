import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../domain/attendance.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../attendance/attendance_page.dart';
import 'calendar_exceptions_page.dart';
import 'session_generator.dart';

typedef MeetingIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

class CourseSchedulePage extends StatefulWidget {
  // Runtime defaults keep production callers free from utility objects.
  // ignore: prefer_const_constructors_in_immutables
  CourseSchedulePage({
    required this.course,
    required this.repository,
    required this.sessionRepository,
    required this.logger,
    this.generator,
    MeetingIdGenerator? idGenerator,
    CurrentTime? now,
    super.key,
  }) : idGenerator = idGenerator ?? _newMeetingId,
       now = now ?? DateTime.now;

  final CourseRecord course;
  final MeetingRepository repository;
  final SessionRepository sessionRepository;
  final AppLogger logger;
  final SessionGenerator? generator;
  final MeetingIdGenerator idGenerator;
  final CurrentTime now;

  @override
  State<CourseSchedulePage> createState() => _CourseSchedulePageState();
}

class _CourseSchedulePageState extends State<CourseSchedulePage> {
  List<MeetingRecord> _meetings = const [];
  bool _loading = true;
  bool _loadFailed = false;
  String? _deletingId;
  bool _generating = false;

  SessionGenerator get _generator =>
      widget.generator ?? SessionGenerator(tz.getLocation('America/Sao_Paulo'));

  @override
  void initState() {
    super.initState();
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
    final duplicate = _meetings.any(
      (meeting) =>
          meeting.id != existing?.id &&
          meeting.weekday == input.weekday &&
          meeting.startMinutes == input.startMinutes,
    );
    if (duplicate) {
      return 'Já existe um horário nessa disciplina nesse dia e hora.';
    }
    try {
      final timestamp = widget.now().toUtc();
      final meeting = MeetingRecord(
        id: existing?.id ?? widget.idGenerator(),
        weekday: input.weekday,
        startMinutes: input.startMinutes,
        endMinutes: input.startMinutes + input.lessonCount.value * 50,
        lessonCount: input.lessonCount,
        callCount: input.callCount,
        createdAt: existing?.createdAt ?? timestamp,
        updatedAt: timestamp,
      );
      await widget.repository.saveMeeting(widget.course.id, meeting);
      if (mounted) {
        setState(() {
          _meetings = _sorted([
            for (final item in _meetings)
              if (item.id != meeting.id) item,
            meeting,
          ]);
        });
      }
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
      await widget.repository.deleteMeeting(widget.course.id, meeting.id);
      if (mounted) {
        setState(
          () => _meetings = _meetings
              .where((item) => item.id != meeting.id)
              .toList(growable: false),
        );
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

  Future<void> _generateSessions() async {
    if (_meetings.isEmpty) {
      _message('Cadastre pelo menos um horário antes de gerar sessões.');
      return;
    }
    final range = await showDialog<_GenerationRange>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _GenerationRangeDialog(),
    );
    if (range == null || !mounted) return;

    setState(() => _generating = true);
    try {
      final count = await runAuditedOperation<int>(
        logger: widget.logger,
        operation: AuditedOperation.sessionGeneration,
        action: () async {
          final existing = await widget.sessionRepository.listSessions(
            widget.course.id,
          );
          final currentTime = widget.now();
          final generated = _generator.generateMissing(
            meetings: _meetings,
            existingSessions: existing,
            startDate: range.start,
            endDate: range.end,
            notBefore: tz.TZDateTime.from(currentTime, _generator.location),
            now: currentTime,
          );
          for (final session in generated) {
            await widget.sessionRepository.saveSession(
              widget.course.id,
              session,
            );
          }
          return generated.length;
        },
      );
      if (!mounted) return;
      _message(switch (count) {
        0 => 'Nenhuma sessão nova para criar.',
        1 => '1 sessão criada.',
        _ => '$count sessões criadas.',
      });
    } catch (_) {
      if (mounted) _message('Não foi possível gerar as sessões.');
    } finally {
      if (mounted) setState(() => _generating = false);
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

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text('Grade • ${widget.course.code}'),
      actions: [
        IconButton(
          tooltip: 'Registrar frequência',
          onPressed: _openAttendance,
          icon: const Icon(Icons.check_circle_outline),
        ),
        IconButton(
          tooltip: 'Exceções de calendário',
          onPressed: _openCalendarExceptions,
          icon: const Icon(Icons.event_busy_outlined),
        ),
        IconButton(
          tooltip: 'Gerar sessões',
          onPressed: _generating ? null : _generateSessions,
          icon: _generating
              ? const SizedBox.square(
                  dimension: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.add_circle_outline),
        ),
      ],
    ),
    floatingActionButton: FloatingActionButton.extended(
      key: const Key('add-meeting'),
      onPressed: _openEditor,
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
    if (_meetings.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.calendar_view_week_outlined, size: 48),
            SizedBox(height: 16),
            Text('Nenhum horário cadastrado'),
            SizedBox(height: 6),
            Text('Adicione os encontros semanais desta disciplina.'),
          ],
        ),
      );
    }
    return ListView.separated(
      itemCount: _meetings.length,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        final meeting = _meetings[index];
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
                        tooltip: 'Editar horário de ${weekday.toLowerCase()}',
                        onPressed: () => _openEditor(meeting),
                        icon: const Icon(Icons.edit_outlined),
                      ),
                      IconButton(
                        tooltip: 'Excluir horário de ${weekday.toLowerCase()}',
                        onPressed: () => _confirmDelete(meeting),
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
          ),
        );
      },
    );
  }
}

final class _GenerationRange {
  const _GenerationRange(this.start, this.end);

  final DateTime start;
  final DateTime end;
}

class _GenerationRangeDialog extends StatefulWidget {
  const _GenerationRangeDialog();

  @override
  State<_GenerationRangeDialog> createState() => _GenerationRangeDialogState();
}

class _GenerationRangeDialogState extends State<_GenerationRangeDialog> {
  final _formKey = GlobalKey<FormState>();
  final _start = TextEditingController();
  final _end = TextEditingController();
  String? _rangeError;

  @override
  void dispose() {
    _start.dispose();
    _end.dispose();
    super.dispose();
  }

  void _submit() {
    if (!_formKey.currentState!.validate()) return;
    final start = _parseDate(_start.text)!;
    final end = _parseDate(_end.text)!;
    if (end.isBefore(start)) {
      setState(() => _rangeError = 'A data final deve ser igual ou posterior.');
      return;
    }
    Navigator.of(context).pop(_GenerationRange(start, end));
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Gerar sessões'),
    content: SizedBox(
      width: 420,
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextFormField(
              key: const Key('generation-start-date'),
              controller: _start,
              decoration: const InputDecoration(
                labelText: 'Data inicial',
                hintText: 'AAAA-MM-DD',
              ),
              validator: _dateValidator,
            ),
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('generation-end-date'),
              controller: _end,
              decoration: const InputDecoration(
                labelText: 'Data final',
                hintText: 'AAAA-MM-DD',
              ),
              validator: _dateValidator,
            ),
            if (_rangeError != null) ...[
              const SizedBox(height: 16),
              Text(
                _rangeError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text('Cancelar'),
      ),
      FilledButton(onPressed: _submit, child: const Text('Gerar')),
    ],
  );
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

String? _dateValidator(String? value) => _parseDate(value ?? '') == null
    ? 'Use uma data válida no formato AAAA-MM-DD.'
    : null;

DateTime? _parseDate(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})$').firstMatch(value.trim());
  if (match == null) return null;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  final parsed = DateTime(year, month, day);
  return parsed.year == year && parsed.month == month && parsed.day == day
      ? parsed
      : null;
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

String _newMeetingId() {
  final random = Random.secure();
  return '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${random.nextInt(1 << 30).toRadixString(36)}';
}
