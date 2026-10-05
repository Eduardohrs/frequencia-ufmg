import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../domain/attendance.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

typedef ExceptionIdGenerator = String Function();
typedef ExceptionCurrentTime = DateTime Function();

class CalendarExceptionsPage extends StatefulWidget {
  // Runtime defaults keep production callers free from utility objects.
  // ignore: prefer_const_constructors_in_immutables
  CalendarExceptionsPage({
    required this.courseId,
    required this.repository,
    required this.logger,
    required this.location,
    ExceptionIdGenerator? idGenerator,
    ExceptionCurrentTime? now,
    super.key,
  }) : idGenerator = idGenerator ?? _newExceptionId,
       now = now ?? DateTime.now;

  final String courseId;
  final SessionRepository repository;
  final AppLogger logger;
  final tz.Location location;
  final ExceptionIdGenerator idGenerator;
  final ExceptionCurrentTime now;

  @override
  State<CalendarExceptionsPage> createState() => _CalendarExceptionsPageState();
}

class _CalendarExceptionsPageState extends State<CalendarExceptionsPage> {
  List<SessionRecord> _sessions = const [];
  bool _loading = true;
  bool _loadFailed = false;
  String? _savingId;

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
      final sessions = await widget.repository.listSessions(widget.courseId);
      if (mounted) setState(() => _sessions = _sorted(sessions));
    } catch (_) {
      if (mounted) setState(() => _loadFailed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _changeStatus(
    SessionRecord session,
    SessionCalendarStatus status,
  ) async {
    setState(() => _savingId = session.id);
    try {
      final updated = _copySession(
        session,
        calendarStatus: status,
        assessmentTitle: session.assessmentTitle,
        updatedAt: widget.now().toUtc(),
      );
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.calendarException,
        action: () => widget.repository.saveSession(widget.courseId, updated),
      );
      if (mounted) {
        setState(() {
          _sessions = _sorted([
            for (final item in _sessions)
              if (item.id != updated.id) item,
            updated,
          ]);
        });
      }
    } catch (_) {
      if (mounted) _message('Não foi possível alterar a sessão.');
    } finally {
      if (mounted) setState(() => _savingId = null);
    }
  }

  Future<void> _openMakeupEditor() => showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _MakeupSessionDialog(onSave: _addMakeup),
  );

  Future<void> _editAssessment(SessionRecord session) async {
    final title = await showDialog<String?>(
      context: context,
      builder: (_) => _AssessmentDialog(initialTitle: session.assessmentTitle),
    );
    if (title == null || !mounted) return;
    setState(() => _savingId = session.id);
    try {
      final updated = _copySession(
        session,
        calendarStatus: session.calendarStatus,
        assessmentTitle: title.isEmpty ? null : title,
        updatedAt: widget.now().toUtc(),
      );
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.assessmentUpdate,
        action: () => widget.repository.saveSession(widget.courseId, updated),
      );
      if (mounted) {
        setState(() {
          _sessions = _sorted([
            for (final item in _sessions)
              if (item.id != updated.id) item,
            updated,
          ]);
        });
      }
    } catch (_) {
      if (mounted) _message('Não foi possível salvar a avaliação.');
    } finally {
      if (mounted) setState(() => _savingId = null);
    }
  }

  Future<String?> _addMakeup(_MakeupInput input) async {
    final timestamp = widget.now().toUtc();
    final startsAt = tz.TZDateTime(
      widget.location,
      input.date.year,
      input.date.month,
      input.date.day,
      input.startMinutes ~/ 60,
      input.startMinutes % 60,
    );
    if (startsAt.isBefore(tz.TZDateTime.from(widget.now(), widget.location))) {
      return 'A reposição precisa estar no futuro.';
    }
    final session = SessionRecord(
      id: widget.idGenerator(),
      startsAt: startsAt.toUtc(),
      endsAt: startsAt
          .add(Duration(minutes: input.lessonCount.value * 50))
          .toUtc(),
      lessonCount: input.lessonCount,
      callCount: input.callCount,
      calendarStatus: SessionCalendarStatus.makeup,
      createdAt: timestamp,
      updatedAt: timestamp,
    );
    try {
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.calendarException,
        action: () => widget.repository.saveSession(widget.courseId, session),
      );
      if (mounted) {
        setState(() => _sessions = _sorted([..._sessions, session]));
      }
      return null;
    } catch (_) {
      return 'Não foi possível adicionar a reposição.';
    }
  }

  void _message(String value) {
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(value)));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Exceções de calendário'),
      actions: [
        IconButton(
          tooltip: 'Entenda os tipos de aula',
          onPressed: _showHelp,
          icon: const Icon(Icons.help_outline),
        ),
      ],
    ),
    floatingActionButton: FloatingActionButton.extended(
      key: const Key('add-makeup-session'),
      onPressed: _openMakeupEditor,
      icon: const Icon(Icons.add),
      label: const Text('Adicionar reposição'),
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
            const Text('Não foi possível carregar as sessões.'),
            const SizedBox(height: 12),
            OutlinedButton(
              onPressed: _load,
              child: const Text('Tentar novamente'),
            ),
          ],
        ),
      );
    }
    if (_sessions.isEmpty) {
      return const Center(child: Text('Nenhuma sessão gerada'));
    }
    return ListView.separated(
      itemCount: _sessions.length,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (_, index) {
        final session = _sessions[index];
        final local = tz.TZDateTime.from(session.startsAt, widget.location);
        final date = _date(local);
        return Card(
          elevation: 0,
          child: ListTile(
            title: Text('$date • ${_time(local)}'),
            subtitle: Text(
              session.assessmentTitle == null
                  ? _statusLabel(session.calendarStatus)
                  : '${_statusLabel(session.calendarStatus)} • '
                        'Avaliação: ${session.assessmentTitle}',
            ),
            trailing: _savingId == session.id
                ? const SizedBox.square(
                    dimension: 24,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: 'Editar avaliação de $date',
                        onPressed: () => _editAssessment(session),
                        icon: Icon(
                          session.assessmentTitle == null
                              ? Icons.assignment_outlined
                              : Icons.assignment,
                        ),
                      ),
                      PopupMenuButton<SessionCalendarStatus>(
                        tooltip: 'Alterar sessão de $date',
                        onSelected: (status) => _changeStatus(session, status),
                        itemBuilder: (_) => switch (session.calendarStatus) {
                          SessionCalendarStatus.scheduled => const [
                            PopupMenuItem(
                              value: SessionCalendarStatus.cancelled,
                              child: Text('Cancelada/feriado'),
                            ),
                            PopupMenuItem(
                              value: SessionCalendarStatus.noCall,
                              child: Text('Aula sem chamada'),
                            ),
                          ],
                          SessionCalendarStatus.makeup => const [
                            PopupMenuItem(
                              value: SessionCalendarStatus.cancelled,
                              child: Text('Cancelada/feriado'),
                            ),
                            PopupMenuItem(
                              value: SessionCalendarStatus.noCall,
                              child: Text('Aula sem chamada'),
                            ),
                          ],
                          _ => const [
                            PopupMenuItem(
                              value: SessionCalendarStatus.scheduled,
                              child: Text('Restaurar aula'),
                            ),
                          ],
                        },
                      ),
                    ],
                  ),
          ),
        );
      },
    );
  }

  Future<void> _showHelp() => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Como as aulas entram no cálculo'),
      content: const Text(
        'Aulas programadas e reposições entram no total de aulas e no cálculo '
        'de faltas.\n\nCancelada/feriado indica que a aula não aconteceu. '
        'Aula sem chamada indica que a aula aconteceu e vale como presença '
        'garantida. Ela entra no total acadêmico, mas não aparece na agenda '
        'operacional. Cancelada/feriado não entra no cálculo.',
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Entendi'),
        ),
      ],
    ),
  );
}

class _AssessmentDialog extends StatefulWidget {
  const _AssessmentDialog({this.initialTitle});

  final String? initialTitle;

  @override
  State<_AssessmentDialog> createState() => _AssessmentDialogState();
}

class _AssessmentDialogState extends State<_AssessmentDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialTitle);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Atividade avaliativa'),
    content: TextField(
      key: const Key('assessment-title'),
      controller: _controller,
      autofocus: true,
      maxLength: 120,
      decoration: const InputDecoration(
        labelText: 'Título',
        hintText: 'Ex.: Prova 1, seminário ou entrega',
        helperText: 'Deixe vazio para remover a avaliação.',
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: () => Navigator.of(context).pop(_controller.text.trim()),
        child: const Text('Salvar'),
      ),
    ],
  );
}

final class _MakeupInput {
  const _MakeupInput({
    required this.date,
    required this.startMinutes,
    required this.lessonCount,
    required this.callCount,
  });

  final DateTime date;
  final int startMinutes;
  final QuantidadeAulas lessonCount;
  final NumeroChamadas callCount;
}

class _MakeupSessionDialog extends StatefulWidget {
  const _MakeupSessionDialog({required this.onSave});

  final Future<String?> Function(_MakeupInput input) onSave;

  @override
  State<_MakeupSessionDialog> createState() => _MakeupSessionDialogState();
}

class _MakeupSessionDialogState extends State<_MakeupSessionDialog> {
  final _formKey = GlobalKey<FormState>();
  final _dateController = TextEditingController();
  final _startController = TextEditingController();
  QuantidadeAulas _lessons = QuantidadeAulas.two;
  NumeroChamadas _calls = NumeroChamadas.one;
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _dateController.dispose();
    _startController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final error = await widget.onSave(
      _MakeupInput(
        date: _parseDate(_dateController.text)!,
        startMinutes: _parseTime(_startController.text)!,
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
    title: const Text('Nova reposição'),
    content: SizedBox(
      width: 460,
      child: Form(
        key: _formKey,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextFormField(
                key: const Key('makeup-date'),
                controller: _dateController,
                enabled: !_saving,
                decoration: const InputDecoration(
                  labelText: 'Data',
                  hintText: 'AAAA-MM-DD',
                ),
                validator: (value) => _parseDate(value ?? '') == null
                    ? 'Use uma data válida no formato AAAA-MM-DD.'
                    : null,
              ),
              const SizedBox(height: 16),
              TextFormField(
                key: const Key('makeup-start'),
                controller: _startController,
                enabled: !_saving,
                decoration: const InputDecoration(
                  labelText: 'Horário de início',
                  hintText: 'HH:MM',
                ),
                validator: (value) => _parseTime(value ?? '') == null
                    ? 'Use um horário válido no formato HH:MM.'
                    : null,
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<QuantidadeAulas>(
                key: const Key('makeup-lessons'),
                initialValue: _lessons,
                decoration: const InputDecoration(labelText: 'Duração'),
                items: [
                  for (final value in QuantidadeAulas.values)
                    DropdownMenuItem(
                      value: value,
                      child: Text('${value.value} aulas'),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (value) => setState(() {
                        _lessons = value!;
                        if (value == QuantidadeAulas.one) {
                          _calls = NumeroChamadas.one;
                        }
                      }),
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<NumeroChamadas>(
                key: ValueKey('makeup-calls-${_calls.value}'),
                initialValue: _calls,
                decoration: const InputDecoration(labelText: 'Chamadas'),
                items: [
                  for (final value in NumeroChamadas.values)
                    DropdownMenuItem(
                      value: value,
                      enabled:
                          !(_lessons == QuantidadeAulas.one &&
                              value == NumeroChamadas.two),
                      child: Text('${value.value} chamadas'),
                    ),
                ],
                onChanged: _saving
                    ? null
                    : (value) => setState(() => _calls = value!),
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
        child: const Text('Adicionar'),
      ),
    ],
  );
}

SessionRecord _copySession(
  SessionRecord source, {
  required SessionCalendarStatus calendarStatus,
  required String? assessmentTitle,
  required DateTime updatedAt,
}) => SessionRecord(
  id: source.id,
  startsAt: source.startsAt,
  endsAt: source.endsAt,
  lessonCount: source.lessonCount,
  callCount: source.callCount,
  firstPing: source.firstPing,
  secondPing: source.secondPing,
  attendanceStatus: source.attendanceStatus,
  absences: source.absences,
  calendarStatus: calendarStatus,
  assessmentTitle: assessmentTitle,
  createdAt: source.createdAt,
  updatedAt: updatedAt,
);

List<SessionRecord> _sorted(Iterable<SessionRecord> sessions) =>
    sessions.toList(growable: false)
      ..sort((left, right) => left.startsAt.compareTo(right.startsAt));

String _statusLabel(SessionCalendarStatus status) => switch (status) {
  SessionCalendarStatus.scheduled => 'Programada',
  SessionCalendarStatus.cancelled ||
  SessionCalendarStatus.holiday => 'Cancelada/feriado',
  SessionCalendarStatus.noCall => 'Aula sem chamada',
  SessionCalendarStatus.makeup => 'Reposição',
};

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

int? _parseTime(String value) {
  final match = RegExp(r'^(\d{2}):(\d{2})$').firstMatch(value.trim());
  if (match == null) return null;
  final hour = int.parse(match.group(1)!);
  final minute = int.parse(match.group(2)!);
  return hour <= 23 && minute <= 59 ? hour * 60 + minute : null;
}

String _date(DateTime date) =>
    '${date.day.toString().padLeft(2, '0')}/'
    '${date.month.toString().padLeft(2, '0')}/${date.year}';

String _time(DateTime date) =>
    '${date.hour.toString().padLeft(2, '0')}:'
    '${date.minute.toString().padLeft(2, '0')}';

String _newExceptionId() {
  final random = Random.secure();
  return 'makeup-${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${random.nextInt(1 << 30).toRadixString(36)}';
}
