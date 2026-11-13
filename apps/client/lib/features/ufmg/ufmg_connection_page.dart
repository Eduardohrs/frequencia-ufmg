import 'academic_sync_feedback.dart';
import 'schedule_pendency_review_dialog.dart';
import '../../design/course_visuals.dart';
import '../../data/material_scope_cache.dart';
import '../../observability/operation_diagnostics.dart';
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../backend/python_backend_transport.dart';
import '../../data/material_file_cache.dart';
import '../../data/material_download_failure.dart';
import '../../data/material_preparation_failure_cache.dart';
import '../../observability/error_log_details.dart';
import '../../data/material_file_cache_factory.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/app_feedback.dart';
import '../../design/course_identity.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import 'material_cache_card.dart';
import 'academic_sync_controller.dart';

enum UFMGView { account, materials, savedFiles }

class UFMGConnectionPage extends StatefulWidget {
  const UFMGConnectionPage({
    required this.gateway,
    required this.logger,
    this.userId,
    this.syncSchedule,
    this.academicSync,
    this.openExternalUri,
    this.materialFileCache,
    this.materialCourseId,
    this.view = UFMGView.account,
    this.materialScopeCache,
    this.materialCourseCode,
    this.materialCourseName,
    this.materialCourseTerm,
    this.onOpenCourses,
    this.onOpenCalendar,
    this.onConnected,
    super.key,
  }) : assert(view != UFMGView.savedFiles || materialCourseId == null);

  final BackendUFMGSessionGateway gateway;
  final AppLogger logger;
  final String? userId;
  final UFMGSyncScheduleGateway? syncSchedule;
  final AcademicSyncController? academicSync;
  final Future<bool> Function(Uri uri)? openExternalUri;
  final MaterialFileCache? materialFileCache;
  final String? materialCourseId;
  final UFMGView view;
  bool get savedFilesOnly => view == UFMGView.savedFiles;
  bool get isMaterialView => isMaterialScope || view == UFMGView.materials;
  final MaterialScopeCache? materialScopeCache;
  final String? materialCourseCode;
  final String? materialCourseName;
  final String? materialCourseTerm;
  final Future<void> Function()? onOpenCourses;
  final Future<void> Function()? onOpenCalendar;
  final VoidCallback? onConnected;

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
  bool _forceSync = false;
  bool _reviewingSyncResult = false;
  bool _showReconnectForm = false;
  String? _error;
  String? _sigaSummary;
  PythonUnifiedAcademicSyncResult? _lastSyncResult;
  String? _moodleSummary;
  PythonMoodleDateImportResult? _dateImportResult;
  String? _sigaError;
  String? _moodleError;
  bool _sigaBusy = false;
  bool _moodleBusy = false;
  PythonMoodleContentDiscovery? _contentDiscovery;
  late final MaterialFileCache _materialFileCache;
  late final bool _ownsMaterialFileCache;
  List<CachedMaterialFile> _cachedMaterials = const [];
  Set<String> _materialPrefixes = {};
  bool _materialCatalogFailed = false;
  bool _cacheReadFailed = false;
  late final _scopeCache = widget.materialScopeCache ?? MaterialScopeCache();
  bool _ownsScopedFile(String id) => _materialPrefixes.any(id.startsWith);
  List<CachedMaterialFile> get _visibleFiles => widget.isMaterialScope
      ? _cachedMaterials.where((file) => _ownsScopedFile(file.id)).toList()
      : _cachedMaterials;
  List<MaterialDownloadProgress> get _visibleDownloads {
    final all = <MaterialDownloadProgress>[
      ..._materialDownloadProgress,
      for (final failure in _preparationFailures)
        MaterialDownloadProgress(
          id: failure.materialId,
          name: failure.materialName,
          state: MaterialDownloadState.failed,
          downloaded: 0,
          total: 0,
          failureCode: failure.code.isEmpty ? 'prepare_failed' : failure.code,
          stage: 'prepare',
        ),
    ];
    return widget.isMaterialScope
        ? all.where((file) => _ownsScopedFile(file.id)).toList()
        : all;
  }

  Future<void> _readMaterialScope() async {
    if (!widget.isMaterialScope || widget.userId == null) return;
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('material_scope_read'),
      'course_id': widget.materialCourseId!,
      'stage': 'scope_cache_read',
    };
    try {
      _materialPrefixes = await _scopeCache.read(
        widget.userId!,
        widget.materialCourseId!,
      );
      emitOperationalEvent(widget.logger, 'material_scope_read_succeeded', {
        ...fields,
        'prefix_count': _materialPrefixes.length,
        'duration_ms': watch.elapsedMilliseconds,
      });
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'material_scope_read',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        failureCode: 'material_scope_cache_failed',
      );
    }
  }

  Future<void> _saveMaterialScope(
    List<PythonMoodleCourseContent> courses,
  ) async {
    if (!widget.isMaterialScope) return;
    final prefixes = {
      for (final course in courses)
        for (final item in course.candidates)
          '${course.term}/${item.moodleCourseId}/',
    };
    _materialPrefixes = {..._materialPrefixes, ...prefixes};
    if (widget.userId == null) return;
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('material_scope_write'),
      'course_id': widget.materialCourseId!,
      'stage': 'scope_cache_write',
    };
    try {
      await _scopeCache.write(
        widget.userId!,
        widget.materialCourseId!,
        _materialPrefixes,
      );
      emitOperationalEvent(widget.logger, 'material_scope_write_succeeded', {
        ...fields,
        'prefix_count': _materialPrefixes.length,
        'duration_ms': watch.elapsedMilliseconds,
      });
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'material_scope_write',
        {...fields, 'duration_ms': watch.elapsedMilliseconds},
        failureCode: 'material_scope_cache_failed',
      );
    }
  }

  List<MaterialDownloadProgress> _materialDownloadProgress = const [];
  List<MaterialPreparationFailureRecord> _preparationFailures = const [];
  late final MaterialPreparationFailureCache _preparationCache =
      MaterialPreparationFailureCache();
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
    widget.academicSync?.addListener(_onAcademicSyncChanged);
    _ownsMaterialFileCache = widget.materialFileCache == null;
    _materialFileCache =
        widget.materialFileCache ?? createMaterialFileCache(widget.userId);
    _load();
  }

  @override
  void dispose() {
    widget.academicSync?.removeListener(_onAcademicSyncChanged);
    _username.dispose();
    _password.dispose();
    _materialProgressTimer?.cancel();
    if (_ownsMaterialFileCache) _materialFileCache.dispose();
    super.dispose();
  }

  void _onAcademicSyncChanged() => setState(() {});

  Future<void> _load() async {
    await _readMaterialScope();
    if (!mounted) return;
    if (widget.savedFilesOnly || widget.isMaterialView) {
      await _loadSupplementaryData();
      if (mounted) setState(() => _loading = false);
      return;
    }
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
    if (widget.isMaterialView) _loadMaterialCatalog(),
    if (widget.isMaterialView || widget.savedFilesOnly) _loadCachedMaterials(),
    if (widget.isMaterialView || widget.savedFilesOnly)
      _loadMaterialDownloadProgress(),
    if (widget.userId != null) _loadPreparationFailures(),
  ]);

  Future<void> _loadPreparationFailures() async {
    final user = widget.userId;
    if (user == null) return;
    try {
      final records = await _preparationCache.read(user);
      if (mounted) setState(() => _preparationFailures = records);
    } catch (_) {
      // A central de falhas é suplementar; a fila nativa continua visível.
    }
  }

  Future<void> _recordPreparationFailure(
    PythonMoodleCourseContent course,
    PythonMoodleContentCandidate candidate,
    Object error,
  ) async {
    final user = widget.userId;
    if (user == null) return;
    final materialId = _materialOperationId(course, candidate);
    final details = ErrorLogDetails.from(error);
    final record = MaterialPreparationFailureRecord(
      materialId: materialId,
      materialName: candidate.title,
      term: course.term,
      moodleCourseId: candidate.moodleCourseId,
      sourceId: candidate.sourceId,
      courseCode: course.courseCode,
      code: details.code ?? details.type,
      at: DateTime.now().toUtc().toIso8601String(),
    );
    final next = [
      ..._preparationFailures.where((item) => item.materialId != materialId),
      record,
    ];
    try {
      await _preparationCache.record(user, record);
    } catch (_) {
      // Sem persistência, a falha segue visível apenas nesta sessão.
    }
    if (mounted) setState(() => _preparationFailures = next);
    unawaited(
      widget.logger
          .logEvent(
            'moodle_material_preparation_failed',
            parameters: {
              'failure_code': record.code,
              'stage': 'prepare',
              'course_code': course.courseCode,
            },
          )
          .catchError((_) {}),
    );
  }

  Future<void> _clearPreparationFailure(String materialId) async {
    final user = widget.userId;
    if (user != null) {
      try {
        await _preparationCache.remove(user, materialId);
      } catch (_) {}
    }
    if (mounted) {
      setState(
        () => _preparationFailures = _preparationFailures
            .where((item) => item.materialId != materialId)
            .toList(),
      );
    }
  }

  String _materialOpenErrorMessage(Object error, String name) {
    if (error is PythonBackendException) {
      if (error.code == PythonBackendError.moodleAuthorizationRequired ||
          error.code == PythonBackendError.ufmgReauthenticationRequired) {
        return 'Sincronize o Moodle novamente para baixar "$name".';
      }
      if (error.code == PythonBackendError.unavailable ||
          error.code == PythonBackendError.timeout ||
          error.code == PythonBackendError.ufmgUnavailable) {
        return 'Sem conexão com a UFMG para baixar "$name". '
            'Tente novamente quando estiver online.';
      }
    }
    return 'Não foi possível preparar "$name" para download.';
  }

  Future<void> _loadMaterialDownloadProgress({bool pollAgain = false}) async {
    if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
      try {
        final progress = await queue.listDownloads();
        if (!mounted) return;
        setState(() {
          _materialDownloadProgress = progress;
          _materialDownloadsScheduled.addAll(
            progress
                .where(
                  (download) =>
                      download.state == MaterialDownloadState.enqueued ||
                      download.state == MaterialDownloadState.running,
                )
                .map((download) => download.id),
          );
        });
        for (final download in progress) {
          if (download.state == MaterialDownloadState.failed &&
              _reportedMaterialDownloadFailures.add(download.failureKey)) {
            unawaited(
              widget.logger
                  .recordError(
                    MaterialDownloadFailure.fromProgress(download),
                    StackTrace.current,
                    context: 'moodle_material_native_download',
                  )
                  .catchError((_) {}),
            );
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
          _cacheReadFailed = false;
          _materialDownloadsScheduled.addAll(files.map((file) => file.id));
        });
      }
    } catch (_) {
      if (mounted) setState(() => _cacheReadFailed = true);
    }
  }

  Future<void> _loadMaterialCatalog() async {
    if (mounted) setState(() => _materialCatalogFailed = false);
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
        await _saveMaterialScope(courses);
        if (!mounted) return;
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
      if (mounted) setState(() => _materialCatalogFailed = true);
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
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_materialOpenErrorMessage(error, candidate.title)),
        ),
      );
      await _recordPreparationFailure(course, candidate, error);
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
      if (imported.notPublished) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('O plano de ensino ainda não foi publicado.'),
          ),
        );
        return;
      }
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
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('Download iniciado.')));
      }
      unawaited(
        _clearPreparationFailure(_materialOperationId(course, candidate)),
      );
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
    unawaited(
      _clearPreparationFailure(_materialOperationId(course, candidate)),
    );
    if (mounted && announce) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Arquivo baixado.')));
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
          '${materials.length} ${_plural(materials.length, 'material selecionado', 'materiais selecionados')}.',
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
    setState(() => _materialBatchRunning = true);
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialBatchPrepare,
        action: () async {
          if (_materialFileCache
              case final BackgroundMaterialPreparation preparation) {
            await preparation.prepareInBackground(
              () => _runMaterialBatch(materials),
              materialCount: materials.length,
            );
          } else {
            await _runMaterialBatch(materials);
          }
        },
      );
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _materialBatchRunning = false;
        _materialBatchTotal = materials.length;
        _materialBatchCompleted = materials.length;
        _materialBatchFailed = materials.length;
        _materialBatchFailures = materials;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Não foi possível iniciar a preparação em segundo plano. Tente novamente.',
          ),
        ),
      );
    }
  }

  Future<void> _runMaterialBatch(
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
          final files = await runAuditedOperation(
            logger: widget.logger,
            operation: AuditedOperation.moodleMaterialPrepare,
            action: () async {
              try {
                final files = await widget.gateway.listMoodleMaterialFiles(
                  term: material.course.term,
                  courseId: material.candidate.moodleCourseId,
                  sourceId: material.candidate.sourceId,
                );
                if (files.isEmpty) {
                  throw StateError('moodle_material_has_no_files');
                }
                return files;
              } catch (error, stackTrace) {
                Error.throwWithStackTrace(
                  MaterialPreparationFailure(
                    materialId: _materialOperationId(
                      material.course,
                      material.candidate,
                    ),
                    materialName: material.candidate.title,
                    courseCode: material.course.courseCode,
                    cause: error,
                  ),
                  stackTrace,
                );
              }
            },
          );
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
            '${course.term}/${candidate.moodleCourseId}/${candidate.sourceId}';
        if (progress.id == prefix || progress.id.startsWith('$prefix/')) {
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
      final file =
          files.where((item) => item.name == fileName).firstOrNull ??
          (fileName.isEmpty && files.isNotEmpty ? files.first : null);
      if (file == null) throw StateError('moodle_material_file_missing');
      await _saveMaterialOffline(
        matchedCourse,
        matchedCandidate,
        file,
        announce: false,
      );
      unawaited(_clearPreparationFailure(progress.id));
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
    if (progress.stage == 'prepare') {
      await _clearPreparationFailure(progress.id);
      return;
    }
    _logInteraction('moodle_material_download_failure_dismiss');
    if (_materialFileCache case final BackgroundMaterialDownloadQueue queue) {
      try {
        await queue.dismissDownload(progress.id);
        _materialDownloadsScheduled.remove(progress.id);
        _reportedMaterialDownloadFailures.remove(progress.failureKey);
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
          title: 'Remover as cópias listadas?',
          destructive: true,
        ),
        content: const Text(
          'As cópias offline e as falhas listadas serão removidas.',
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
        final failures = _visibleDownloads
            .where((item) => item.state == MaterialDownloadState.failed)
            .toList();
        for (final download in failures) {
          await queue.dismissDownload(download.id);
        }
      }
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.moodleMaterialCacheClear,
        action: () async {
          if (widget.isMaterialScope) {
            for (final file in _visibleFiles) {
              await _materialFileCache.remove(file.id);
            }
          } else {
            await _materialFileCache.clear();
          }
        },
      );
      if (widget.isMaterialScope) {
        _materialDownloadsScheduled.removeWhere(_ownsScopedFile);
        _reportedMaterialDownloadFailures.removeWhere(_ownsScopedFile);
        if (mounted) {
          setState(
            () => _materialDownloadProgress = _materialDownloadProgress
                .where(
                  (file) =>
                      !_ownsScopedFile(file.id) ||
                      file.state == MaterialDownloadState.enqueued ||
                      file.state == MaterialDownloadState.running,
                )
                .toList(),
          );
        }
      } else {
        _materialDownloadsScheduled.clear();
        _reportedMaterialDownloadFailures.clear();
        if (mounted) setState(() => _materialDownloadProgress = const []);
      }
      _materialDownloadsScheduled.addAll(
        _materialDownloadProgress
            .where(
              (file) =>
                  file.state == MaterialDownloadState.enqueued ||
                  file.state == MaterialDownloadState.running,
            )
            .map((file) => file.id),
      );
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
        if (status.connected) widget.onConnected?.call();
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
          destructive: true,
        ),
        content: const Text(
          'Você precisará entrar novamente para sincronizar.',
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
      logSyncFeedback(widget.logger, 'siga', sigaSyncDetails(result), const []);
      if (mounted) {
        setState(() {
          _sigaSummary =
              result.schedules.conflicts > 0 ||
                  result.schedules.missingCourses > 0
              ? 'Confira os horários de algumas disciplinas.'
              : null;
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
    var synchronized = false;
    try {
      final result = widget.academicSync != null
          ? await widget.academicSync!.start(force: _forceSync)
          : await runAuditedOperation(
              logger: widget.logger,
              operation: AuditedOperation.academicSync,
              action: unifiedGateway.syncAllAcademicData,
            );
      synchronized = true;
      await _presentAcademicSyncResult(result, review: false);
      if (widget.academicSync == null && mounted) {
        await _offerOfficialCalendar();
      }
    } catch (error, stack) {
      if (synchronized) {
        unawaited(
          widget.logger
              .recordError(
                error,
                stack,
                context: 'academic_sync_result_refresh',
              )
              .catchError((_) {}),
        );
        if (mounted) {
          setState(
            () => _sigaError =
                'A sincronização terminou, mas não foi possível atualizar o resumo. Abra o resultado novamente.',
          );
        }
        return;
      }
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

  Future<void> _presentAcademicSyncResult(
    PythonUnifiedAcademicSyncResult result, {
    bool review = true,
  }) async {
    _lastSyncResult = result;
    final userId = widget.userId;
    final schedule = widget.syncSchedule;
    if (userId != null && schedule != null) {
      await schedule.record(userId, result.siga.nextAutomaticSyncAt);
    }
    if (!mounted) return;
    final issues = unifiedSyncIssues(result);
    logSyncFeedback(
      widget.logger,
      'all',
      {
        ...sigaSyncDetails(result.siga),
        ...moodleSyncDetails(result.moodle),
        'plans_available': result.teachingPlans.available,
        'plans_imported': result.teachingPlans.imported,
        'plans_applied': result.teachingPlans.applied,
        'plans_unchanged': result.teachingPlans.unchanged,
        'plans_review_required': result.teachingPlans.reviewRequired,
        'plans_not_published': result.exceptions
            .where((e) => e.reason == 'teaching_plan_not_published')
            .length,
      },
      issues,
      operationId: widget.academicSync?.progress?.operationId,
    );
    setState(() {
      _dateImportResult = result.moodle.dates;
      _sigaSummary = _syncIssueSummary(issues);
      _sigaBusy = false;
      _moodleBusy = false;
    });
    if (!review) return;
    if (issues.isNotEmpty) {
      await _showAcademicSyncExceptions(issues);
    }
    await _offerOfficialCalendar();
  }

  Future<void> _reviewAcademicSyncResult(
    PythonUnifiedAcademicSyncResult result,
  ) async {
    if (_reviewingSyncResult) return;
    _logInteraction('ufmg_review_sync_result');
    setState(() => _reviewingSyncResult = true);
    try {
      await _presentAcademicSyncResult(result);
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'academic_sync_result_review')
            .catchError((_) {}),
      );
      if (mounted) {
        setState(
          () => _sigaError =
              'A sincronização terminou, mas não foi possível carregar a revisão. Tente abrir o resultado novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _reviewingSyncResult = false);
    }
  }

  String _syncCourseLabel(AcademicSyncIssue issue) =>
      CourseVisualHost.of(
        context,
      )?.course(id: issue.courseId, code: issue.courseCode)?.displayName ??
      (issue.courseCode.isEmpty ? 'Dados acadêmicos' : issue.courseCode);
  String _syncIssueMessage(AcademicSyncIssue issue) => switch (issue.reason) {
    'ambiguous_teaching_plan' => 'Escolha o plano de ensino na disciplina.',
    'schedule_review' => 'Confira os horários das disciplinas.',
    'unmatched_dates' => 'Algumas datas não têm uma disciplina correspondente.',
    _ => 'Não foi possível atualizar ${_syncCourseLabel(issue)}.',
  };
  String? _syncIssueSummary(List<AcademicSyncIssue> issues) {
    final messages = issues.map(_syncIssueMessage).toSet().toList();
    if (messages.isEmpty) return null;
    return messages.length == 1
        ? messages.single
        : '${messages.first} Mais ${messages.length - 1} ${messages.length == 2 ? 'pendência' : 'pendências'} para revisar.';
  }

  Future<void> _showAcademicSyncExceptions(
    List<AcademicSyncIssue> exceptions,
  ) => showDialog<void>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('Pendências da sincronização'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final exception in exceptions) ...[
                Text(
                  _syncCourseLabel(exception),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(_syncIssueMessage(exception)),
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
        if (exceptions.any((issue) => issue.reason == 'schedule_review') &&
            widget.gateway is BackendSchedulePendencyGateway)
          TextButton(
            key: const Key('ufmg-review-schedule-pendencies'),
            onPressed: () {
              Navigator.of(dialogContext).pop();
              _openSchedulePendencyReview();
            },
            child: const Text('Revisar horários'),
          ),
        FilledButton(
          onPressed: () => Navigator.of(dialogContext).pop(),
          child: const Text('Entendi'),
        ),
      ],
    ),
  );

  Future<void> _openSchedulePendencyReview() async {
    final gateway = widget.gateway;
    if (gateway is! BackendSchedulePendencyGateway || !mounted) return;
    _logInteraction('ufmg_review_schedule_pendencies');
    await showDialog<void>(
      context: context,
      builder: (context) => SchedulePendencyReviewDialog(
        gateway: gateway as BackendSchedulePendencyGateway,
        logger: widget.logger,
      ),
    );
    if (mounted) {
      setState(() {
        _sigaSummary = null;
      });
    }
  }

  Future<void> _offerOfficialCalendar() async {
    final gateway = widget.gateway;
    if (gateway is! BackendOfficialCalendarGateway || !mounted) return;
    final calendarGateway = gateway as BackendOfficialCalendarGateway;
    try {
      final preview = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.officialCalendarPreview,
        action: calendarGateway.previewOfficialCalendar,
      );
      if (!mounted || preview.candidates.isEmpty) return;
      _logInteraction('official_calendar_preview_shown');
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Atualizar feriados oficiais?'),
          content: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'O calendário oficial da UFMG indica estas alterações. Nenhuma será aplicada sem sua confirmação.',
                  ),
                  const SizedBox(height: 16),
                  for (final change in preview.candidates) ...[
                    Text(
                      change.courseCode,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    Text(
                      '${change.date.day.toString().padLeft(2, '0')}/'
                      '${change.date.month.toString().padLeft(2, '0')} · '
                      '${TimeOfDay.fromDateTime(change.startsAt.toLocal()).format(context)}–'
                      '${TimeOfDay.fromDateTime(change.endsAt.toLocal()).format(context)}',
                    ),
                    Text(
                      '${change.eventTitle} · aula será marcada como feriado',
                    ),
                    const SizedBox(height: 12),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Agora não'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(
                'Aplicar ${preview.candidates.length} '
                '${_plural(preview.candidates.length, 'alteração', 'alterações')}',
              ),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
      _logInteraction('official_calendar_apply_confirmed');
      final result = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.officialCalendarApply,
        action: () => calendarGateway.applyOfficialCalendar(preview.candidates),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${result.applied} ${_plural(result.applied, 'aula atualizada', 'aulas atualizadas')} pelo calendário oficial.',
          ),
        ),
      );
    } catch (error, stackTrace) {
      await widget.logger.recordError(
        error,
        stackTrace,
        context: 'official_calendar_sync',
        parameters: const {'action': 'official_calendar_best_effort'},
      );
    }
  }

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
      final discovery = widget.isMaterialView
          ? await runAuditedOperation(
              logger: widget.logger,
              operation: AuditedOperation.moodleMaterialCatalogList,
              action: widget.gateway.listMoodleMaterialCatalog,
            )
          : null;
      final issues = moodleSyncIssues(sync);
      logSyncFeedback(widget.logger, 'moodle', moodleSyncDetails(sync), issues);
      if (mounted) {
        setState(() {
          _dateImportResult = sync.dates;
          if (discovery != null) _contentDiscovery = discovery;
          _moodleSummary = _syncIssueSummary(issues);
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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.isMaterialScope
              ? 'Materiais • ${widget.materialCourseName ?? widget.materialCourseCode}'
              : widget.savedFilesOnly
              ? 'Arquivos no dispositivo'
              : widget.isMaterialView
              ? 'Materiais'
              : 'Conta acadêmica UFMG',
        ),
      ),
      body: SafeArea(
        child: Align(
          alignment: Alignment.topCenter,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: widget.isMaterialView && !widget.isMaterialScope
                    ? 920
                    : 720,
              ),
              child: _loading
                  ? _loadingContent()
                  : widget.savedFilesOnly
                  ? _savedFilesContent()
                  : widget.isMaterialScope
                  ? _scopedMaterialContent()
                  : widget.isMaterialView
                  ? _materialLibraryContent()
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
        widget.savedFilesOnly
            ? 'Carregando arquivos do dispositivo…'
            : widget.isMaterialView
            ? 'Carregando materiais…'
            : 'Conferindo a conexão com a UFMG…',
        textAlign: TextAlign.center,
      ),
      if ((widget.isMaterialView || widget.savedFilesOnly) &&
          _materialFileCache.isAvailable) ...[
        const SizedBox(height: 20),
        MaterialCacheCard(
          files: _visibleFiles,
          downloads: _visibleDownloads,
          onOpen: _openCachedMaterial,
          onRemove: _removeCachedMaterial,
          onRetry: widget.savedFilesOnly ? null : _retryFailedMaterial,
          onDismiss: _dismissFailedMaterial,
          onClear: _clearCachedMaterials,
        ),
      ],
    ],
  );

  Future<void> _openMaterialLibrary() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => UFMGConnectionPage(
          gateway: widget.gateway,
          logger: widget.logger,
          userId: widget.userId,
          materialFileCache: _materialFileCache,
          view: UFMGView.materials,
        ),
      ),
    );
    if (mounted && widget.isMaterialScope) await _loadCachedMaterials();
  }

  Widget _materialLibraryContent() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const AppPageIntro(
        title: 'Seus materiais',
        subtitle: 'Escolha a disciplina e abra ou baixe seus materiais.',
      ),
      Wrap(
        spacing: 12,
        runSpacing: 8,
        children: [
          FilledButton.icon(
            key: const Key('ufmg-sync-moodle'),
            onPressed: _moodleBusy ? null : _syncMoodle,
            icon: const Icon(Icons.sync),
            label: const Text('Atualizar materiais'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).push<void>(
              MaterialPageRoute(
                builder: (_) => UFMGConnectionPage(
                  gateway: widget.gateway,
                  logger: widget.logger,
                  userId: widget.userId,
                ),
              ),
            ),
            child: const Text('Gerenciar conexão'),
          ),
        ],
      ),
      if (_moodleBusy) const LinearProgressIndicator(),
      if (_moodleSummary != null) Text(_moodleSummary!),
      if (_moodleError != null) Text(_moodleError!),
      if (_materialCatalogFailed)
        TextButton(
          onPressed: _loadMaterialCatalog,
          child: const Text(
            'Não foi possível ler o catálogo. Tentar novamente',
          ),
        ),
      if (_materialFileCache.isAvailable) _savedFilesContent(),
      if (_contentDiscovery != null) ..._materialSections(),
      if (_contentDiscovery == null && !_materialCatalogFailed && !_moodleBusy)
        const AppEmptyState(
          icon: Icons.folder_outlined,
          title: 'Nenhum material sincronizado',
          message: 'Atualize os materiais para consultar o catálogo.',
        ),
    ],
  );

  Widget _savedFilesContent() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (_cacheReadFailed) ...[
        const Text('Não foi possível ler os arquivos salvos.'),
        TextButton(
          onPressed: _loadCachedMaterials,
          child: const Text('Tentar novamente'),
        ),
      ],
      const SizedBox(height: 16),
      MaterialCacheCard(
        files: _cachedMaterials,
        downloads: _visibleDownloads,
        onOpen: _openCachedMaterial,
        onRemove: _removeCachedMaterial,
        onRetry: widget.savedFilesOnly ? null : _retryFailedMaterial,
        onDismiss: _dismissFailedMaterial,
        onClear: _clearCachedMaterials,
      ),
      if (widget.savedFilesOnly &&
          _materialDownloadProgress.any(
            (file) => file.state == MaterialDownloadState.failed,
          ))
        const Text(
          'Para tentar baixar novamente, abra os materiais da disciplina.',
        ),
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
                  widget.materialCourseName ?? widget.materialCourseCode!,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (widget.materialCourseName != null)
                  Text(widget.materialCourseCode!),
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

      TextButton(
        onPressed: _openMaterialLibrary,
        child: const Text('Materiais de todas as disciplinas'),
      ),
      if (_materialPrefixes.isEmpty && _cachedMaterials.isNotEmpty)
        const Text('Há arquivos sem disciplina identificada.'),
      if (_cacheReadFailed)
        const Text('Não foi possível ler os arquivos salvos agora.'),
      if (_materialFileCache.isAvailable) ...[
        const SizedBox(height: 16),
        TextButton(
          onPressed: () async {
            await Navigator.of(context).push<void>(
              MaterialPageRoute(
                builder: (_) => UFMGConnectionPage(
                  gateway: widget.gateway,
                  logger: widget.logger,
                  userId: widget.userId,
                  materialFileCache: _materialFileCache,
                  view: UFMGView.savedFiles,
                ),
              ),
            );
            if (mounted) await _loadCachedMaterials();
          },
          child: const Text('Todos os arquivos do dispositivo'),
        ),
        MaterialCacheCard(
          files: _visibleFiles,
          downloads: _visibleDownloads,
          onOpen: _openCachedMaterial,
          onRemove: _removeCachedMaterial,
          onRetry: _retryFailedMaterial,
          onDismiss: _dismissFailedMaterial,
          onClear: _clearCachedMaterials,
        ),
      ],
      if (_materialCatalogFailed) ...[
        const Text('Não foi possível atualizar o catálogo.'),
        TextButton(
          onPressed: _loadMaterialCatalog,
          child: const Text('Tentar novamente'),
        ),
      ] else if (_contentDiscovery?.courses.isEmpty ?? true) ...[
        const SizedBox(height: 24),
        const Card(
          child: ListTile(
            leading: Icon(Icons.folder_off_outlined),
            title: Text('Nenhum item no catálogo desta disciplina'),
            subtitle: Text(
              'Sincronize o Moodle pela conta para atualizar o catálogo.',
            ),
          ),
        ),
      ] else
        ..._materialSections(),
    ],
  );

  Widget _content() {
    final status = _status;
    final connected = status?.connected ?? false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (connected || status?.reauthenticationRequired == true)
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
        const SizedBox(height: 12),
        if (!connected || _showReconnectForm)
          _connectionForm()
        else
          _syncActions(),
      ],
    );
  }

  Widget _accountOverview(PythonUFMGSessionStatus? status, bool connected) =>
      Card(
        key: const Key('ufmg-account-overview'),
        margin: EdgeInsets.zero,
        child: ListTile(
          leading: Icon(connected ? Icons.link : Icons.link_off),
          title: Text(connected ? 'UFMG conectada' : 'Sua sessão expirou'),
          subtitle: connected && status?.expiresAt != null
              ? Text('Válida até ${_formattedExpiry(status!.expiresAt!)}')
              : null,
        ),
      );

  String _catalogName(PythonMoodleCourseContent course) {
    final local = CourseVisualHost.of(
      context,
    )?.course(id: course.courseId, code: course.courseCode, term: course.term);
    return local?.displayName ??
        (widget.isMaterialScope ? widget.materialCourseName : null) ??
        'Disciplina ${course.courseCode}';
  }

  List<Widget> _materialSections() {
    final downloadableCourses = _contentDiscovery!.courses
        .where((course) => _downloadableMaterials([course]).isNotEmpty)
        .length;
    return [
      const SizedBox(height: 8),
      if (_materialFileCache.isAvailable && downloadableCourses > 0)
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
            title: Text(_catalogName(course)),
            subtitle: Text('${course.courseCode} • ${_contentStatus(course)}'),
            children: [
              if (_materialFileCache.isAvailable &&
                  downloadableCourses > 1 &&
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
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
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
    ];
  }

  List<Widget> _dateImportIssues() => [
    if (_dateImportResult case final result?)
      if (result.unmatchedEvents.isNotEmpty || result.failedCourses.isNotEmpty)
        ExpansionTile(
          key: const Key('moodle-date-import-issues'),
          title: Text(
            'Avisos das datas (${result.unmatchedEvents.length + result.failedCourses.length})',
          ),
          children: [
            for (final issue in result.unmatchedEvents)
              ListTile(
                title: Text('${issue['title']}'),
                subtitle: Text(
                  '${issue['reason'] == 'ambiguous_course' ? 'Mais de uma disciplina corresponde' : 'Disciplina não encontrada'} · ${issue['term']}',
                ),
                trailing: TextButton(
                  onPressed: () => _launchMaterialUri(
                    Uri.parse(
                      'https://virtual.ufmg.br/${(issue['term']! as String).replaceAll('-', '')}/course/view.php?id=${issue['moodle_course_id']}',
                    ),
                  ),
                  child: const Text('Ver no Moodle'),
                ),
              ),
            for (final issue in result.failedCourses)
              ListTile(
                title: Text(
                  'Não foi possível atualizar ${issue['course_code'] ?? issue['course_id']}',
                ),
                subtitle: const Text('Tente sincronizar novamente.'),
              ),
          ],
        ),
  ];

  Widget _syncActions() {
    if (widget.gateway is BackendUnifiedAcademicSyncGateway) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _academicSourceCard(
            key: const Key('ufmg-source-all'),
            icon: Icons.sync_outlined,
            title: 'UFMG e Moodle',
            description: 'Disciplinas, horários, datas e planos de ensino',
            actionKey: const Key('ufmg-sync-all'),
            actionLabel: 'Sincronizar tudo',
            busy:
                _sigaBusy ||
                _moodleBusy ||
                widget.academicSync?.isRunning == true,
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
          if ((_lastSyncResult ?? widget.academicSync?.result)
              case final result?)
            TextButton.icon(
              onPressed: _reviewingSyncResult
                  ? null
                  : () => _reviewAcademicSyncResult(result),
              icon: const Icon(Icons.checklist),
              label: const Text('Revisar última sincronização'),
            ),
          ..._dateImportIssues(),
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
        ..._dateImportIssues(),
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
        if (widget.academicSync != null)
          CheckboxListTile(
            key: const Key('ufmg-force-refresh'),
            contentPadding: EdgeInsets.zero,
            title: const Text('Consultar novamente todas as fontes'),
            value: _forceSync,
            onChanged: widget.academicSync!.isRunning
                ? null
                : (value) {
                    _logInteraction(
                      value == true
                          ? 'ufmg_force_refresh_enabled'
                          : 'ufmg_force_refresh_disabled',
                    );
                    setState(() => _forceSync = value ?? false);
                  },
          ),

        SizedBox(
          width: double.infinity,
          child: TextButton.icon(
            key: const Key('ufmg-reconnect'),
            onPressed: _busy || widget.academicSync?.isRunning == true
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
            onPressed: _busy || widget.academicSync?.isRunning == true
                ? null
                : _confirmDisconnect,
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
            ],
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
      '${course.candidates.length} ${_plural(course.candidates.length, 'material', 'materiais')}',
    PythonMoodleContentStatus.empty => 'Nenhum material encontrado',
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
