import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../backend/python_backend_transport.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

class UFMGConnectionPage extends StatefulWidget {
  const UFMGConnectionPage({
    required this.gateway,
    required this.logger,
    this.userId,
    this.syncSchedule,
    this.openExternalUri,
    super.key,
  });

  final BackendUFMGSessionGateway gateway;
  final AppLogger logger;
  final String? userId;
  final UFMGSyncScheduleGateway? syncSchedule;
  final Future<bool> Function(Uri uri)? openExternalUri;

  @override
  State<UFMGConnectionPage> createState() => _UFMGConnectionPageState();
}

class _UFMGConnectionPageState extends State<UFMGConnectionPage> {
  final _formKey = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  PythonUFMGSessionStatus? _status;
  bool _loading = true;
  bool _busy = false;
  bool _showReconnectForm = false;
  String? _error;
  String? _importSummary;
  List<PythonMoodleDate> _dates = const [];
  PythonMoodleContentDiscovery? _contentDiscovery;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionStatus,
        action: widget.gateway.getUFMGSessionStatus,
      );
      if (mounted) setState(() => _status = status);
      try {
        final dates = await _listDates();
        if (mounted) setState(() => _dates = dates);
      } catch (_) {
        // Imported dates are supplementary; their failure must not hide the
        // UFMG connection controls or the attendance core.
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Não foi possível consultar a conexão com a UFMG.',
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openMoodleMaterial(
    PythonMoodleContentCandidate candidate,
  ) async {
    final uri = candidate.url;
    if (uri == null || !candidate.canOpenDirectly) return;
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialOpen,
        action: () async {
          final launcher = widget.openExternalUri ?? _openExternalUri;
          if (!await launcher(uri)) {
            throw StateError('moodle_material_launch_rejected');
          }
        },
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Não foi possível abrir este material no Moodle.'),
        ),
      );
    }
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionConnect,
        action: () => widget.gateway.connectUFMG(
          username: _username.text,
          password: _password.text,
        ),
      );
      _username.clear();
      if (mounted) {
        setState(() {
          _status = status;
          _showReconnectForm = false;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = _messageFor(error));
    } finally {
      _password.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDisconnect() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Desconectar da UFMG?'),
        content: const Text(
          'A sessão acadêmica salva será apagada. Seus registros de frequência permanecem intactos.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Desconectar'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionDisconnect,
        action: widget.gateway.disconnectUFMG,
      );
      if (mounted) setState(() => _status = status);
    } catch (error) {
      if (mounted) setState(() => _error = _messageFor(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _syncSiga() async {
    setState(() {
      _busy = true;
      _error = null;
      _importSummary = null;
    });
    try {
      final result = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSync,
        action: widget.gateway.syncSiga,
      );
      final userId = widget.userId;
      final schedule = widget.syncSchedule;
      if (userId != null && schedule != null) {
        await schedule.record(userId, result.nextAutomaticSyncAt);
      }
      if (mounted) {
        setState(() {
          _importSummary =
              '${result.courses.created} ${_plural(result.courses.created, 'disciplina importada', 'disciplinas importadas')}. '
              '${result.courses.existing} já ${result.courses.existing == 1 ? 'estava cadastrada' : 'estavam cadastradas'}. '
              '${result.schedules.updated} ${_plural(result.schedules.updated, 'grade atualizada', 'grades atualizadas')}. '
              '${result.schedules.unchanged} ${_plural(result.schedules.unchanged, 'grade sem alteração', 'grades sem alteração')}. '
              '${result.schedules.conflicts} ${_plural(result.schedules.conflicts, 'conflito preservado', 'conflitos preservados')}.';
        });
      }
    } catch (error) {
      if (!mounted) return;
      if (error is PythonBackendException &&
          error.code == PythonBackendError.ufmgReauthenticationRequired) {
        setState(() {
          _status = const PythonUFMGSessionStatus(
            connected: false,
            reauthenticationRequired: true,
          );
          _error = 'Sua sessão expirou. Reconecte para sincronizar.';
        });
      } else {
        setState(() => _error = _syncMessageFor(error));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _syncMoodle() async {
    setState(() {
      _busy = true;
      _error = null;
      _importSummary = null;
    });
    try {
      final result = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleDateImport,
        action: widget.gateway.importMoodleDates,
      );
      final discovery = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleContentDiscovery,
        action: widget.gateway.discoverMoodleContent,
      );
      String capabilitySummary;
      try {
        final capabilities = await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleMobileCapability,
          action: widget.gateway.probeMoodleMobileCapabilities,
        );
        capabilitySummary = capabilities.directDownloadSupported
            ? ' Download direto disponível.'
            : ' Download direto ainda não disponível.';
      } on PythonBackendException catch (error) {
        if (error.code == PythonBackendError.ufmgReauthenticationRequired) {
          rethrow;
        }
        capabilitySummary =
            ' Não foi possível validar o download direto agora.';
      } catch (_) {
        capabilitySummary =
            ' Não foi possível validar o download direto agora.';
      }
      final dates = await _listDates();
      if (mounted) {
        setState(() {
          _dates = dates;
          _contentDiscovery = discovery;
          _importSummary =
              '${result.created} ${_plural(result.created, 'data do Moodle importada', 'datas do Moodle importadas')}. '
              '${result.updated} ${_plural(result.updated, 'data atualizada', 'datas atualizadas')}. '
              '${result.unchanged} sem alteração. '
              '${result.unmatched} ${_plural(result.unmatched, 'data não pôde ser ligada a uma disciplina', 'datas não puderam ser ligadas a uma disciplina')}. '
              '${discovery.candidateTotal} ${_plural(discovery.candidateTotal, 'material candidato encontrado', 'materiais candidatos encontrados')}.'
              '$capabilitySummary';
        });
      }
    } catch (error) {
      if (!mounted) return;
      if (error is PythonBackendException &&
          error.code == PythonBackendError.ufmgReauthenticationRequired) {
        setState(() {
          _status = const PythonUFMGSessionStatus(
            connected: false,
            reauthenticationRequired: true,
          );
          _error = 'Sua sessão expirou. Reconecte para sincronizar o Moodle.';
        });
      } else {
        setState(() => _error = _moodleSyncMessageFor(error));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<List<PythonMoodleDate>> _listDates() => runAuditedOperation(
    logger: widget.logger,
    operation: AuditedOperation.moodleDateList,
    action: widget.gateway.listMoodleDates,
  );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Conexão UFMG')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 560),
              child: _loading ? const CircularProgressIndicator() : _content(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _content() {
    final status = _status;
    final connected = status?.connected ?? false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Icon(
          connected
              ? Icons.verified_user_outlined
              : Icons.account_balance_outlined,
          size: 56,
          color: connected
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(height: 16),
        Text(
          connected
              ? 'UFMG conectada'
              : status?.reauthenticationRequired == true
              ? 'Sua sessão expirou'
              : 'Conectar à UFMG',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          connected
              ? 'A sessão acadêmica pode ser usada nas próximas sincronizações.'
              : 'Use seu login institucional para permitir sincronizações. Sua senha não é armazenada.',
          textAlign: TextAlign.center,
        ),
        if (connected && status?.expiresAt != null) ...[
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.schedule_outlined),
              title: const Text('Sessão temporária'),
              subtitle: Text(
                'Válida até ${_formattedExpiry(status!.expiresAt!)}',
              ),
            ),
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 16),
          Semantics(
            liveRegion: true,
            child: Text(
              _error!,
              textAlign: TextAlign.center,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        ],
        const SizedBox(height: 24),
        if (!connected || _showReconnectForm)
          _connectionForm()
        else
          _syncActions(),
        if (_importSummary != null) ...[
          const SizedBox(height: 16),
          Semantics(
            liveRegion: true,
            child: Card(
              child: ListTile(
                leading: const Icon(Icons.check_circle_outline),
                title: Text(_importSummary!),
                subtitle: const Text(
                  'Dados já cadastrados, correções manuais e registros de frequência foram preservados.',
                ),
              ),
            ),
          ),
        ],
        if (_dates.isNotEmpty) ...[
          const SizedBox(height: 24),
          Text(
            'Datas do Moodle',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          for (final date in _dates)
            Card(
              child: ListTile(
                leading: Icon(_dateIcon(date.kind)),
                title: Text(date.title),
                subtitle: Text(
                  '${date.courseCode} • ${_formattedDate(date.dueAt)}',
                ),
              ),
            ),
        ],
        if (_contentDiscovery != null) ...[
          const SizedBox(height: 24),
          Text(
            'Materiais do Moodle',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          const Text(
            'Os materiais abrem diretamente na UFMG. O Moodle pode pedir login '
            'se a sessão do navegador tiver expirado.',
          ),
          const SizedBox(height: 8),
          for (final course in _contentDiscovery!.courses)
            Card(
              child: ExpansionTile(
                key: Key('moodle-content-${course.courseId}'),
                title: Text(course.courseCode),
                subtitle: Text(_contentStatus(course)),
                children: [
                  for (final candidate in course.candidates)
                    ListTile(
                      leading: Icon(_contentIcon(candidate.kind)),
                      title: Text(candidate.title),
                      subtitle: Text(_candidateLabel(candidate)),
                      trailing: candidate.canOpenDirectly
                          ? IconButton(
                              key: Key(
                                'moodle-material-open-${candidate.sourceId}',
                              ),
                              tooltip: 'Abrir no Moodle',
                              onPressed: () => _openMoodleMaterial(candidate),
                              icon: const Icon(Icons.open_in_new),
                            )
                          : null,
                    ),
                ],
              ),
            ),
        ],
      ],
    );
  }

  Widget _syncActions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Sincronizar dados',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        FilledButton.icon(
          key: const Key('ufmg-sync-siga'),
          onPressed: _busy ? null : _syncSiga,
          icon: _busy
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.school_outlined),
          label: const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Column(
              children: [
                Text('Sincronizar SIGA'),
                Text('Disciplinas e horários'),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton.tonalIcon(
          key: const Key('ufmg-sync-moodle'),
          onPressed: _busy ? null : _syncMoodle,
          icon: _busy
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.menu_book_outlined),
          label: const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Column(
              children: [
                Text('Sincronizar Moodle'),
                Text('Datas, planos de ensino e cronogramas'),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          margin: EdgeInsets.zero,
          child: ExpansionTile(
            key: const Key('ufmg-manage-connection'),
            leading: const Icon(Icons.settings_outlined),
            title: const Text('Gerenciar conexão'),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            children: [
              SizedBox(
                width: double.infinity,
                child: TextButton.icon(
                  key: const Key('ufmg-reconnect'),
                  onPressed: _busy
                      ? null
                      : () => setState(() => _showReconnectForm = true),
                  icon: const Icon(Icons.sync),
                  label: const Text('Reconectar'),
                ),
              ),
              SizedBox(
                width: double.infinity,
                child: TextButton.icon(
                  key: const Key('ufmg-disconnect'),
                  onPressed: _busy ? null : _confirmDisconnect,
                  icon: const Icon(Icons.link_off),
                  label: const Text('Desconectar'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _connectionForm() {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextFormField(
            key: const Key('ufmg-username'),
            controller: _username,
            enabled: !_busy,
            autofillHints: const [AutofillHints.username],
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Usuário MinhaUFMG',
              prefixIcon: Icon(Icons.person_outline),
            ),
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Informe seu usuário da UFMG.'
                : null,
          ),
          const SizedBox(height: 16),
          TextFormField(
            key: const Key('ufmg-password'),
            controller: _password,
            enabled: !_busy,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            autofillHints: const [AutofillHints.password],
            onFieldSubmitted: (_) => _busy ? null : _connect(),
            decoration: const InputDecoration(
              labelText: 'Senha MinhaUFMG',
              prefixIcon: Icon(Icons.lock_outline),
            ),
            validator: (value) => value == null || value.isEmpty
                ? 'Informe sua senha da UFMG.'
                : null,
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            key: const Key('ufmg-connect'),
            onPressed: _busy ? null : _connect,
            icon: _busy
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.link),
            label: Text(connectedLabel),
          ),
          if (_showReconnectForm) ...[
            const SizedBox(height: 8),
            TextButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                      _showReconnectForm = false;
                      _username.clear();
                      _password.clear();
                    }),
              child: const Text('Cancelar'),
            ),
          ],
        ],
      ),
    );
  }

  String get connectedLabel =>
      _showReconnectForm ? 'Renovar conexão' : 'Conectar';

  String _formattedExpiry(DateTime expiry) {
    final local = expiry.toLocal();
    return '${MaterialLocalizations.of(context).formatMediumDate(local)} às '
        '${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(local))}';
  }

  String _formattedDate(DateTime value) {
    final local = value.toLocal();
    return '${MaterialLocalizations.of(context).formatMediumDate(local)} às '
        '${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(local))}';
  }

  static IconData _dateIcon(String kind) => switch (kind) {
    'assignment' => Icons.assignment_outlined,
    'quiz' => Icons.quiz_outlined,
    _ => Icons.event_outlined,
  };

  static IconData _contentIcon(String kind) => switch (kind) {
    'page' => Icons.article_outlined,
    'file' => Icons.attach_file,
    _ => Icons.notes_outlined,
  };

  static String _contentStatus(
    PythonMoodleCourseContent course,
  ) => switch (course.status) {
    PythonMoodleContentStatus.found =>
      '${course.candidates.length} ${_plural(course.candidates.length, 'material candidato', 'materiais candidatos')}',
    PythonMoodleContentStatus.empty =>
      'Nenhuma publicação candidata encontrada',
    PythonMoodleContentStatus.unmatched =>
      'Disciplina não localizada no Moodle',
    PythonMoodleContentStatus.ambiguous =>
      'Mais de uma disciplina correspondente no Moodle',
  };

  static String _relevanceLabel(String relevance) => switch (relevance) {
    'teaching_plan' => 'Possível plano de ensino',
    'schedule' => 'Possível cronograma',
    _ => 'Material da disciplina',
  };

  static String _candidateLabel(PythonMoodleContentCandidate candidate) {
    final relevance = _relevanceLabel(candidate.relevance);
    return candidate.origin == PythonMoodleContentOrigin.metaturma
        ? '$relevance • Metaturma'
        : relevance;
  }

  static String _messageFor(Object error) {
    if (error is PythonBackendException) {
      return switch (error.code) {
        PythonBackendError.ufmgCredentialsInvalid =>
          'Usuário ou senha da UFMG inválidos.',
        PythonBackendError.ufmgUnavailable ||
        PythonBackendError.unavailable ||
        PythonBackendError.timeout =>
          'A UFMG está indisponível no momento. Tente novamente mais tarde.',
        PythonBackendError.rateLimited =>
          'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
        _ => 'Não foi possível atualizar a conexão com a UFMG.',
      };
    }
    return 'Não foi possível atualizar a conexão com a UFMG.';
  }

  static String _moodleSyncMessageFor(Object error) {
    if (error is PythonBackendException) {
      return switch (error.code) {
        PythonBackendError.ufmgUnavailable ||
        PythonBackendError.unavailable ||
        PythonBackendError.timeout =>
          'Não foi possível sincronizar com o Moodle agora.',
        PythonBackendError.rateLimited =>
          'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
        _ => 'Não foi possível sincronizar os dados do Moodle.',
      };
    }
    return 'Não foi possível sincronizar os dados do Moodle.';
  }

  static String _syncMessageFor(Object error) {
    if (error is PythonBackendException) {
      return switch (error.code) {
        PythonBackendError.ufmgUnavailable ||
        PythonBackendError.unavailable ||
        PythonBackendError.timeout =>
          'Não foi possível sincronizar com a UFMG agora.',
        PythonBackendError.rateLimited =>
          'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
        _ => 'Não foi possível sincronizar os dados da UFMG.',
      };
    }
    return 'Não foi possível sincronizar os dados da UFMG.';
  }

  static String _plural(int count, String singular, String plural) =>
      count == 1 ? singular : plural;
}

Future<bool> _openExternalUri(Uri uri) =>
    launchUrl(uri, mode: LaunchMode.externalApplication);
