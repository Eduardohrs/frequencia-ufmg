import 'dart:async';
import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;
import 'package:url_launcher/url_launcher.dart';
import '../../backend/python_backend_transport.dart';
import '../../data/academic_records.dart';
import '../../data/course_activity_snapshot_cache.dart';
import '../../data/material_file_cache.dart';
import '../../data/material_file_cache_factory.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';

enum _Section { activities, dates, plan }

class CourseWorkspacePage extends StatefulWidget {
  const CourseWorkspacePage({
    required this.course,
    required this.gateway,
    required this.logger,
    required this.now,
    this.userId,
    this.onConnect,
    this.materialFileCache,
    this.openExternalUri,
    this.snapshotCache,
    super.key,
  });
  final CourseActivitySnapshotCache? snapshotCache;
  final CourseRecord course;
  final BackendAcademicWorkspaceGateway gateway;
  final AppLogger logger;
  final DateTime Function() now;
  final String? userId;
  final Future<void> Function()? onConnect;
  final MaterialFileCache? materialFileCache;
  final Future<bool> Function(Uri)? openExternalUri;
  @override
  State<CourseWorkspacePage> createState() => _CourseWorkspacePageState();
}

class _CourseWorkspacePageState extends State<CourseWorkspacePage> {
  _Section _section = _Section.activities;
  final _loaded = <_Section>{}, _loading = <_Section>{}, _failed = <_Section>{};
  List<PythonMoodleActivity> _activities = [];
  PythonCourseActivitySnapshot? _snapshot;
  bool _localSnapshot = false;
  bool _cacheWriteFailed = false;
  late final _snapshotCache =
      widget.snapshotCache ?? CourseActivitySnapshotCache();
  List<PythonMoodleDate> _dates = [];
  Map<String, Object?>? _plan;
  bool _saving = false;
  String? _openingActivity;
  late final MaterialFileCache _files;
  Map<String, Object> _fields(String stage) => {
    'operation_id': newCorrelationId('course_workspace'),
    'course_id': widget.course.id,
    'course_code': widget.course.code,
    'screen': 'course_workspace',
    'stage': stage,
  };
  @override
  void initState() {
    super.initState();
    _files = widget.materialFileCache ?? createMaterialFileCache(widget.userId);
    unawaited(_load(_section));
  }

  @override
  void dispose() {
    if (widget.materialFileCache == null) _files.dispose();
    super.dispose();
  }

  Future<void> _load(_Section section) async {
    if (_loading.contains(section)) return;
    setState(() => _loading.add(section));
    final fields = _fields(section.name);
    final watch = Stopwatch()..start();
    emitOperationalEvent(
      widget.logger,
      'course_workspace_read_started',
      fields,
    );
    try {
      switch (section) {
        case _Section.activities:
          await _restoreSnapshot();
          final snapshot = await widget.gateway.loadCourseActivitySnapshot(
            widget.course.id,
          );
          if (snapshot.term != widget.course.term) {
            throw const FormatException('Snapshot semester mismatch');
          }
          fields['snapshot_synced_at'] = snapshot.syncedAt.toIso8601String();
          fields['snapshot_source'] = 'server';
          if (mounted) {
            _snapshot = snapshot;
            _activities = snapshot.activities;
            _localSnapshot = false;
          }
          if (widget.userId case final user?) {
            try {
              await _snapshotCache.write(user, snapshot);
              if (mounted) _cacheWriteFailed = false;
              emitOperationalEvent(
                widget.logger,
                'activity_snapshot_cache_written',
                {...fields, 'item_count': snapshot.details.length},
              );
            } catch (error, stack) {
              recordOperationalFailure(
                widget.logger,
                error,
                stack,
                'activity_snapshot_cache_write',
                fields,
                failureCode: 'activity_snapshot_cache_write_failed',
              );
              if (mounted) _cacheWriteFailed = true;
            }
          }
        case _Section.dates:
          final entries = await widget.gateway.listCourseDates(
            widget.course.id,
          );
          if (mounted) _dates = entries;
        case _Section.plan:
          final plan = await widget.gateway.loadCoursePlan(widget.course.id);
          if (mounted) _plan = plan;
      }
      emitOperationalEvent(widget.logger, 'course_workspace_read_succeeded', {
        ...fields,
        'applied_to_view': mounted,
        'duration_ms': watch.elapsedMilliseconds,
        'item_count': section == _Section.activities
            ? _activities.length
            : section == _Section.dates
            ? _dates.length
            : _plan == null
            ? 0
            : 1,
      });
      if (!mounted) return;
      setState(() {
        _loaded.add(section);
        _failed.remove(section);
      });
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_workspace_read',
        {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
          'retained_previous': _loaded.contains(section),
        },
        failureCode: 'course_workspace_read_failed',
      );
      if (mounted) setState(() => _failed.add(section));
    } finally {
      if (mounted) setState(() => _loading.remove(section));
    }
  }

  Future<void> _restoreSnapshot() async {
    final user = widget.userId;
    if (user == null || _snapshot != null) return;
    final fields = _fields('activity_snapshot_cache_read');
    try {
      final snapshot = await _snapshotCache.read(
        user,
        widget.course.id,
        widget.course.term,
      );
      emitOperationalEvent(widget.logger, 'activity_snapshot_cache_read', {
        ...fields,
        'cache_hit': snapshot != null,
        'snapshot_synced_at': ?snapshot?.syncedAt.toIso8601String(),
      });
      if (snapshot != null && mounted) {
        setState(() {
          _snapshot = snapshot;
          _activities = snapshot.activities;
          _localSnapshot = true;
          _loaded.add(_Section.activities);
        });
      }
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'activity_snapshot_cache_read',
        fields,
        failureCode: 'activity_snapshot_cache_read_failed',
      );
    }
  }

  Future<void> _requestSync() async {
    final fields = _fields('sync_navigation');
    emitOperationalEvent(
      widget.logger,
      'course_activity_sync_requested',
      fields,
    );
    try {
      await widget.onConnect!();
      emitOperationalEvent(
        widget.logger,
        'course_activity_sync_returned',
        fields,
      );
      if (mounted) await _load(_section);
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_activity_sync_navigation',
        fields,
        failureCode: 'course_activity_sync_navigation_failed',
      );
      if (mounted) {
        _message(
          'Não foi possível abrir a sincronização. A cópia salva continua disponível.',
        );
      }
    }
  }

  void _select(_Section section) {
    emitOperationalEvent(
      widget.logger,
      'course_workspace_section_selected',
      _fields(section.name),
    );
    setState(() => _section = section);
    if (!_loaded.contains(section)) unawaited(_load(section));
  }

  void _message(String text) {
    ScaffoldMessenger.of(context)
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(text)));
  }

  Future<void> _editDate([PythonMoodleDate? date]) async {
    final fields = {..._fields('date_editor'), 'date_id': date?.id ?? 'new'};
    emitOperationalEvent(widget.logger, 'course_date_editor_opened', fields);
    final input = await showDialog<_DateInput>(
      context: context,
      builder: (_) => _DateEditor(date: date, now: widget.now),
    );
    emitOperationalEvent(widget.logger, 'course_date_editor_closed', {
      ...fields,
      'saved': input != null,
    });
    if (input == null || !mounted) return;
    await _mutate(
      'save_date',
      () => widget.gateway.saveCourseDate(
        widget.course.id,
        date?.id ?? 'manual-${newCorrelationId('date')}',
        title: input.title,
        dueAt: input.dueAt,
        kind: input.kind,
      ),
    );
  }

  Future<void> _deleteDate(PythonMoodleDate date) async {
    emitOperationalEvent(widget.logger, 'course_date_delete_requested', {
      ..._fields('delete_confirmation'),
      'date_id': date.id,
      'title': date.title,
    });
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Excluir prazo?'),
        content: Text(date.title),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Excluir'),
          ),
        ],
      ),
    );
    emitOperationalEvent(widget.logger, 'course_date_delete_confirmation', {
      ..._fields('delete_confirmation'),
      'date_id': date.id,
      'confirmed': confirmed == true,
    });
    if (confirmed != true || !mounted) return;
    await _mutate(
      'delete_date',
      () => widget.gateway.deleteCourseDate(widget.course.id, date.id),
    );
  }

  Future<void> _mutate(String stage, Future<void> Function() operation) async {
    if (_saving) return;
    setState(() => _saving = true);
    final fields = _fields(stage);
    final watch = Stopwatch()..start();
    emitOperationalEvent(
      widget.logger,
      'course_workspace_mutation_started',
      fields,
    );
    try {
      await operation();
      emitOperationalEvent(
        widget.logger,
        'course_workspace_mutation_succeeded',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
      );
      if (mounted) await _load(_Section.dates);
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_workspace_mutation',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        failureCode: 'course_date_save_failed',
      );
      if (mounted) {
        _message('Não foi possível salvar a alteração. Tente novamente.');
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _activity(PythonMoodleActivity activity) async {
    if (_openingActivity != null) return;
    _openingActivity = activity.id;
    final fields = {..._fields('activity_detail'), 'activity_id': activity.id};
    final watch = Stopwatch()..start();
    emitOperationalEvent(widget.logger, 'course_activity_open_started', fields);
    try {
      final detail = _snapshot!.details.firstWhere(
        (e) => e.activity.id == activity.id,
      );
      emitOperationalEvent(widget.logger, 'course_activity_open_succeeded', {
        ...fields,
        'duration_ms': watch.elapsedMilliseconds,
        'source': 'snapshot',
        'synced_at': _snapshot!.syncedAt.toIso8601String(),
        'submission_state': detail.submissionState,
        'attachment_count': detail.attachmentCount,
      });
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: DraggableScrollableSheet(
            expand: false,
            initialChildSize: .8,
            minChildSize: .4,
            maxChildSize: .95,
            builder: (context, controller) => ListView(
              controller: controller,
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 32),
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: IconButton(
                    tooltip: 'Fechar atividade',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close),
                  ),
                ),
                Text(
                  activity.title,
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 20),
                Text(
                  detail.submissionText.isEmpty
                      ? 'Situação do envio não informada pelo Moodle.'
                      : detail.submissionText,
                ),
                const SizedBox(height: 12),
                Text(
                  detail.datesText.isEmpty
                      ? 'Sem prazo publicado'
                      : detail.datesText,
                ),
                if (detail.description.isNotEmpty) ...[
                  const SizedBox(height: 24),
                  SelectableText(detail.description),
                ],
                if (detail.attachmentCount > 0) ...[
                  const SizedBox(height: 24),
                  Text(
                    'Anexos',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  for (var i = 0; i < detail.attachmentNames.length; i++)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(detail.attachmentNames[i]),
                      trailing: const Icon(Icons.download_outlined),
                      onTap: () => _downloadSnapshotAttachment(detail, i),
                    ),
                ],
              ],
            ),
          ),
        ),
      );
    } finally {
      _openingActivity = null;
    }
  }

  Future<void> _downloadSnapshotAttachment(
    PythonMoodleActivityDetail saved,
    int index,
  ) async {
    final fields = {
      ..._fields('saved_attachment_authorization'),
      'activity_id': saved.activity.id,
      'attachment_index': index,
      'file_name': saved.attachmentNames[index],
    };
    final watch = Stopwatch()..start();
    emitOperationalEvent(
      widget.logger,
      'course_activity_attachment_authorization_started',
      fields,
    );
    try {
      final authorized = await widget.gateway.loadCourseActivity(
        widget.course.id,
        saved.activity.id,
      );
      final matching = authorized.files
          .where((file) => file.name == saved.attachmentNames[index])
          .toList();
      if (matching.length != 1) {
        throw StateError('saved_attachment_authorization_unavailable');
      }
      emitOperationalEvent(
        widget.logger,
        'course_activity_attachment_authorization_succeeded',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
      );
      await _download(authorized, matching.single);
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'saved_attachment_authorization',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        failureCode: 'saved_attachment_authorization_failed',
      );
      if (mounted) {
        _message(
          'Não foi possível autorizar os anexos. O enunciado salvo continua disponível.',
        );
      }
    }
  }

  Future<void> _download(
    PythonMoodleActivityDetail detail,
    PythonMoodleMaterialFile file,
  ) async {
    final fields = {
      ..._fields('attachment_download'),
      'activity_id': detail.activity.id,
      'file_name': file.name,
    };
    emitOperationalEvent(
      widget.logger,
      'course_activity_download_started',
      fields,
    );
    try {
      if (_files.isAvailable) {
        final download = MaterialDownload(
          id: '${detail.term}/activity/${detail.activity.id}/${file.name}',
          name: file.name,
          source: file.url,
          expectedSize: file.size,
          mimeType: file.mimeType,
        );
        if (_files case final BackgroundMaterialDownloadQueue queue) {
          await queue.enqueue(download);
        } else {
          await _files.save(download);
        }
      } else {
        final opened = await (widget.openExternalUri ?? launchUrl)(file.url);
        if (!opened) throw StateError('attachment_launch_failed');
      }
      emitOperationalEvent(
        widget.logger,
        'course_activity_download_scheduled',
        fields,
      );
      if (mounted) {
        _message(
          _files.isAvailable
              ? 'Download iniciado. O arquivo ficará disponível offline.'
              : 'Download aberto no navegador.',
        );
      }
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_activity_download',
        fields,
        failureCode: 'course_activity_download_failed',
      );
      if (mounted) _message('Não foi possível iniciar o download.');
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.course.code)),
    floatingActionButton: _section == _Section.dates
        ? FloatingActionButton.extended(
            key: const Key('workspace-add-date'),
            onPressed: _saving ? null : () => _editDate(),
            icon: const Icon(Icons.add),
            label: const Text('Adicionar prazo'),
          )
        : null,
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 900),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.all(20),
                child: SegmentedButton<_Section>(
                  segments: const [
                    ButtonSegment(
                      value: _Section.activities,
                      label: Text('Atividades'),
                    ),
                    ButtonSegment(value: _Section.dates, label: Text('Prazos')),
                    ButtonSegment(value: _Section.plan, label: Text('Plano')),
                  ],
                  selected: {_section},
                  showSelectedIcon: false,
                  onSelectionChanged: (values) => _select(values.single),
                ),
              ),
              if (_loading.contains(_section)) const LinearProgressIndicator(),
              if (_failed.contains(_section))
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Column(
                    children: [
                      const Text(
                        'Não foi possível atualizar esta seção. Os outros dados continuam disponíveis.',
                      ),
                      Wrap(
                        children: [
                          TextButton(
                            onPressed: () => _load(_section),
                            child: const Text('Tentar novamente'),
                          ),
                          if (widget.onConnect != null)
                            TextButton(
                              onPressed: _requestSync,
                              child: const Text('Conexão UFMG'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              Expanded(
                child: _section == _Section.activities
                    ? _activityList()
                    : _section == _Section.dates
                    ? _dateList()
                    : _planView(),
              ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget _activityList() => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      if (widget.onConnect != null)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _requestSync,
            icon: const Icon(Icons.sync),
            label: const Text('Sincronizar Moodle'),
          ),
        ),
      if (_cacheWriteFailed)
        const Padding(
          padding: EdgeInsets.only(bottom: 16),
          child: Text(
            'Não foi possível salvar esta cópia no dispositivo. Ela continua disponível no servidor.',
          ),
        ),
      if (_snapshot case final snapshot?)
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            '${_localSnapshot ? 'Cópia local' : 'Última sincronização'}: ${_displayDate(snapshot.syncedAt)}. Situação de envio registrada nessa data.',
          ),
        ),
      if (_loaded.contains(_Section.activities) && _activities.isEmpty)
        const Text('Nenhuma atividade disponível nesta disciplina.'),
      for (final activity in _activities)
        ListTile(
          key: Key('workspace-activity-${activity.id}'),
          contentPadding: EdgeInsets.zero,
          title: Text(activity.title),
          subtitle: Text(
            '${activity.kind == 'assign' ? 'Tarefa · consultar enunciado e envio' : 'Questionário'}${activity.origin == 'metaturma' ? ' · Metaturma' : ''}',
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: _openingActivity == null ? () => _activity(activity) : null,
        ),
    ],
  );
  Widget _dateList() => ListView(
    padding: const EdgeInsets.fromLTRB(20, 0, 20, 100),
    children: [
      if (_loaded.contains(_Section.dates) && _dates.isEmpty)
        const Text('Nenhum prazo cadastrado.'),
      for (final date in _dates)
        ListTile(
          key: Key('workspace-date-${date.id}'),
          contentPadding: EdgeInsets.zero,
          title: Text(date.title),
          subtitle: Text(
            '${_displayDate(date.dueAt)} · ${date.id.startsWith('manual-')
                ? 'Manual'
                : date.id.startsWith('diario-')
                ? 'Plano de ensino'
                : 'Moodle'}',
          ),
          onTap: _saving ? null : () => _editDate(date),
          trailing: date.id.startsWith('manual-')
              ? IconButton(
                  tooltip: 'Excluir prazo',
                  onPressed: _saving ? null : () => _deleteDate(date),
                  icon: const Icon(Icons.delete_outline),
                )
              : const Icon(Icons.edit_outlined),
        ),
    ],
  );
  Widget _planView() {
    if (!_loaded.contains(_Section.plan)) return const SizedBox.shrink();
    if (_plan == null) {
      return const Padding(
        padding: EdgeInsets.all(20),
        child: Text('Nenhum plano de ensino importado para esta disciplina.'),
      );
    }
    final criteria = _plan!['criteria']! as List;
    final assessments = _plan!['assessments']! as List;
    final schedule = _plan!['schedule']! as List;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          'Plano de ensino',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 20),
        Text(
          'Critérios de avaliação',
          style: Theme.of(context).textTheme.titleMedium,
        ),
        if (criteria.isEmpty) const Text('Não informados no plano.'),
        for (final raw in criteria)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('${(raw as Map)['description']}'),
            trailing: Text('${raw['value']}'),
          ),
        ExpansionTile(
          title: Text('Avaliações (${assessments.length})'),
          children: [
            for (final raw in assessments)
              ListTile(
                title: Text('${(raw as Map)['title']}'),
                subtitle: Text(
                  '${_planDate(raw['scheduled_at'] as String)} · Valor: ${raw['value']}',
                ),
              ),
          ],
        ),
        ExpansionTile(
          title: Text('Cronograma (${schedule.length})'),
          children: [
            for (final raw in schedule)
              ListTile(
                title: Text('${(raw as Map)['subject']}'),
                subtitle: Text(
                  '${_planDate(raw['date'] as String)} · ${raw['starts_at'] ?? raw['time'] ?? ''}',
                ),
              ),
          ],
        ),
      ],
    );
  }
}

String _planDate(String value) {
  final date = DateTime.tryParse(value);
  if (date == null) return value;
  if (value.contains('T')) return _displayDate(date);
  return '${date.day.toString().padLeft(2, '0')}/${date.month.toString().padLeft(2, '0')}/${date.year}';
}

String _displayDate(DateTime value) {
  final local = tz.TZDateTime.from(value, tz.getLocation('America/Sao_Paulo'));
  return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}/${local.year} ${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
}

final class _DateInput {
  const _DateInput(this.title, this.dueAt, this.kind);
  final String title, kind;
  final DateTime dueAt;
}

class _DateEditor extends StatefulWidget {
  const _DateEditor({this.date, required this.now});
  final PythonMoodleDate? date;
  final DateTime Function() now;
  @override
  State<_DateEditor> createState() => _DateEditorState();
}

class _DateEditorState extends State<_DateEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _title;
  late DateTime _day;
  late TimeOfDay _time;
  late String _kind;
  @override
  void initState() {
    super.initState();
    _title = TextEditingController(text: widget.date?.title ?? '');
    final local = tz.TZDateTime.from(
      widget.date?.dueAt ?? widget.now(),
      tz.getLocation('America/Sao_Paulo'),
    );
    _day = DateTime(local.year, local.month, local.day);
    _time = widget.date == null
        ? const TimeOfDay(hour: 23, minute: 59)
        : TimeOfDay(hour: local.hour, minute: local.minute);
    _kind = widget.date?.kind ?? 'assignment';
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.date == null ? 'Adicionar prazo' : 'Editar prazo'),
    content: SingleChildScrollView(
      child: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextFormField(
              key: const Key('workspace-date-title'),
              controller: _title,
              maxLength: 120,
              decoration: const InputDecoration(labelText: 'Título'),
              validator: (value) => value == null || value.trim().isEmpty
                  ? 'Informe um título'
                  : null,
            ),
            DropdownButtonFormField<String>(
              initialValue: _kind,
              decoration: const InputDecoration(labelText: 'Tipo'),
              items: const [
                DropdownMenuItem(value: 'assignment', child: Text('Trabalho')),
                DropdownMenuItem(value: 'assessment', child: Text('Prova')),
                DropdownMenuItem(value: 'quiz', child: Text('Questionário')),
                DropdownMenuItem(value: 'event', child: Text('Outro')),
              ],
              onChanged: (value) => setState(() => _kind = value!),
            ),
            TextButton(
              key: const Key('workspace-pick-date'),
              onPressed: () async {
                final date = await showDatePicker(
                  context: context,
                  initialDate: _day,
                  firstDate: DateTime(2020),
                  lastDate: DateTime(2040),
                );
                if (date != null && mounted) setState(() => _day = date);
              },
              child: Text('${_day.day}/${_day.month}/${_day.year}'),
            ),
            TextButton(
              key: const Key('workspace-pick-time'),
              onPressed: () async {
                final time = await showTimePicker(
                  context: context,
                  initialTime: _time,
                );
                if (time != null && mounted) setState(() => _time = time);
              },
              child: Text(_time.format(context)),
            ),
            if (widget.date != null && !widget.date!.id.startsWith('manual-'))
              const Text(
                'Sua correção será preservada nas próximas sincronizações.',
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancelar'),
      ),
      FilledButton(
        onPressed: () {
          if (_form.currentState!.validate()) {
            final due = tz.TZDateTime(
              tz.getLocation('America/Sao_Paulo'),
              _day.year,
              _day.month,
              _day.day,
              _time.hour,
              _time.minute,
            ).toUtc();
            Navigator.pop(context, _DateInput(_title.text.trim(), due, _kind));
          }
        },
        child: const Text('Salvar'),
      ),
    ],
  );
}
