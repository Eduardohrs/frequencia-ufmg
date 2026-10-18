import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../backend/python_backend_transport.dart';
import '../../data/material_file_cache.dart';
import '../../data/material_file_cache_factory.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import 'material_cache_card.dart';

class UFMGConnectionPage extends StatefulWidget {
  const UFMGConnectionPage({
    required this.gateway,
    required this.logger,
    this.userId,
    this.syncSchedule,
    this.openExternalUri,
    this.materialFileCache,
    super.key,
  });

  final BackendUFMGSessionGateway gateway;
  final AppLogger logger;
  final String? userId;
  final UFMGSyncScheduleGateway? syncSchedule;
  final Future<bool> Function(Uri uri)? openExternalUri;
  final MaterialFileCache? materialFileCache;

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
  late final MaterialFileCache _materialFileCache;
  late final bool _ownsMaterialFileCache;
  List<CachedMaterialFile> _cachedMaterials = const [];
  List<MaterialDownloadProgress> _materialDownloadProgress = const [];
  Timer? _materialProgressTimer;
  final Set<String> _materialDownloadsInFlight = {};
  final Set<String> _materialDownloadsScheduled = {};
  final Set<String> _reportedMaterialDownloadFailures = {};
  bool _materialBatchRunning = false;
  int _materialBatchCompleted = 0;
  int _materialBatchTotal = 0;
  int _materialBatchFailed = 0;
  List<
    ({PythonMoodleCourseContent course, PythonMoodleContentCandidate candidate})
  >
  _materialBatchFailures = const [];

  void _logInteraction(String action) {
    unawaited(
      widget.logger
          .logEvent(
            'ui_interaction',
            parameters: {'screen': 'ufmg_connection', 'action': action},
          )
          .catchError((Object _) {}),
    );
  }

  @override
  void initState() {
    super.initState();
    _ownsMaterialFileCache = widget.materialFileCache == null;
    _materialFileCache =
        widget.materialFileCache ?? createMaterialFileCache(widget.userId);
    _load();
  }

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _materialProgressTimer?.cancel();
    if (_ownsMaterialFileCache) _materialFileCache.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final supplementary = _loadSupplementaryData();
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionStatus,
        action: widget.gateway.getUFMGSessionStatus,
      );
      if (mounted) setState(() => _status = status);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Não foi possível consultar a conexão com a UFMG.',
        );
      }
    } finally {
      await supplementary;
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadSupplementaryData() => Future.wait([
    _loadDates(),
    _loadMaterialCatalog(),
    _loadCachedMaterials(),
    _loadMaterialDownloadProgress(),
  ]);

  Future<void> _loadMaterialDownloadProgress({bool pollAgain = false}) async {
    if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
      try {
        final progress = await queue.listDownloads();
        if (!mounted) return;
        setState(() {
          _materialDownloadProgress = progress;
          _materialDownloadsScheduled.addAll(
            progress.map((download) => download.id),
          );
        });
        for (final download in progress) {
          if (download.state == MaterialDownloadState.failed &&
              _reportedMaterialDownloadFailures.add(download.id)) {
            unawaited(
              widget.logger
                  .logEvent(
                    'moodle_material_download_failed',
                    parameters: {
                      'failure_code': download.failureCode.isEmpty
                          ? 'unknown'
                          : download.failureCode,
                    },
                  )
                  .catchError((_) {}),
            );
          }
        }
        final active = progress.any(
          (download) =>
              download.state == MaterialDownloadState.enqueued ||
              download.state == MaterialDownloadState.running,
        );
        if (active || pollAgain) {
          _materialProgressTimer?.cancel();
          _materialProgressTimer = Timer(
            const Duration(seconds: 1),
            _loadMaterialDownloadProgress,
          );
        } else if (progress.any(
          (download) => download.state == MaterialDownloadState.succeeded,
        )) {
          await _loadCachedMaterials();
        }
      } catch (_) {
        // Native queue status is supplementary; notifications remain available.
      }
    }
  }

  Future<void> _loadCachedMaterials() async {
    if (!_materialFileCache.isAvailable) return;
    try {
      final files = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheList,
        action: _materialFileCache.list,
      );
      if (mounted) {
        setState(() {
          _cachedMaterials = files;
          _materialDownloadsScheduled.addAll(files.map((file) => file.id));
        });
      }
    } catch (_) {}
  }

  Future<void> _loadDates() async {
    try {
      final dates = await _listDates();
      if (mounted) setState(() => _dates = dates);
    } catch (_) {
      // Imported dates are supplementary and never hide the attendance core.
    }
  }

  Future<void> _loadMaterialCatalog() async {
    try {
      final catalog = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCatalogList,
        action: widget.gateway.listMoodleMaterialCatalog,
      );
      if (mounted && catalog.courses.isNotEmpty) {
        setState(() => _contentDiscovery = catalog);
      }
    } catch (_) {
      // The persisted catalogue is supplementary and may be synced later.
    }
  }

  Future<void> _openMoodleMaterial(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
  ) async {
    _logInteraction('moodle_material_open');
    final operationId = _materialOperationId(course, candidate);
    if (!_materialDownloadsInFlight.add(operationId)) return;
    setState(() {});
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialOpen,
        action: () async {
          if (candidate.kind != 'file') {
            final uri = candidate.canOpenDirectly ? candidate.url : null;
            if (uri != null) await _launchMaterialUri(uri);
            return;
          }
          final file = await _selectMaterialFile(course, candidate);
          if (file == null) return;
          if (_materialFileCache.isAvailable) {
            await _saveMaterialOffline(course, candidate, file);
            return;
          }
          await _launchMaterialUri(file.url);
        },
      );
    } catch (error) {
      if (!mounted) return;
      final message =
          error is PythonBackendException &&
              error.code == PythonBackendError.moodleAuthorizationRequired
          ? 'Sincronize o Moodle novamente para baixar este material.'
          : 'Não foi possível abrir este material no Moodle.';
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    } finally {
      _materialDownloadsInFlight.remove(operationId);
      if (mounted) setState(() {});
    }
  }

  String _materialOperationId(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
  ) => '${course.term}/${candidate.moodleCourseId}/${candidate.sourceId}';

  Future<void> _launchMaterialUri(Uri uri) async {
    final launcher = widget.openExternalUri ?? _openExternalUri;
    if (!await launcher(uri)) {
      throw StateError('moodle_material_launch_rejected');
    }
  }

  Future<PythonMoodleMaterialFile?> _selectMaterialFile(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
  ) async {
    final files = await widget.gateway.listMoodleMaterialFiles(
      term: course.term,
      courseId: candidate.moodleCourseId,
      sourceId: candidate.sourceId,
    );
    if (files.isEmpty) throw StateError('moodle_material_has_no_files');
    if (files.length == 1) return files.single;
    if (!mounted) return null;
    final selected = await showModalBottomSheet<PythonMoodleMaterialFile>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(context).height * 0.65,
          ),
          child: ListView(
            shrinkWrap: true,
            children: [
              const ListTile(title: Text('Escolha um arquivo')),
              for (final file in files)
                ListTile(
                  leading: const Icon(Icons.download_outlined),
                  title: Text(file.name),
                  subtitle: Text(formatMaterialFileSize(file.size)),
                  onTap: () {
                    _logInteraction('moodle_material_file_select');
                    Navigator.pop(context, file);
                  },
                ),
            ],
          ),
        ),
      ),
    );
    return selected;
  }

  Future<void> _saveMaterialOffline(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
    PythonMoodleMaterialFile file, {
    bool announce = true,
  }) async {
    final download = MaterialDownload(
      id:
          '${course.term}/${candidate.moodleCourseId}/'
          '${candidate.sourceId}/${file.name}',
      name: file.name,
      source: file.url,
      expectedSize: file.size,
      mimeType: file.mimeType,
    );
    if (!_materialDownloadsScheduled.add(download.id)) return;
    if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
      try {
        await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleMaterialDownloadEnqueue,
          action: () => queue.enqueue(download),
        );
      } catch (_) {
        _materialDownloadsScheduled.remove(download.id);
        rethrow;
      }
      if (mounted && announce) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Download iniciado em segundo plano.')),
        );
      }
      unawaited(_loadMaterialDownloadProgress(pollAgain: true));
      return;
    }
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheSave,
        action: () => _materialFileCache.save(download),
      );
    } catch (_) {
      _materialDownloadsScheduled.remove(download.id);
      rethrow;
    }
    await _loadCachedMaterials();
    if (mounted && announce) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Arquivo salvo para uso offline.')),
      );
    }
  }

  List<
    ({PythonMoodleCourseContent course, PythonMoodleContentCandidate candidate})
  >
  _downloadableMaterials(Iterable<PythonMoodleCourseContent> courses) {
    final seen = <String>{};
    return [
      for (final course in courses)
        for (final candidate in course.candidates)
          if (candidate.kind == 'file' &&
              candidate.canOpenDirectly &&
              seen.add(
                '${course.term}/${candidate.moodleCourseId}/${candidate.sourceId}',
              ))
            (course: course, candidate: candidate),
    ];
  }

  Future<void> _confirmMaterialBatch(
    String title,
    List<
      ({
        PythonMoodleCourseContent course,
        PythonMoodleContentCandidate candidate,
      })
    >
    materials,
  ) async {
    _logInteraction('moodle_material_batch_prompt');
    if (_materialBatchRunning || materials.isEmpty) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(
          '${materials.length} ${_plural(materials.length, 'material será preparado', 'materiais serão preparados')} para uso offline. '
          'O download usa sua conexão e o armazenamento deste dispositivo.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Baixar'),
          ),
        ],
      ),
    );
    _logInteraction(
      confirmed == true
          ? 'moodle_material_batch_confirm'
          : 'moodle_material_batch_cancel',
    );
    if (confirmed == true && mounted) await _downloadMaterialBatch(materials);
  }

  Future<void> _downloadMaterialBatch(
    List<
      ({
        PythonMoodleCourseContent course,
        PythonMoodleContentCandidate candidate,
      })
    >
    materials,
  ) async {
    setState(() {
      _materialBatchRunning = true;
      _materialBatchCompleted = 0;
      _materialBatchTotal = materials.length;
      _materialBatchFailed = 0;
      _materialBatchFailures = const [];
      _materialDownloadsInFlight.addAll(
        materials.map(
          (material) =>
              _materialOperationId(material.course, material.candidate),
        ),
      );
    });
    var next = 0;
    final failures =
        <
          ({
            PythonMoodleCourseContent course,
            PythonMoodleContentCandidate candidate,
          })
        >[];
    final prepared =
        <
          ({
            PythonMoodleCourseContent course,
            PythonMoodleContentCandidate candidate,
            PythonMoodleMaterialFile file,
          })
        >[];

    Future<void> worker() async {
      while (next < materials.length) {
        final material = materials[next++];
        try {
          final files = await widget.gateway.listMoodleMaterialFiles(
            term: material.course.term,
            courseId: material.candidate.moodleCourseId,
            sourceId: material.candidate.sourceId,
          );
          if (files.isEmpty) throw StateError('moodle_material_has_no_files');
          for (final file in files) {
            prepared.add((
              course: material.course,
              candidate: material.candidate,
              file: file,
            ));
          }
        } catch (_) {
          failures.add(material);
          if (mounted) setState(() => _materialBatchFailed++);
        } finally {
          _materialDownloadsInFlight.remove(
            _materialOperationId(material.course, material.candidate),
          );
          if (mounted) setState(() => _materialBatchCompleted++);
        }
      }
    }

    await Future.wait([worker(), if (materials.length > 1) worker()]);
    for (final item in prepared) {
      try {
        await _saveMaterialOffline(
          item.course,
          item.candidate,
          item.file,
          announce: false,
        );
      } catch (_) {
        final material = (course: item.course, candidate: item.candidate);
        if (!failures.any(
          (failure) =>
              failure.course.term == material.course.term &&
              failure.candidate.moodleCourseId ==
                  material.candidate.moodleCourseId &&
              failure.candidate.sourceId == material.candidate.sourceId,
        )) {
          failures.add(material);
          if (mounted) setState(() => _materialBatchFailed++);
        }
      }
    }
    if (!mounted) return;
    setState(() {
      _materialBatchRunning = false;
      _materialBatchFailures = failures;
    });
    if (_materialFileCache is! BackgroundMaterialDownloadQueue) {
      await _loadCachedMaterials();
    }
  }

  Future<void> _openCachedMaterial(CachedMaterialFile file) async {
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheOpen,
        action: () => _materialFileCache.open(file.id),
      );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Não foi possível abrir a cópia offline.'),
          ),
        );
      }
    }
  }

  Future<void> _retryFailedMaterial(MaterialDownloadProgress progress) async {
    _logInteraction('moodle_material_retry');
    final discovery = _contentDiscovery;
    if (discovery == null) return;
    PythonMoodleCourseContent? matchedCourse;
    PythonMoodleContentCandidate? matchedCandidate;
    for (final course in discovery.courses) {
      for (final candidate in course.candidates) {
        final prefix =
            '${course.term}/${candidate.moodleCourseId}/${candidate.sourceId}/';
        if (progress.id.startsWith(prefix)) {
          matchedCourse = course;
          matchedCandidate = candidate;
          break;
        }
      }
      if (matchedCandidate != null) break;
    }
    if (matchedCourse == null || matchedCandidate == null) return;
    try {
      _materialDownloadsScheduled.remove(progress.id);
      final files = await widget.gateway.listMoodleMaterialFiles(
        term: matchedCourse.term,
        courseId: matchedCandidate.moodleCourseId,
        sourceId: matchedCandidate.sourceId,
      );
      final fileName = progress.id.split('/').skip(3).join('/');
      final file = files.where((item) => item.name == fileName).firstOrNull;
      if (file == null) throw StateError('moodle_material_file_missing');
      await _saveMaterialOffline(
        matchedCourse,
        matchedCandidate,
        file,
        announce: false,
      );
      unawaited(_loadMaterialDownloadProgress(pollAgain: true));
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Não foi possível repetir o download.')),
        );
      }
    }
  }

  Future<void> _dismissFailedMaterial(MaterialDownloadProgress progress) async {
    _logInteraction('moodle_material_download_failure_dismiss');
    if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
      try {
        await queue.dismissDownload(progress.id);
        _materialDownloadsScheduled.remove(progress.id);
        _reportedMaterialDownloadFailures.remove(progress.id);
        if (mounted) {
          setState(
            () => _materialDownloadProgress = _materialDownloadProgress
                .where((download) => download.id != progress.id)
                .toList(),
          );
        }
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Não foi possível remover a falha.')),
          );
        }
      }
    }
  }

  Future<void> _removeCachedMaterial(CachedMaterialFile file) async {
    _logInteraction('moodle_material_remove');
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheRemove,
        action: () => _materialFileCache.remove(file.id),
      );
      _materialDownloadsScheduled.remove(file.id);
      await _loadCachedMaterials();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Não foi possível remover a cópia offline.'),
          ),
        );
      }
    }
  }

  Future<void> _clearCachedMaterials() async {
    _logInteraction('moodle_material_clear_prompt');
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remover todas as cópias?'),
        content: const Text(
          'Os arquivos deixarão de abrir offline e as falhas serão removidas da lista. '
          'Os originais permanecem no Moodle.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remover todas'),
          ),
        ],
      ),
    );
    _logInteraction(
      confirmed == true
          ? 'moodle_material_clear_confirm'
          : 'moodle_material_clear_cancel',
    );
    if (confirmed != true) return;
    try {
      if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
        final failures = _materialDownloadProgress
            .where((item) => item.state == MaterialDownloadState.failed)
            .toList();
        for (final download in failures) {
          await queue.dismissDownload(download.id);
        }
      }
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheClear,
        action: _materialFileCache.clear,
      );
      _materialDownloadsScheduled.clear();
      _reportedMaterialDownloadFailures.clear();
      if (mounted) setState(() => _materialDownloadProgress = const []);
      await _loadCachedMaterials();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Não foi possível limpar as cópias offline.'),
          ),
        );
      }
    }
  }

  Future<void> _connect() async {
    _logInteraction('ufmg_connect');
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
      TextInput.finishAutofillContext(shouldSave: true);
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
    _logInteraction('ufmg_disconnect_prompt');
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
    _logInteraction(
      confirmed == true ? 'ufmg_disconnect_confirm' : 'ufmg_disconnect_cancel',
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
    _logInteraction('ufmg_sync_siga');
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
    _logInteraction('ufmg_sync_moodle');
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
      try {
        await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleContentDiscovery,
          action: widget.gateway.discoverMoodleContent,
        );
      } catch (error) {
        if (!isTransientPythonBackendFailure(error)) rethrow;
        await widget.logger.logEvent(
          'moodle_content_discovery_retrying',
          parameters: const {
            'operation': 'moodle_content_discovery',
            'outcome': 'retrying',
          },
        );
        await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleContentDiscovery,
          action: widget.gateway.discoverMoodleContent,
        );
        await widget.logger.logEvent(
          'moodle_content_discovery_recovered',
          parameters: const {
            'operation': 'moodle_content_discovery',
            'outcome': 'recovered',
          },
        );
      }
      final discovery = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCatalogList,
        action: widget.gateway.listMoodleMaterialCatalog,
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
              child: _loading ? _loadingContent() : _content(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _loadingContent() => Column(
    mainAxisSize: MainAxisSize.min,
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Center(child: CircularProgressIndicator()),
      const SizedBox(height: 12),
      const Text(
        'Conferindo a conexão com a UFMG…',
        textAlign: TextAlign.center,
      ),
      if (_materialFileCache.isAvailable) ...[
        const SizedBox(height: 20),
        MaterialCacheCard(
          files: _cachedMaterials,
          downloads: _materialDownloadProgress,
          onOpen: _openCachedMaterial,
          onRemove: _removeCachedMaterial,
          onRetry: _retryFailedMaterial,
          onDismiss: _dismissFailedMaterial,
          onClear: _clearCachedMaterials,
        ),
      ],
    ],
  );

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
        if (_materialFileCache.isAvailable) ...[
          const SizedBox(height: 16),
          MaterialCacheCard(
            files: _cachedMaterials,
            downloads: _materialDownloadProgress,
            onOpen: _openCachedMaterial,
            onRemove: _removeCachedMaterial,
            onRetry: _retryFailedMaterial,
            onDismiss: _dismissFailedMaterial,
            onClear: _clearCachedMaterials,
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
            'Arquivos são baixados diretamente da UFMG sem ocupar espaço no '
            'nosso servidor. Páginas interativas continuam abrindo no Moodle.',
          ),
          const SizedBox(height: 8),
          if (_materialFileCache.isAvailable &&
              _downloadableMaterials(_contentDiscovery!.courses).isNotEmpty)
            OutlinedButton.icon(
              key: const Key('moodle-download-all'),
              onPressed: _materialBatchRunning
                  ? null
                  : () => _confirmMaterialBatch(
                      'Baixar todos os materiais?',
                      _downloadableMaterials(_contentDiscovery!.courses),
                    ),
              icon: const Icon(Icons.download_for_offline_outlined),
              label: const Text('Baixar tudo'),
            ),
          if (_materialBatchTotal > 0) ...[
            const SizedBox(height: 8),
            Semantics(
              liveRegion: true,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  LinearProgressIndicator(
                    value: _materialBatchTotal == 0
                        ? null
                        : _materialBatchCompleted / _materialBatchTotal,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _materialBatchRunning
                        ? '$_materialBatchCompleted de $_materialBatchTotal materiais processados'
                        : '${_materialBatchCompleted - _materialBatchFailed} de $_materialBatchTotal materiais preparados',
                  ),
                  if (!_materialBatchRunning &&
                      _materialBatchFailures.isNotEmpty)
                    TextButton.icon(
                      key: const Key('moodle-download-retry-failed'),
                      onPressed: () {
                        _logInteraction('moodle_material_batch_retry');
                        _downloadMaterialBatch(List.of(_materialBatchFailures));
                      },
                      icon: const Icon(Icons.refresh),
                      label: Text(
                        'Tentar novamente (${_materialBatchFailures.length})',
                      ),
                    ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 8),
          for (final course in _contentDiscovery!.courses)
            Card(
              child: ExpansionTile(
                key: Key('moodle-content-${course.courseId}'),
                onExpansionChanged: (expanded) => _logInteraction(
                  expanded ? 'moodle_course_expand' : 'moodle_course_collapse',
                ),
                title: Text(course.courseCode),
                subtitle: Text(_contentStatus(course)),
                children: [
                  if (_materialFileCache.isAvailable &&
                      _downloadableMaterials([course]).isNotEmpty)
                    Align(
                      alignment: Alignment.centerRight,
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 0, 8, 4),
                        child: TextButton.icon(
                          key: Key('moodle-download-all-${course.courseId}'),
                          onPressed: _materialBatchRunning
                              ? null
                              : () => _confirmMaterialBatch(
                                  'Baixar todos de ${course.courseCode}?',
                                  _downloadableMaterials([course]),
                                ),
                          icon: const Icon(Icons.download_for_offline_outlined),
                          label: const Text('Baixar tudo'),
                        ),
                      ),
                    ),
                  for (final candidate in course.candidates)
                    ListTile(
                      leading: Icon(_contentIcon(candidate.kind)),
                      title: Text(candidate.title),
                      subtitle: Text(_candidateLabel(candidate)),
                      trailing: candidate.canOpenDirectly
                          ? _materialDownloadsInFlight.contains(
                                  _materialOperationId(course, candidate),
                                )
                                ? const SizedBox.square(
                                    dimension: 24,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : IconButton(
                                    key: Key(
                                      'moodle-material-open-${candidate.sourceId}',
                                    ),
                                    tooltip: candidate.kind == 'file'
                                        ? 'Baixar'
                                        : 'Abrir no Moodle',
                                    onPressed: () =>
                                        _openMoodleMaterial(course, candidate),
                                    icon: Icon(
                                      candidate.kind == 'file'
                                          ? Icons.download_outlined
                                          : Icons.open_in_new,
                                    ),
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
            onExpansionChanged: (expanded) => _logInteraction(
              expanded ? 'ufmg_manage_expand' : 'ufmg_manage_collapse',
            ),
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
                      : () {
                          _logInteraction('ufmg_reconnect_show');
                          setState(() => _showReconnectForm = true);
                        },
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
    return AutofillGroup(
      onDisposeAction: AutofillContextAction.cancel,
      child: Form(
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
              textInputAction: TextInputAction.done,
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
                    : () {
                        _logInteraction('ufmg_reconnect_cancel');
                        setState(() {
                          _showReconnectForm = false;
                          _username.clear();
                          _password.clear();
                        });
                      },
                child: const Text('Cancelar'),
              ),
            ],
          ],
        ),
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
