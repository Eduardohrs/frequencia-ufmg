import 'dart:async';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../data/academic_records.dart';
import '../../backend/python_backend_transport.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../domain/attendance.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

class AttendancePage extends StatefulWidget {
  const AttendancePage({
    required this.courseId,
    required this.repository,
    required this.logger,
    required this.location,
    required this.now,
    this.attendanceEvaluator,
    this.sessionGateway,
    this.sessionWritesEnabled = false,
    this.androidOfflineQueueEnabled = false,
    this.courseCode,
    this.initialSessionId,
    this.initialSessions,
    super.key,
  }) : assert(!sessionWritesEnabled || sessionGateway != null),
       assert(
         !androidOfflineQueueEnabled ||
             repository is OfflineSessionMutationQueue,
       );

  final String courseId;
  final SessionRepository repository;
  final AppLogger logger;
  final tz.Location location;
  final DateTime Function() now;
  final BackendAttendanceEvaluator? attendanceEvaluator;
  final BackendSessionGateway? sessionGateway;
  final bool sessionWritesEnabled;
  final bool androidOfflineQueueEnabled;
  final String? courseCode;
  final String? initialSessionId;
  final List<SessionRecord>? initialSessions;

  @override
  State<AttendancePage> createState() => _AttendancePageState();
}

class _AttendancePageState extends State<AttendancePage> {
  List<SessionRecord> _sessions = const [];
  bool _loading = true;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failed = false;
    });
    try {
      final sessions = List<SessionRecord>.of(
        widget.initialSessions ??
            await widget.repository.listSessions(widget.courseId),
      );
      sessions.sort((a, b) => a.startsAt.compareTo(b.startsAt));
      if (mounted) setState(() => _sessions = sessions);
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _edit(SessionRecord session) => showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _AttendanceDialog(
      session: session,
      attendanceEvaluator: widget.sessionWritesEnabled
          ? null
          : widget.attendanceEvaluator,
      onSave: (status, absences) => _save(session, status, absences),
    ),
  );

  Future<String?> _save(
    SessionRecord source,
    SituacaoFrequencia status,
    int? absences,
  ) async {
    try {
      late SessionRecord updated;
      var queuedOffline = false;
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.manualAttendance,
        action: () async {
          var savedStatus = status;
          var savedAbsences = absences;
          var savedAt = widget.now().toUtc();
          if (widget.sessionWritesEnabled) {
            try {
              final result = await widget.sessionGateway!.saveAttendance(
                courseId: widget.courseId,
                sessionId: source.id,
                status: status.code,
                maximumAbsences: source.lessonCount.value,
                useDefaultAbsences: source.attendanceStatus == null,
                correctedAbsences: source.attendanceStatus == null
                    ? null
                    : absences,
              );
              savedStatus = SituacaoFrequencia.fromCode(result.status);
              savedAbsences = result.absences;
              savedAt = result.updatedAt;
            } catch (error) {
              if (!widget.androidOfflineQueueEnabled ||
                  !isTransientPythonBackendFailure(error)) {
                rethrow;
              }
              queuedOffline = true;
            }
          }
          updated = SessionRecord(
            id: source.id,
            startsAt: source.startsAt,
            endsAt: source.endsAt,
            lessonCount: source.lessonCount,
            callCount: source.callCount,
            firstPing: source.firstPing,
            secondPing: source.secondPing,
            attendanceStatus: savedStatus,
            absences: savedAbsences,
            calendarStatus: source.calendarStatus,
            assessmentTitle: source.assessmentTitle,
            createdAt: source.createdAt,
            updatedAt: savedAt,
          );
          if (!widget.sessionWritesEnabled || queuedOffline) {
            final delivery = queuedOffline
                ? (widget.repository as OfflineSessionMutationQueue)
                      .patchAttendance(
                        widget.courseId,
                        updated.id,
                        status: savedStatus,
                        absences: savedAbsences,
                        updatedAt: savedAt,
                      )
                : widget.repository.saveSession(widget.courseId, updated);
            if (queuedOffline) {
              unawaited(
                widget.logger.logEvent(
                  'android_offline_attendance_queued',
                  parameters: {
                    'operation': 'manual_attendance',
                    'operation_id': currentOperationId!,
                    'outcome': 'queued',
                  },
                ),
              );
              unawaited(
                delivery.catchError((Object error, StackTrace stackTrace) {
                  return widget.logger.recordError(
                    error,
                    stackTrace,
                    context: 'android_offline_attendance_delivery',
                  );
                }),
              );
            } else {
              await delivery;
            }
          }
        },
      );
      if (mounted) {
        setState(() {
          _sessions = [
            for (final item in _sessions)
              if (item.id != updated.id) item,
            updated,
          ]..sort((a, b) => a.startsAt.compareTo(b.startsAt));
        });
      }
      if (queuedOffline && mounted) {
        _message(
          'Salvo no aparelho. A sincronização continuará automaticamente.',
        );
      }
      return null;
    } catch (_) {
      return 'Não foi possível salvar a frequência.';
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
      title: Text(
        widget.courseCode == null
            ? 'Frequência por aula'
            : 'Frequência • ${widget.courseCode}',
      ),
    ),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760),
          child: Padding(padding: const EdgeInsets.all(20), child: _content()),
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
    final sections = _sections();
    return CustomScrollView(
      slivers: [
        for (var index = 0; index < sections.length; index++) ...[
          SliverToBoxAdapter(
            child: Padding(
              padding: EdgeInsets.only(top: index == 0 ? 0 : 20, bottom: 8),
              child: Text(
                sections[index].title,
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
          ),
          SliverList.separated(
            itemCount: sections[index].sessions.length,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (_, sessionIndex) =>
                _sessionCard(sections[index].sessions[sessionIndex]),
          ),
        ],
      ],
    );
  }

  List<_AttendanceSection> _sections() {
    final localNow = tz.TZDateTime.from(widget.now(), widget.location);
    final today = DateTime(localNow.year, localNow.month, localNow.day);
    final current = <SessionRecord>[];
    final pending = <SessionRecord>[];
    final upcoming = <SessionRecord>[];
    final history = <SessionRecord>[];
    for (final session in _sessions) {
      final local = tz.TZDateTime.from(session.startsAt, widget.location);
      final day = DateTime(local.year, local.month, local.day);
      if (day == today) {
        current.add(session);
      } else if (_requiresAttendance(session) &&
          session.absences == null &&
          day.isBefore(today)) {
        pending.add(session);
      } else if (day.isAfter(today)) {
        upcoming.add(session);
      } else {
        history.add(session);
      }
    }
    pending.sort((left, right) => right.startsAt.compareTo(left.startsAt));
    history.sort((left, right) => right.startsAt.compareTo(left.startsAt));
    final ordered = <_AttendanceSection>[
      if (widget.initialSessionId != null && pending.isNotEmpty)
        _AttendanceSection('Pendências anteriores', pending),
      if (current.isNotEmpty) _AttendanceSection('Hoje', current),
      if (widget.initialSessionId == null && pending.isNotEmpty)
        _AttendanceSection('Pendências anteriores', pending),
      if (upcoming.isNotEmpty) _AttendanceSection('Próximas aulas', upcoming),
      if (history.isNotEmpty) _AttendanceSection('Histórico', history),
    ];
    return ordered;
  }

  Widget _sessionCard(SessionRecord session) {
    final local = tz.TZDateTime.from(session.startsAt, widget.location);
    final inactive = !_requiresAttendance(session);
    final selected = session.id == widget.initialSessionId;
    final localNow = tz.TZDateTime.from(widget.now(), widget.location);
    final today = DateTime(localNow.year, localNow.month, localNow.day);
    final day = DateTime(local.year, local.month, local.day);
    final overdue =
        !inactive && session.absences == null && day.isBefore(today);
    final colorScheme = Theme.of(context).colorScheme;
    return Card(
      key: Key('attendance-session-${session.id}'),
      elevation: 0,
      color: selected
          ? colorScheme.tertiaryContainer
          : overdue
          ? colorScheme.errorContainer
          : null,
      child: ListTile(
        title: Wrap(
          spacing: 8,
          runSpacing: 4,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Text(_dateTime(local)),
            if (overdue) const _StatusBadge('Pendente de registro'),
            if (selected) const _StatusBadge('Selecionada pelo alerta'),
          ],
        ),
        subtitle: Text(
          inactive
              ? _calendarLabel(session.calendarStatus)
              : _attendanceLabel(session),
        ),
        trailing: IconButton(
          tooltip: inactive
              ? session.calendarStatus == SessionCalendarStatus.noCall
                    ? 'Presença garantida'
                    : 'Sessão sem frequência'
              : 'Registrar frequência de ${_date(local)}',
          onPressed: inactive ? null : () => _edit(session),
          icon: const Icon(Icons.edit_outlined),
        ),
      ),
    );
  }
}

final class _AttendanceSection {
  const _AttendanceSection(this.title, this.sessions);

  final String title;
  final List<SessionRecord> sessions;
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge(this.label);

  final String label;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: Theme.of(context).colorScheme.surface,
      borderRadius: BorderRadius.circular(8),
    ),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: Text(label, style: Theme.of(context).textTheme.labelMedium),
    ),
  );
}

bool _requiresAttendance(SessionRecord session) =>
    session.calendarStatus == SessionCalendarStatus.scheduled ||
    session.calendarStatus == SessionCalendarStatus.makeup;

class _AttendanceDialog extends StatefulWidget {
  const _AttendanceDialog({
    required this.session,
    required this.onSave,
    this.attendanceEvaluator,
  });

  final SessionRecord session;
  final Future<String?> Function(SituacaoFrequencia, int?) onSave;
  final BackendAttendanceEvaluator? attendanceEvaluator;

  @override
  State<_AttendanceDialog> createState() => _AttendanceDialogState();
}

class _AttendanceDialogState extends State<_AttendanceDialog> {
  final _formKey = GlobalKey<FormState>();
  late SituacaoFrequencia _status;
  late final TextEditingController _absences;
  bool _saving = false;
  String? _error;

  bool get _editing => widget.session.attendanceStatus != null;

  @override
  void initState() {
    super.initState();
    _status = widget.session.attendanceStatus ?? SituacaoFrequencia.present;
    _absences = TextEditingController();
    final savedAbsences = widget.session.absences;
    if (widget.session.attendanceStatus != null) {
      _absences.text = savedAbsences?.toString() ?? '';
    } else {
      _setSuggestedAbsences();
    }
  }

  void _setSuggestedAbsences() {
    if (!_editing) return;
    final session = SessaoAula(
      widget.session.id,
      ConfiguracaoSessao(
        aulas: widget.session.lessonCount,
        chamadas: widget.session.callCount,
      ),
    );
    _absences.text = session.calcularFaltas(_status)?.toString() ?? '';
  }

  @override
  void dispose() {
    _absences.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    String? error;
    try {
      final value = _editing
          ? _status == SituacaoFrequencia.pending
                ? null
                : int.parse(_absences.text)
          : await _defaultAbsences();
      error = await widget.onSave(_status, value);
    } catch (_) {
      error = 'Não foi possível calcular as faltas. Tente novamente.';
    }
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

  Future<int?> _defaultAbsences() async {
    final evaluator = widget.attendanceEvaluator;
    if (evaluator == null) {
      return SessaoAula(
        widget.session.id,
        ConfiguracaoSessao(
          aulas: widget.session.lessonCount,
          chamadas: widget.session.callCount,
        ),
      ).calcularFaltas(_status);
    }
    final decision = await evaluator.evaluateAttendanceStatus(
      lessons: widget.session.lessonCount.value,
      calls: widget.session.callCount.value,
      status: _status.code,
    );
    if (decision.status != _status.code) {
      throw const PythonBackendException(PythonBackendError.invalidResponse);
    }
    return decision.absences;
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Registrar frequência'),
    content: SizedBox(
      width: 440,
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            DropdownButtonFormField<SituacaoFrequencia>(
              key: const Key('attendance-status'),
              initialValue: _status,
              decoration: const InputDecoration(labelText: 'Situação'),
              items: [
                for (final status in SituacaoFrequencia.values)
                  DropdownMenuItem(
                    value: status,
                    child: Text(_statusName(status)),
                  ),
              ],
              onChanged: _saving
                  ? null
                  : (value) => setState(() {
                      _status = value!;
                      _setSuggestedAbsences();
                    }),
            ),
            const SizedBox(height: 16),
            if (_editing)
              TextFormField(
                key: const Key('attendance-absences'),
                controller: _absences,
                enabled: !_saving && _status != SituacaoFrequencia.pending,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Faltas nesta sessão',
                ),
                validator: (value) {
                  if (_status == SituacaoFrequencia.pending) return null;
                  final parsed = int.tryParse(value ?? '');
                  if (parsed == null ||
                      parsed < 0 ||
                      parsed > widget.session.lessonCount.value) {
                    return 'Use um valor entre 0 e ${widget.session.lessonCount.value}.';
                  }
                  return null;
                },
              )
            else
              const Text('As faltas serão calculadas automaticamente.'),
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
    actions: [
      TextButton(
        onPressed: _saving ? null : () => Navigator.of(context).pop(),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: _saving ? null : _submit,
        child: const Text('Salvar'),
      ),
    ],
  );
}

String _attendanceLabel(SessionRecord session) {
  final status = session.attendanceStatus;
  if (status == null) return 'Sem registro';
  final absences = session.absences;
  return '${_statusName(status)} • ${absences == null ? 'faltas pendentes' : '$absences faltas'}';
}

String _statusName(SituacaoFrequencia status) => switch (status) {
  SituacaoFrequencia.present => 'Presente',
  SituacaoFrequencia.arrivedLate => 'Chegou atrasado',
  SituacaoFrequencia.leftEarly => 'Saiu mais cedo',
  SituacaoFrequencia.absent => 'Ausente',
  SituacaoFrequencia.pending => 'Pendente',
};

String _calendarLabel(SessionCalendarStatus status) => switch (status) {
  SessionCalendarStatus.noCall => 'Aula sem chamada • presença garantida',
  SessionCalendarStatus.cancelled ||
  SessionCalendarStatus.holiday => 'Cancelada/feriado • sem frequência',
  _ => '',
};

String _date(DateTime value) =>
    '${value.day.toString().padLeft(2, '0')}/${value.month.toString().padLeft(2, '0')}/${value.year}';

String _dateTime(DateTime value) =>
    '${_date(value)} • ${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';
