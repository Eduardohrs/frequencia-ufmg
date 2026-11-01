import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
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
    super.key,
  });
  final List<CourseRecord> courses;
  final SessionRepository sessions;
  final FirstCheckpointGateway gateway;
  final CampusSelectionGateway selection;
  final AppLogger logger;
  final DateTime Function() now;
  @override
  State<FirstCheckpointPage> createState() => _FirstCheckpointPageState();
}

class _FirstCheckpointPageState extends State<FirstCheckpointPage>
    with WidgetsBindingObserver {
  List<(CourseRecord, SessionRecord)> _options = [];
  List<Map<String, Object?>> _reports = [];
  int? _selected;
  bool _busy = false;
  String? _error;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_load());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_load());
  }

  Future<void> _load() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final options = <(CourseRecord, SessionRecord)>[];
      for (final course in widget.courses.where((c) => c.tracksAttendance)) {
        for (final session in await widget.sessions.listSessions(course.id)) {
          final expected = session.startsAt.add(const Duration(minutes: 20));
          if (session.calendarStatus.requiresAttendance &&
              session.attendanceStatus == null &&
              session.firstPing == null &&
              expected.isAfter(widget.now()) &&
              expected.isBefore(session.endsAt) &&
              expected.difference(widget.now()) <= const Duration(days: 180)) {
            options.add((course, session));
          }
        }
      }
      options.sort((a, b) => a.$2.startsAt.compareTo(b.$2.startsAt));
      final reports = await widget.gateway.perform('read');
      if (mounted) {
        setState(() {
          _options = options;
          _reports = reports;
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
          () => _error =
              'Não foi possível consultar os primeiros pings. Tente atualizar.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
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
      if (mounted) setState(() => _reports = reports);
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
              'Não foi possível concluir. Confira permissões e tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _date(Object? ms) {
    if (ms is! int) return 'Horário indisponível';
    final d = DateTime.fromMillisecondsSinceEpoch(ms).toLocal();
    return '${d.day.toString().padLeft(2, "0")}/${d.month.toString().padLeft(2, "0")} ${d.hour.toString().padLeft(2, "0")}:${d.minute.toString().padLeft(2, "0")}';
  }

  String _result(Map<String, Object?> report) => switch (report['status']) {
    'scheduled' => 'Agendado — aguardando o Android',
    'running' => 'Capturando localização',
    'cancelled' => 'Cancelado',
    'succeeded' when report['first_ping'] == 'no_campus' =>
      'Primeiro ping: no campus',
    'succeeded' when report['first_ping'] == 'fora' =>
      'Primeiro ping: fora do campus',
    'superseded' => 'Horário substituído',
    'checkpoint_outside_window' => 'Horário perdido — sem evidência válida',
    _ => 'Localização indisponível (${report['status']})',
  };
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Primeiro ping'),
      actions: [
        IconButton(
          tooltip: 'Atualizar primeiros pings',
          onPressed: _busy ? null : _load,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text(
          'Agende uma verificação 20 minutos após o início da aula. O Android pode atrasar: até 5 minutos após esse horário, antes do fim da aula; fora dessa janela, o resultado fica indisponível.',
        ),
        const SizedBox(height: 12),
        const Text(
          'Requer localização precisa permitida sempre e bateria sem restrições. Até 50 agendamentos/resultados ficam neste aparelho; limpe os encerrados quando necessário. A evidência ainda não encerra a frequência e não substitui registros manuais. O segundo ping entra na próxima etapa.',
        ),
        if (_busy) const LinearProgressIndicator(),
        if (_error case final error?)
          Text(
            error,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (_options.isEmpty && !_busy)
          const Text('Nenhuma sessão elegível para agendar.'),
        if (_options.isNotEmpty)
          DropdownButtonFormField<int>(
            key: ValueKey(_options.map((e) => e.$2.id).join(',')),
            initialValue: _selected,
            isExpanded: true,
            decoration: const InputDecoration(labelText: 'Sessão'),
            items: [
              for (var i = 0; i < _options.length; i++)
                DropdownMenuItem(
                  value: i,
                  child: Text(
                    '${_options[i].$1.code} • ${_date(_options[i].$2.startsAt.add(const Duration(minutes: 20)).millisecondsSinceEpoch)}',
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
          child: const Text('Agendar primeiro ping'),
        ),
        if (_reports.isNotEmpty)
          TextButton(
            onPressed: _busy ? null : () => _act('clear_completed'),
            child: const Text('Limpar resultados encerrados'),
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
                      child: const Text('Cancelar primeiro ping'),
                    ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}
