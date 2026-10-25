import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../backend/python_backend_transport.dart';
import '../../data/material_file_cache.dart';
import '../../data/material_file_cache_factory.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/app_feedback.dart';
import '../../design/course_identity.dart';
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
    this.materialCourseId,
    this.materialCourseCode,
    this.materialCourseTerm,
    this.onOpenCourses,
    this.onOpenCalendar,
    super.key,
  });

  final BackendUFMGSessionGateway gateway;
  final AppLogger logger;
  final String? userId;
  final UFMGSyncScheduleGateway? syncSchedule;
  final Future<bool> Function(Uri uri)? openExternalUri;
  final MaterialFileCache? materialFileCache;
  final String? materialCourseId;
  final String? materialCourseCode;
  final String? materialCourseTerm;
  final Future<void> Function()? onOpenCourses;
  final Future<void> Function()? onOpenCalendar;

  bool get isMaterialScope => materialCourseId != null;

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
  String? _sigaSummary;
  String? _moodleSummary;
  String? _sigaError;
  String? _moodleError;
  bool _sigaBusy = false;
  bool _moodleBusy = false;
  List<PythonMoodleDate> _dates = const [];
  PythonMoodleContentDiscovery? _contentDiscovery;
  late final MaterialFileCache _materialFileCache;
  late final bool _ownsMaterialFileCache;
  List<CachedMaterialFile> _cachedMaterials = const [];
  List<MaterialDownloadProgress> _materialDownloadProgress = const [];
  Timer? _materialProgressTimer;
  final Set<String> _materialDownloadsInFlight = {};
  final Set<String> _diarioProbesInFlight = {};
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
        final courses = widget.isMaterialScope
            ? catalog.courses.where(_matchesMaterialScope).toList()
            : catalog.courses;
        setState(
          () => _contentDiscovery = PythonMoodleContentDiscovery(
            courses: courses,
            candidateTotal: courses.fold(
              0,
              (total, course) => total + course.candidates.length,
            ),
            metaturmaCandidateTotal: courses.fold(
              0,
              (total, course) =>
                  total +
                  course.candidates
                      .where(
                        (item) =>
                            item.origin == PythonMoodleContentOrigin.metaturma,
                      )
                      .length,
            ),
          ),
        );
      }
    } catch (_) {
      // The persisted catalogue is supplementary and may be synced later.
    }
  }

  bool _matchesMaterialScope(PythonMoodleCourseContent course) =>
      course.courseId == widget.materialCourseId ||
      (course.courseCode.toUpperCase() ==
              widget.materialCourseCode?.toUpperCase() &&
          course.term == widget.materialCourseTerm);

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
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    } finally {
      _materialDownloadsInFlight.remove(operationId);
      if (mounted) setState(() {});
    }
  }

  bool _canProbeDiario(PythonMoodleContentCandidate candidate) =>
      candidate.kind == 'link' &&
      candidate.relevance == 'teaching_plan' &&
      widget.gateway is BackendDiarioPlanGateway;

  Future<void> _probeDiarioPlan(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
  ) async {
    _logInteraction('moodle_teaching_plan_import');
    final operationId = _materialOperationId(course, candidate);
    if (!_diarioProbesInFlight.add(operationId)) return;
    setState(() {});
    try {
      final imported = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleTeachingPlanImport,
        action: () => (widget.gateway as BackendDiarioPlanGateway)
            .importMoodleTeachingPlan(
              courseId: course.courseId,
              term: course.term,
              sourceId: candidate.sourceId,
            ),
      );
      if (!mounted) return;
      final reconciliation = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleTeachingPlanReconciliation,
        action: () => (widget.gateway as BackendDiarioPlanGateway)
            .reconcileMoodleTeachingPlan(
              courseId: course.courseId,
              apply: false,
            ),
      );
      if (!mounted) return;
      var applied = 0;
      if (reconciliation.changes.isNotEmpty) {
        final confirmed = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: Text('Aplicar alterações em ${course.courseCode}?'),
            content: SizedBox(
              width: 520,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '${reconciliation.matched} aulas já conferem com o plano. '
                      'Estas são as alterações que serão aplicadas:',
                    ),
                    if (reconciliation.workloadValidation case final workload?
                        when workload.status != 'aligned') ...[
                      const SizedBox(height: 12),
                      Text(
                        'O calendário resultante tem '
                        '${workload.actualLessonUnits} de '
                        '${workload.expectedLessonUnits} '
                        'horas-aula de 50 minutos '
                        '(${workload.activeEncounters} de '
                        '${workload.expectedTypicalMeetings} '
                        'encontros de 2 aulas como referência). '
                        'A carga apenas sinaliza a divergência; nenhuma aula será '
                        'criada ou removida para completar esse número.',
                      ),
                    ],
                    const SizedBox(height: 12),
                    for (final change in reconciliation.changes)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              change.action == 'remove_session'
                                  ? Icons.remove_circle_outline
                                  : Icons.add_circle_outline,
                              size: 20,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                '${change.action == 'remove_session'
                                    ? 'Remover aula'
                                    : change.action == 'link_assessment'
                                    ? 'Vincular avaliação'
                                    : 'Adicionar aula'}\n'
                                '${MaterialLocalizations.of(context).formatMediumDate(change.date)} '
                                '• ${change.startsAt}–${change.endsAt}\n'
                                '${change.subject}',
                              ),
                            ),
                          ],
                        ),
                      ),
                    if (reconciliation.conflicting > 0)
                      Text(
                        '${reconciliation.conflicting} conflitos não serão alterados automaticamente.',
                      ),
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                key: const Key('teaching-plan-reconciliation-cancel'),
                onPressed: () => Navigator.pop(context, false),
                child: const Text('Agora não'),
              ),
              FilledButton(
                key: const Key('teaching-plan-reconciliation-apply'),
                onPressed: () => Navigator.pop(context, true),
                child: const Text('Aplicar atualizações'),
              ),
            ],
          ),
        );
        if (confirmed == true) {
          final result = await runAuditedOperation(
            logger: widget.logger,
            operation: AuditedOperation.moodleTeachingPlanReconciliation,
            action: () => (widget.gateway as BackendDiarioPlanGateway)
                .reconcileMoodleTeachingPlan(
                  courseId: course.courseId,
                  apply: true,
                ),
          );
          applied = result.applied;
        }
      } else if (_hasTeachingPlanNotice(reconciliation)) {
        _logInteraction('moodle_teaching_plan_review_notice_shown');
        await showDialog<void>(
          context: context,
          builder: (context) => AlertDialog(
            key: const Key('teaching-plan-no-change-notice'),
            title: const Text('Plano importado sem alterações automáticas'),
            content: Text(_teachingPlanNotice(reconciliation)),
            actions: [
              FilledButton(
                key: const Key('teaching-plan-no-change-notice-close'),
                onPressed: () {
                  _logInteraction(
                    'moodle_teaching_plan_review_notice_acknowledged',
                  );
                  Navigator.pop(context);
                },
                child: const Text('Entendi'),
              ),
            ],
          ),
        );
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Plano importado: ${imported.assessmentTotal} avaliações, '
            '${imported.scheduleTotal} aulas e ${imported.criteriaTotal} critérios.'
            '${imported.undatedAssessmentTotal == 0 ? '' : ' '
                      '${imported.undatedAssessmentTotal} avaliações ainda estão sem data.'}'
            '${applied == 0 ? '' : ' $applied atualizações aplicadas ao calendário.'}'
            '${reconciliation.conflicting == 0 ? '' : ' '
                      '${reconciliation.conflicting == 1 ? '1 conflito precisa' : '${reconciliation.conflicting} conflitos precisam'} de revisão.'}'
            '${reconciliation.outsideSchedule == 0 ? '' : ' '
                      '${reconciliation.outsideSchedule == 1 ? '1 item' : '${reconciliation.outsideSchedule} itens'} fora da grade ${reconciliation.outsideSchedule == 1 ? 'foi mantido' : 'foram mantidos'} fora da frequência.'}',
          ),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      final message = switch (error) {
        PythonBackendException(
          code: PythonBackendError.ufmgReauthenticationRequired,
        ) =>
          'Reconecte a UFMG para importar este plano.',
        _ => 'Não foi possível importar este plano de ensino.',
      };
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    } finally {
      _diarioProbesInFlight.remove(operationId);
      if (mounted) setState(() {});
    }
  }

  bool _hasTeachingPlanNotice(PythonTeachingPlanReconciliation reconciliation) {
    final hasOutsideSchedule = reconciliation.outsideSchedule > 0;
    final hasConflicts = reconciliation.conflicting > 0;
    final workloadStatus = reconciliation.workloadValidation?.status;
    final hasWorkloadDifference =
        workloadStatus != null && workloadStatus != 'aligned';
    return hasOutsideSchedule || hasConflicts || hasWorkloadDifference;
  }

  String _teachingPlanNotice(PythonTeachingPlanReconciliation reconciliation) {
    final details = <String>[];
    if (reconciliation.outsideSchedule > 0) {
      details.add(
        '${reconciliation.outsideSchedule} '
        '${reconciliation.outsideSchedule == 1 ? 'item está' : 'itens estão'} '
        'fora da grade e não '
        '${reconciliation.outsideSchedule == 1 ? 'virou' : 'viraram'} '
        'aula de frequência.',
      );
    }
    if (reconciliation.conflicting > 0) {
      details.add(
        '${reconciliation.conflicting} '
        '${reconciliation.conflicting == 1 ? 'conflito precisa' : 'conflitos precisam'} '
        'de revisão manual.',
      );
    }
    if (reconciliation.workloadValidation case final workload?
        when workload.status != 'aligned') {
      details.add(
        'O calendário soma ${workload.actualLessonUnits} de '
        '${workload.expectedLessonUnits} horas-aula previstas.',
      );
    }
    return '${reconciliation.matched} aulas já conferem com o plano. '
        'Nenhuma mudança foi aplicada automaticamente. ${details.join(' ')}';
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
        title: const AppDialogHeader(
          icon: Icons.delete_sweep_outlined,
          title: 'Remover todas as cópias?',
          subtitle: 'Os arquivos originais continuarão disponíveis no Moodle.',
          destructive: true,
        ),
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
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
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
        title: const AppDialogHeader(
          icon: Icons.link_off_outlined,
          title: 'Desconectar da UFMG?',
          subtitle: 'Seus registros pessoais não serão apagados.',
          destructive: true,
        ),
        content: const Text(
          'A sessão acadêmica salva será apagada. Seus registros de frequência permanecem intactos.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
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
      _sigaBusy = true;
      _error = null;
      _sigaError = null;
      _sigaSummary = null;
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
          _sigaSummary =
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
          _sigaError = _error;
        });
      } else {
        setState(() {
          _sigaError = _syncMessageFor(error);
        });
      }
    } finally {
      if (mounted) setState(() => _sigaBusy = false);
    }
  }

  Future<void> _syncAll() async {
    final gateway = widget.gateway;
    if (gateway is! BackendUnifiedAcademicSyncGateway) return;
    final unifiedGateway = gateway as BackendUnifiedAcademicSyncGateway;
    _logInteraction('ufmg_sync_all');
    setState(() {
      _sigaBusy = true;
      _moodleBusy = true;
      _error = null;
      _sigaError = null;
      _sigaSummary = null;
    });
    try {
      final result = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.academicSync,
        action: unifiedGateway.syncAllAcademicData,
      );
      final supplementary = await Future.wait<Object>([
        widget.gateway.listMoodleDates(),
        widget.gateway.listMoodleMaterialCatalog(),
      ]);
      final userId = widget.userId;
      final schedule = widget.syncSchedule;
      if (userId != null && schedule != null) {
        await schedule.record(userId, result.siga.nextAutomaticSyncAt);
      }
      if (!mounted) return;
      setState(() {
        _dates = supplementary[0] as List<PythonMoodleDate>;
        _contentDiscovery = supplementary[1] as PythonMoodleContentDiscovery;
        _sigaSummary =
            '${result.siga.courses.created} ${_plural(result.siga.courses.created, 'disciplina importada', 'disciplinas importadas')}. '
            '${result.siga.schedules.updated} ${_plural(result.siga.schedules.updated, 'grade atualizada', 'grades atualizadas')}. '
            '${result.moodle.dates.created} ${_plural(result.moodle.dates.created, 'data importada', 'datas importadas')}. '
            '${result.teachingPlans.applied} ${_plural(result.teachingPlans.applied, 'alteração de plano aplicada', 'alterações de plano aplicadas')}. '
            '${result.teachingPlans.reviewRequired} ${_plural(result.teachingPlans.reviewRequired, 'exceção para revisar', 'exceções para revisar')}.';
        _sigaBusy = false;
        _moodleBusy = false;
      });
      if (result.exceptions.isNotEmpty) {
        await _showAcademicSyncExceptions(result.exceptions);
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
          _sigaError = _error;
        });
      } else {
        setState(() => _sigaError = _syncMessageFor(error));
      }
    } finally {
      if (mounted) {
        setState(() {
          _sigaBusy = false;
          _moodleBusy = false;
        });
      }
    }
  }

  Future<void> _showAcademicSyncExceptions(
    List<PythonAcademicSyncException> exceptions,
  ) => showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('Revisão necessária'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'A sincronização automática terminou. Estas exceções não foram aplicadas:',
              ),
              const SizedBox(height: 12),
              for (final exception in exceptions) ...[
                Text(
                  exception.courseCode,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(
                  exception.reason == 'ambiguous_teaching_plan'
                      ? '${exception.candidateCount} planos de ensino possíveis.'
                      : exception.reason == 'teaching_plan_unavailable'
                      ? 'O plano não pôde ser processado; as outras disciplinas continuaram normalmente.'
                      : '${exception.conflicting + exception.assessmentConflicts} conflito(s) com dados existentes.',
                ),
                for (final change in exception.changes)
                  Text(
                    '${change.date.day.toString().padLeft(2, '0')}/'
                    '${change.date.month.toString().padLeft(2, '0')} · '
                    '${change.startsAt} · ${change.subject}',
                  ),
                const SizedBox(height: 12),
              ],
            ],
          ),
        ),
      ),
      actions: [
        FilledButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Entendi'),
        ),
      ],
    ),
  );

  Future<void> _syncMoodle() async {
    _logInteraction('ufmg_sync_moodle');
    setState(() {
      _moodleBusy = true;
      _error = null;
      _moodleError = null;
      _moodleSummary = null;
    });
    try {
      late PythonMoodleSyncResult sync;
      try {
        sync = await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleSync,
          action: widget.gateway.syncMoodle,
        );
      } catch (error) {
        if (!isTransientPythonBackendFailure(error)) rethrow;
        await widget.logger.logEvent(
          'moodle_sync_retrying',
          parameters: const {'operation': 'moodle_sync', 'outcome': 'retrying'},
        );
        sync = await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.moodleSync,
          action: widget.gateway.syncMoodle,
        );
        await widget.logger.logEvent(
          'moodle_sync_recovered',
          parameters: const {
            'operation': 'moodle_sync',
            'outcome': 'recovered',
          },
        );
      }
      final discovery = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCatalogList,
        action: widget.gateway.listMoodleMaterialCatalog,
      );
      final capabilities = sync.capabilities;
      final capabilitySummary = capabilities == null
          ? ' Não foi possível validar o download direto agora.'
          : capabilities.directDownloadSupported
          ? ' Download direto disponível.'
          : ' Download direto ainda não disponível.';
      final dates = await _listDates();
      if (mounted) {
        setState(() {
          _dates = dates;
          _contentDiscovery = discovery;
          _moodleSummary =
              '${sync.dates.created} ${_plural(sync.dates.created, 'data do Moodle importada', 'datas do Moodle importadas')}. '
              '${sync.dates.updated} ${_plural(sync.dates.updated, 'data atualizada', 'datas atualizadas')}. '
              '${sync.dates.unchanged} sem alteração. '
              '${sync.dates.unmatched} ${_plural(sync.dates.unmatched, 'data não pôde ser ligada a uma disciplina', 'datas não puderam ser ligadas a uma disciplina')}. '
              '${sync.candidateTotal} ${_plural(sync.candidateTotal, 'material candidato encontrado', 'materiais candidatos encontrados')}.'
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
          _moodleError = _error;
        });
      } else {
        setState(() {
          _moodleError = _moodleSyncMessageFor(error);
        });
      }
    } finally {
      if (mounted) setState(() => _moodleBusy = false);
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
      appBar: AppBar(
        title: Text(
          widget.isMaterialScope
              ? 'Materiais • ${widget.materialCourseCode}'
              : 'Conta acadêmica UFMG',
        ),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: widget.isMaterialScope ? 720 : 920,
              ),
              child: _loading
                  ? _loadingContent()
                  : widget.isMaterialScope
                  ? _scopedMaterialContent()
                  : _content(),
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
      Text(
        widget.isMaterialScope
            ? 'Carregando materiais…'
            : 'Conferindo a conexão com a UFMG…',
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

  Widget _scopedMaterialContent() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Row(
        key: const Key('material-scope-header'),
        children: [
          CourseMark(
            key: const Key('material-course-mark'),
            code: widget.materialCourseCode!,
            size: 52,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.materialCourseCode!,
                  style: Theme.of(context).textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                Text(
                  'Materiais do Moodle',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
      const SizedBox(height: 16),
      const Text(
        'Os arquivos são baixados diretamente da UFMG para este dispositivo, '
        'sem ocupar espaço no nosso servidor.',
      ),
      if (_contentDiscovery?.courses.isEmpty ?? true) ...[
        const SizedBox(height: 24),
        const Card(
          child: ListTile(
            leading: Icon(Icons.folder_off_outlined),
            title: Text('Nenhum material sincronizado'),
            subtitle: Text(
              'Sincronize o Moodle pela conta para atualizar o catálogo.',
            ),
          ),
        ),
      ] else
        ..._materialSections(includeHeading: false),
    ],
  );

  Widget _content() {
    final status = _status;
    final connected = status?.connected ?? false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _accountOverview(status, connected),
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
          _academicAgenda(),
        ],
        if (_contentDiscovery != null) ..._materialSections(),
      ],
    );
  }

  Widget _academicAgenda() => Card(
    key: const Key('ufmg-academic-agenda'),
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ListTile(
            leading: const Icon(Icons.calendar_month_outlined),
            title: Text(
              'Agenda do Moodle',
              style: Theme.of(context).textTheme.titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            subtitle: const Text('Avaliações e entregas encontradas'),
          ),
          for (final date in _dates)
            ListTile(
              leading: Icon(_dateIcon(date.kind)),
              title: Text(date.title),
              subtitle: Text(
                '${date.courseCode} • ${_formattedDate(date.dueAt)}',
              ),
            ),
        ],
      ),
    ),
  );

  Widget _accountOverview(
    PythonUFMGSessionStatus? status,
    bool connected,
  ) => Card(
    key: const Key('ufmg-account-overview'),
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 48,
            height: 48,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: connected
                  ? Theme.of(context).colorScheme.primaryContainer
                        .withValues(alpha: .65)
                  : Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Icon(
              connected
                  ? Icons.verified_user_outlined
                  : Icons.account_balance_outlined,
              color: connected
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  connected
                      ? 'UFMG conectada'
                      : status?.reauthenticationRequired == true
                      ? 'Sua sessão expirou'
                      : 'Conectar à UFMG',
                  style: Theme.of(context).textTheme.titleLarge
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 4),
                Text(
                  connected
                      ? 'Suas fontes acadêmicas estão prontas para sincronizar.'
                      : 'Sua senha não é armazenada; ela é usada somente para conectar.',
                ),
                if (connected && status?.expiresAt != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    'Sessão válida até ${_formattedExpiry(status!.expiresAt!)}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    ),
  );

  List<Widget> _materialSections({bool includeHeading = true}) => [
    if (includeHeading) ...[
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
    ],
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
            if (!_materialBatchRunning && _materialBatchFailures.isNotEmpty)
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
          leading: CourseMark(
            key: Key('moodle-course-mark-${course.courseId}'),
            code: course.courseCode,
            size: 40,
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
                trailing: _canProbeDiario(candidate)
                    ? _diarioProbesInFlight.contains(
                            _materialOperationId(course, candidate),
                          )
                          ? const SizedBox.square(
                              dimension: 24,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : IconButton(
                              key: Key(
                                'moodle-diario-probe-${candidate.sourceId}',
                              ),
                              tooltip: 'Validar plano estruturado',
                              onPressed: () =>
                                  _probeDiarioPlan(course, candidate),
                              icon: const Icon(Icons.fact_check_outlined),
                            )
                    : candidate.canOpenDirectly
                    ? _materialDownloadsInFlight.contains(
                            _materialOperationId(course, candidate),
                          )
                          ? const SizedBox.square(
                              dimension: 24,
                              child: CircularProgressIndicator(strokeWidth: 2),
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
  ];

  Widget _syncActions() {
    if (widget.gateway is BackendUnifiedAcademicSyncGateway) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'Dados acadêmicos',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          _academicSourceCard(
            key: const Key('ufmg-source-all'),
            icon: Icons.sync_outlined,
            title: 'UFMG e Moodle',
            description: 'Disciplinas, horários, datas e planos de ensino',
            actionKey: const Key('ufmg-sync-all'),
            actionLabel: 'Sincronizar tudo',
            busy: _sigaBusy || _moodleBusy,
            onSync: _syncAll,
            errorKey: const Key('ufmg-source-all-error'),
            error: _sigaError,
            summary: _sigaSummary,
            resultActionKey: const Key('ufmg-open-calendar'),
            resultActionLabel: 'Ver calendário',
            onOpenResult: widget.onOpenCalendar == null
                ? null
                : () async {
                    _logInteraction('ufmg_open_calendar');
                    await widget.onOpenCalendar!();
                  },
          ),
          const SizedBox(height: 12),
          _connectionManagementCard(),
        ],
      );
    }
    final sources = [
      _academicSourceCard(
        key: const Key('ufmg-source-siga'),
        icon: Icons.school_outlined,
        title: 'SIGA',
        description: 'Disciplinas e horários',
        actionKey: const Key('ufmg-sync-siga'),
        actionLabel: 'Sincronizar SIGA',
        busy: _sigaBusy,
        onSync: _syncSiga,
        errorKey: const Key('ufmg-source-siga-error'),
        error: _sigaError,
        summary: _sigaSummary,
        resultActionKey: const Key('ufmg-open-courses'),
        resultActionLabel: 'Ver disciplinas',
        onOpenResult: widget.onOpenCourses == null
            ? null
            : () async {
                _logInteraction('ufmg_open_courses');
                await widget.onOpenCourses!();
              },
      ),
      _academicSourceCard(
        key: const Key('ufmg-source-moodle'),
        icon: Icons.menu_book_outlined,
        title: 'Moodle',
        description: 'Datas, planos de ensino e cronogramas',
        actionKey: const Key('ufmg-sync-moodle'),
        actionLabel: 'Sincronizar Moodle',
        busy: _moodleBusy,
        onSync: _syncMoodle,
        errorKey: const Key('ufmg-source-moodle-error'),
        error: _moodleError,
        summary: _moodleSummary,
        resultActionKey: const Key('ufmg-open-calendar'),
        resultActionLabel: 'Ver calendário',
        onOpenResult: widget.onOpenCalendar == null
            ? null
            : () async {
                _logInteraction('ufmg_open_calendar');
                await widget.onOpenCalendar!();
              },
      ),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Fontes acadêmicas',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        LayoutBuilder(
          builder: (context, constraints) {
            if (constraints.maxWidth < 700) {
              return Column(
                key: const Key('ufmg-sources-grid'),
                children: [sources[0], const SizedBox(height: 12), sources[1]],
              );
            }
            final width = (constraints.maxWidth - 12) / 2;
            return Wrap(
              key: const Key('ufmg-sources-grid'),
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final source in sources)
                  SizedBox(width: width, child: source),
              ],
            );
          },
        ),
        const SizedBox(height: 12),
        _connectionManagementCard(),
      ],
    );
  }

  Widget _connectionManagementCard() => Card(
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
        const ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Icon(Icons.shield_outlined),
          title: Text('Seus dados manuais são preservados'),
          subtitle: Text(
            'Sincronizações complementam seus registros. Sua senha não '
            'é armazenada e os arquivos vêm direto da UFMG.',
          ),
        ),
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
  );

  Widget _academicSourceCard({
    required Key key,
    required IconData icon,
    required String title,
    required String description,
    required Key actionKey,
    required String actionLabel,
    required bool busy,
    required Future<void> Function() onSync,
    required Key errorKey,
    required String? error,
    required String? summary,
    required Key resultActionKey,
    required String resultActionLabel,
    required Future<void> Function()? onOpenResult,
  }) => Card(
    key: key,
    margin: EdgeInsets.zero,
    child: LayoutBuilder(
      builder: (context, constraints) {
        final action = FilledButton.tonalIcon(
          key: actionKey,
          onPressed: busy || _busy ? null : onSync,
          icon: busy
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.sync),
          label: Text(busy ? 'Atualizando…' : actionLabel),
        );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ListTile(
              leading: Icon(icon),
              title: Text(title),
              subtitle: Text(description),
              trailing: constraints.maxWidth >= 420 ? action : null,
            ),
            if (constraints.maxWidth < 420)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: action,
              ),
            if (error != null)
              Semantics(
                liveRegion: true,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: Text(
                    error,
                    key: errorKey,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              ),
            if (summary != null) ...[
              Semantics(
                liveRegion: true,
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Text(summary),
                ),
              ),
              const SizedBox(height: 4),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: Text(
                  'Dados já cadastrados, correções manuais e registros de '
                  'frequência foram preservados.',
                ),
              ),
              if (onOpenResult != null)
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    key: resultActionKey,
                    onPressed: onOpenResult,
                    icon: const Icon(Icons.arrow_forward),
                    label: Text(resultActionLabel),
                  ),
                )
              else
                const SizedBox(height: 12),
            ],
          ],
        );
      },
    ),
  );

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
    'link' => Icons.link_outlined,
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
