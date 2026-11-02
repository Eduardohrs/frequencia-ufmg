import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../data/checkpoint_attendance_estimate.dart';
import '../../domain/attendance.dart';
import '../../data/campus_location.dart';
import '../../data/first_checkpoint.dart';
import '../../domain/campus_areas.dart';
import '../../observability/app_logger.dart';

class FirstCheckpointPage extends StatefulWidget {
  const FirstCheckpointPage({
    required this.courses,
    required this.sessions,
    required this.gateway,
    required this.selection,
    required this.logger,
    this.now = DateTime.now,
    this.deliveryUpdates,
    super.key,
  });
  final List<CourseRecord> courses;
  final SessionRepository sessions;
  final FirstCheckpointGateway gateway;
  final CampusSelectionGateway selection;
  final AppLogger logger;
  final DateTime Function() now;
  final Stream<Map<String, Object?>>? deliveryUpdates;
  @override
  State<FirstCheckpointPage> createState() => _FirstCheckpointPageState();
}

class _FirstCheckpointPageState extends State<FirstCheckpointPage>
    with WidgetsBindingObserver {
  List<(CourseRecord, SessionRecord)> _options = [];
  final Map<String, (CourseRecord, SessionRecord)> _catalog = {};
  List<(CourseRecord, CheckpointAttendanceEstimate)> _estimates = [];
  String _moment = 'first';
  List<Map<String, Object?>> _reports = [];
  int? _selected;
  StreamSubscription<Map<String, Object?>>? _deliverySubscription;
  bool _reloadQueued = false;
  int _deliveryRevision = 0;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _deliverySubscription = widget.deliveryUpdates?.listen(
      (event) {
        final revision = event['revision'];
        if (event['account_id'] != widget.gateway.accountId ||
            revision is! int ||
            revision <= _deliveryRevision) {
          return;
        }
        _deliveryRevision = revision;
        _reloadQueued = true;
        _reloadIfQueued();
      },
      onError: (Object error, StackTrace stack) {
        unawaited(
          widget.logger
              .recordError(error, stack, context: 'checkpoint_delivery_updates')
              .catchError((Object e) {
                debugPrint(
                  'checkpoint_delivery_event_log_failed type=${e.runtimeType}',
                );
              }),
        );
      },
    );
    unawaited(_load());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_deliverySubscription?.cancel());
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_load());
  }

  void _reloadIfQueued() {
    if (!mounted ||
        _busy ||
        !_reloadQueued ||
        (WidgetsBinding.instance.lifecycleState ?? AppLifecycleState.resumed) !=
            AppLifecycleState.resumed) {
      return;
    }
    _reloadQueued = false;
    unawaited(_load());
  }

  Future<void> _load() async {
    if (_busy) return;
    _reloadQueued = false;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      // Native evidence must remain readable while the academic catalog is offline.
      final reports = await widget.gateway.perform('read');
      if (mounted) setState(() => _acceptReports(reports));
      final catalog = <String, (CourseRecord, SessionRecord)>{};
      for (final course in widget.courses.where((c) => c.tracksAttendance)) {
        for (final session in await widget.sessions.listSessions(course.id)) {
          catalog['${course.id}/${session.id}'] = (course, session);
        }
      }
      if (mounted) {
        setState(() {
          _catalog
            ..clear()
            ..addAll(catalog);
          final options = _eligibleOptions();
          _options = options;
          _acceptReports(reports);
          _selected = options.isEmpty ? null : 0;
        });
      }
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'first_checkpoint_catalog')
            .catchError((Object e) {
              debugPrint(
                'first_checkpoint_log_delivery_failed type=${e.runtimeType}',
              );
            }),
      );
      if (mounted) {
        setState(
          () =>
              _error = 'Não foi possível consultar os pings. Tente atualizar.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
      _reloadIfQueued();
    }
  }

  Future<void> _act(
    String action, [
    Map<String, Object?> fields = const {},
  ]) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final payload = Map<String, Object?>.of(fields);
      if (action == 'schedule') {
        final (course, session) = _options[_selected!];
        final campus =
            CampusAreas.find(await widget.selection.read() ?? '') ??
            CampusAreas.defaultArea;
        payload.addAll({
          'moment': _moment,
          'delivery_enabled': true,
          'lesson_count': session.lessonCount.value,
          'call_count': session.callCount.value,
          'course_id': course.id,
          'course_code': course.code,
          'session_id': session.id,
          'starts_at_ms': session.startsAt.millisecondsSinceEpoch,
          'ends_at_ms': session.endsAt.millisecondsSinceEpoch,
          'campus_id': campus.id,
          'campus_name': campus.name,
          'rectangles': FirstCheckpointGateway.rectangles(campus),
        });
      }
      final reports = await widget.gateway.perform(action, payload);
      if (mounted) setState(() => _acceptReports(reports));
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(
              error,
              stack,
              context: 'first_checkpoint_prepare_$action',
              parameters: {'action': action},
            )
            .catchError((Object e) {
              debugPrint(
                'first_checkpoint_log_delivery_failed type=${e.runtimeType}',
              );
            }),
      );
      if (mounted) {
        setState(
          () => _error =
              error is PlatformException &&
                  error.details is Map &&
                  (error.details as Map)['cause_message'] ==
                      'exact_alarm_permission_required'
              ? 'Permita Alarmes e lembretes para agendar os pings.'
              : 'Não foi possível concluir. Confira permissões e tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
      _reloadIfQueued();
    }
  }

  List<(CourseRecord, SessionRecord)> _eligibleOptions() {
    final options = _catalog.values.where((entry) {
      final session = entry.$2;
      final expected = _moment == 'first'
          ? session.startsAt.add(const Duration(minutes: 20))
          : session.endsAt.subtract(const Duration(minutes: 20));
      return session.calendarStatus.requiresAttendance &&
          session.attendanceStatus == null &&
          session.firstPing == null &&
          session.secondPing == null &&
          (_moment != 'second' ||
              session.endsAt.difference(session.startsAt) >
                  const Duration(minutes: 40)) &&
          expected.isAfter(widget.now()) &&
          expected.isBefore(session.endsAt) &&
          expected.difference(widget.now()) <= const Duration(days: 180);
    }).toList();
    options.sort((a, b) => a.$2.startsAt.compareTo(b.$2.startsAt));
    return options;
  }

  void _selectMoment(String moment) {
    setState(() {
      _moment = moment;
      _options = _eligibleOptions();
      _selected = _options.isEmpty ? null : 0;
    });
    unawaited(
      widget.logger
          .logEvent(
            'attendance_checkpoint_moment_selected',
            parameters: {
              'action': 'select_moment',
              'details': jsonEncode({
                'moment': moment,
                'eligible_count': _options.length,
              }),
            },
          )
          .catchError((Object error) {
            debugPrint(
              'attendance_moment_log_delivery_failed type=${error.runtimeType}',
            );
          }),
    );
  }

  void _acceptReports(List<Map<String, Object?>> reports) {
    _reports = reports;
    final seen = <String>{};
    _estimates = [];
    for (final r in reports) {
      final courseId = r['course_id'];
      final sessionId = r['session_id'];
      final campus = r['campus_id'];
      final entry = _catalog['$courseId/$sessionId'];
      if (entry == null || campus is! String) continue;
      final (course, session) = entry;
      if (!CheckpointAttendanceEstimate.matches(
            r,
            course.id,
            session,
            campus,
          ) ||
          !seen.add('$courseId/$sessionId/$campus')) {
        continue;
      }
      final estimate = CheckpointAttendanceEstimate.fromReports(
        courseId: course.id,
        session: session,
        campusId: campus,
        reports: reports,
        now: widget.now(),
      );
      _estimates.add((course, estimate));
      unawaited(
        widget.logger
            .logEvent(
              'attendance_checkpoint_classified',
              parameters: {
                'course_id': course.id,
                'course_code': course.code,
                'session_id': session.id,
                'details': jsonEncode({
                  'stage': 'classification',
                  'course_id': course.id,
                  'course_code': course.code,
                  'session_id': session.id,
                  'call_count': session.callCount.value,
                  'lesson_count': session.lessonCount.value,
                  ...estimate.toLogFields(),
                }),
              },
            )
            .catchError((Object error) {
              debugPrint(
                'attendance_classification_log_delivery_failed type=${error.runtimeType}',
              );
            }),
      );
    }
  }

  String _attendanceLabel(SituacaoFrequencia status) => switch (status) {
    SituacaoFrequencia.present => 'Presente',
    SituacaoFrequencia.absent => 'Ausente',
    SituacaoFrequencia.arrivedLate => 'Chegou atrasado',
    SituacaoFrequencia.leftEarly => 'Saiu mais cedo',
    SituacaoFrequencia.pending => 'Pendente',
  };

  String _date(Object? ms) {
    if (ms is! int) return 'Horário indisponível';
    final d = DateTime.fromMillisecondsSinceEpoch(ms).toLocal();
    return '${d.day.toString().padLeft(2, "0")}/${d.month.toString().padLeft(2, "0")} ${d.hour.toString().padLeft(2, "0")}:${d.minute.toString().padLeft(2, "0")}';
  }

  static const _delivered = {
    'applied',
    'already_applied',
    'preserved',
    'unresolved',
    'discarded',
    'rejected',
  };
  String _deliveryLabel(Object? status) => switch (status) {
    'sending' => 'Enviando frequência',
    'retry' => 'Salvo neste aparelho; nova tentativa pendente',
    'applied' || 'already_applied' => 'Frequência sincronizada',
    'preserved' => 'Registro existente mantido',
    'unresolved' =>
      'Informação insuficiente; registre a frequência manualmente',
    'discarded' => 'Disciplina ou sessão removida; nenhum registro criado',
    'rejected' => 'Envio não validado; confira os detalhes de diagnóstico',
    _ => 'Salvo neste aparelho; aguardando envio',
  };

  String _result(Map<String, Object?> report) {
    final second = report['moment'] == 'second';
    final ping = report[second ? 'second_ping' : 'first_ping'];
    final label = second ? 'Segundo ping' : 'Primeiro ping';
    return switch (report['status']) {
      'scheduled' => 'Agendado para o horário da aula',
      'exact_alarm_permission_required' => 'Alarmes e lembretes não autorizado',
      'running' => 'Capturando localização',
      'cancelled' => 'Cancelado',
      'succeeded' when ping == 'no_campus' => '$label: no campus',
      'succeeded' when ping == 'fora' => '$label: fora do campus',
      'superseded' => 'Horário substituído',
      'checkpoint_outside_window' => 'Horário perdido — sem evidência válida',
      _ => 'Localização indisponível (${report['status']})',
    };
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Pings de presença'),
      actions: [
        IconButton(
          tooltip: 'Atualizar pings',
          onPressed: _busy ? null : _load,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text(
          'Agende os dois momentos: 20 minutos após o início e 20 minutos antes do fim da aula. O Android pode atrasar: até 5 minutos após esse horário, antes do fim da aula; fora dessa janela, o resultado fica indisponível.',
        ),
        const SizedBox(height: 12),
        const Text(
          'Requer Alarmes e lembretes, localização precisa permitida sempre e bateria sem restrições. Até 50 agendamentos/resultados ficam neste aparelho; limpe os encerrados quando necessário. Resultados ficam salvos neste aparelho e são enviados automaticamente quando houver conexão. Registros manuais são preservados.',
        ),
        TextButton(
          onPressed: _busy ? null : () => _act('request_alarm_permission'),
          child: const Text('Revisar Alarmes e lembretes'),
        ),
        if (_busy) const LinearProgressIndicator(),
        if (_error case final error?)
          Text(
            error,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'first', label: Text('Início da aula')),
            ButtonSegment(value: 'second', label: Text('Fim da aula')),
          ],
          selected: {_moment},
          onSelectionChanged: _busy
              ? null
              : (values) {
                  _selectMoment(values.single);
                },
        ),
        if (_options.isEmpty && !_busy)
          const Text('Nenhuma sessão elegível para agendar.'),
        if (_options.isNotEmpty)
          DropdownButtonFormField<int>(
            key: ValueKey('$_moment/${_options.map((e) => e.$2.id).join(',')}'),
            initialValue: _selected,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Sessão'),
            items: [
              for (var i = 0; i < _options.length; i++)
                DropdownMenuItem(
                  value: i,
                  child: Text(
                    '${_options[i].$1.code} • ${_date((_moment == 'first' ? _options[i].$2.startsAt.add(const Duration(minutes: 20)) : _options[i].$2.endsAt.subtract(const Duration(minutes: 20))).millisecondsSinceEpoch)}',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: _busy
                ? null
                : (value) => setState(() => _selected = value),
          ),
        FilledButton(
          onPressed: _busy || _selected == null ? null : () => _act('schedule'),
          child: Text(
            _moment == 'first'
                ? 'Agendar primeiro ping'
                : 'Agendar segundo ping',
          ),
        ),
        if (_reports.isNotEmpty)
          TextButton(
            onPressed: _busy ? null : () => _act('clear_completed'),
            child: const Text('Limpar resultados encerrados'),
          ),
        if (_reports.any(
          (r) =>
              r['delivery_enabled'] == true &&
              !_delivered.contains(r['delivery_status']),
        ))
          TextButton(
            onPressed: _busy ? null : () => _act('retry_deliveries'),
            child: const Text('Enviar resultados pendentes'),
          ),
        for (final (course, estimate) in _estimates)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${course.code} · ${estimate.complete ? 'Resultado local' : 'Prévia local'}',
                  ),
                  Text(_attendanceLabel(estimate.status)),
                  Text(
                    estimate.absences == null
                        ? 'Faltas ainda não definidas'
                        : '${estimate.absences} falta(s)',
                  ),
                  if (!estimate.complete)
                    const Text('Aguardando os dois resultados'),
                  if (estimate.preservesExistingRecord)
                    const Text('Registro da disciplina preservado'),
                ],
              ),
            ),
          ),
        for (final report in _reports)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${report['course_code']} • ${_date(report['checkpoint_expected_at_ms'])}',
                  ),
                  Text(_result(report)),
                  if (report['delivery_enabled'] == true)
                    Text(_deliveryLabel(report['delivery_status'])),
                  Text('Campus: ${report['campus_name']}'),
                  if (report['lateness_ms'] case final int lateness)
                    Text('Atraso observado: ${(lateness / 1000).round()} s'),
                  if (report['accuracy_m'] case final num accuracy)
                    Text('Precisão: ${accuracy.toStringAsFixed(1)} m'),
                  if (report['status'] == 'scheduled' ||
                      report['status'] == 'running')
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => _act('cancel', {
                              'operation_id': report['operation_id'],
                            }),
                      child: Text(
                        report['moment'] == 'second'
                            ? 'Cancelar segundo ping'
                            : 'Cancelar primeiro ping',
                      ),
                    ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}
