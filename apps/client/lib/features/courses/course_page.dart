import '../navigation/product_navigation.dart';
import '../settings/settings_page.dart';
import '../settings/automatic_attendance_controller.dart';
import '../../design/course_visuals.dart';
import '../activities/course_workspace_page.dart';
import 'dart:convert';
import '../../data/automatic_checkpoint_scheduler.dart';
import '../ufmg/academic_sync_host.dart';
import '../../data/first_checkpoint.dart';
import '../../data/campus_location.dart';
import '../../data/academic_agenda.dart';
import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../auth/auth_user.dart';
import '../../backend/python_backend_transport.dart';
import '../../backend/academic_sync_progress.dart';
import '../../data/academic_records.dart';
import '../../data/attendance_permissions.dart';
import '../../data/academic_repositories.dart';
import '../../data/academic_period.dart';
import '../../data/calendar_status.dart';
import '../../data/course_draft_store.dart';
import '../../data/python_overview_repository.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/adaptive_app_shell.dart';
import '../../design/app_feedback.dart';
import '../../design/app_motion.dart';
import '../../design/course_identity.dart';
import '../../observability/error_log_details.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';
import '../attendance/absence_dashboard_page.dart';
import '../attendance/attendance_page.dart';
import '../schedule/general_calendar_page.dart';
import '../ufmg/ufmg_connection_page.dart';
import '../ufmg/academic_sync_controller.dart';
import '../ufmg/academic_sync_banner.dart';
import 'course_editor_dialog.dart';
import 'course_hub_page.dart';

typedef CourseIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

enum _CourseTileAction { edit, delete }

class CoursePage extends StatefulWidget {
  // The runtime defaults intentionally prevent callers from needing utility
  // objects merely to construct the production page.
  // ignore: prefer_const_constructors_in_immutables
  CoursePage({
    required this.repository,
    required this.meetingRepository,
    required this.sessionRepository,
    required this.user,
    required this.logger,
    required this.onSignOut,
    CourseRepository? fallbackCourseRepository,
    this.attendanceEvaluator,
    this.scheduleGateway,
    this.sessionGateway,
    this.ufmgSessionGateway,
    this.ufmgSyncSchedule,
    this.academicSyncSchedule,
    this.draftStore,
    this.overviewRepository,
    this.scheduleReadsEnabled = true,
    this.scheduleWritesEnabled = false,
    this.sessionWritesEnabled = false,
    this.overviewReadsEnabled = false,
    this.androidOfflineQueueEnabled = false,
    this.checkpointDeliveryUpdates,
    this.attendancePermissions,
    this.attendanceExperience,
    this.automaticCheckpointScheduler,
    CourseIdGenerator? idGenerator,
    CurrentTime? now,
    super.key,
  }) : fallbackCourseRepository = fallbackCourseRepository ?? repository,
       idGenerator = idGenerator ?? _newCourseId,
       now = now ?? DateTime.now,
       assert(!overviewReadsEnabled || overviewRepository != null);

  final CourseRepository repository;
  final CourseRepository fallbackCourseRepository;
  final MeetingRepository meetingRepository;
  final SessionRepository sessionRepository;
  final AuthUser user;
  final AppLogger logger;
  final Future<void> Function() onSignOut;
  final BackendAttendanceEvaluator? attendanceEvaluator;
  final BackendScheduleGateway? scheduleGateway;
  final BackendSessionGateway? sessionGateway;
  final BackendUFMGSessionGateway? ufmgSessionGateway;
  final UFMGSyncScheduleGateway? ufmgSyncSchedule;
  final UFMGSyncScheduleGateway? academicSyncSchedule;
  final CourseDraftStore? draftStore;
  final AcademicOverviewRepository? overviewRepository;
  final bool scheduleReadsEnabled;
  final bool scheduleWritesEnabled;
  final bool sessionWritesEnabled;
  final bool overviewReadsEnabled;
  final bool androidOfflineQueueEnabled;
  final Stream<Map<String, Object?>>? checkpointDeliveryUpdates;
  final AttendancePermissionsGateway? attendancePermissions;
  final AutomaticAttendanceController? attendanceExperience;
  final AutomaticCheckpointScheduler? automaticCheckpointScheduler;
  final CourseIdGenerator idGenerator;
  final CurrentTime now;

  @override
  State<CoursePage> createState() => _CoursePageState();
}

class _CoursePageState extends State<CoursePage> with WidgetsBindingObserver {
  StreamSubscription<Map<String, Object?>>? _deliverySubscription;
  int _deliveryRevision = 0;
  bool _deliveryDirty = false;
  bool _noticePending = false, _checkpointOpen = false;
  int _noticeRevision = 0;
  bool _deliveryActive = true;
  bool _checkpointSchedulingAllowed = true;
  AutomaticCheckpointScheduler? _automaticCheckpoints;
  Timer? _dayWatchTimer;
  DateTime? _lastLocalDay;

  void _reconcileCheckpoints(
    AcademicOverviewSnapshot snapshot,
    String trigger,
  ) {
    final scheduler = _automaticCheckpoints;
    if (scheduler == null || !_checkpointSchedulingAllowed || !mounted) return;
    unawaited(
      scheduler
          .reconcile(snapshot, trigger: trigger)
          .then((_) => _automaticAttendance?.refresh(afterCurrent: true)),
    );
  }

  void _onDeliveryUpdate(Map<String, Object?> event) {
    if (event['account_id'] == widget.user.id &&
        event['action'] == 'open_checkpoints') {
      final revision = event['open_revision'];
      if (revision is int && revision > _noticeRevision) {
        _noticeRevision = revision;
        if (_checkpointOpen) return;
        _noticePending = true;
        _refreshDeliveryIfNeeded();
      }
      return;
    }
    final revision = event['revision'];
    if (event['account_id'] != widget.user.id ||
        revision is! int ||
        revision <= _deliveryRevision) {
      return;
    }
    _deliveryRevision = revision;
    unawaited(_automaticAttendance?.refresh(afterCurrent: true));
    _deliveryDirty = true;
    _refreshDeliveryIfNeeded();
  }

  void _refreshDeliveryIfNeeded() {
    if (mounted && _noticePending && _deliveryActive && !_loading) {
      _noticePending = false;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || _checkpointOpen) return;
        unawaited(_openCheckpointPage());
      });
      WidgetsBinding.instance.ensureVisualUpdate();
    }

    if (!mounted ||
        !_deliveryDirty ||
        !_deliveryActive ||
        _loading ||
        ModalRoute.of(context)?.isCurrent == false) {
      return;
    }
    unawaited(
      widget.logger
          .logEvent(
            'checkpoint_delivery_ui_refresh',
            parameters: {
              'screen': 'home',
              'details': jsonEncode({'revision': _deliveryRevision}),
            },
          )
          .catchError((Object error) {
            debugPrint(
              'checkpoint_delivery_refresh_log_failed type=${error.runtimeType}',
            );
          }),
    );
    unawaited(_load());
  }

  DateTime _localDay(DateTime value) {
    final local = tz.TZDateTime.from(
      value,
      tz.getLocation('America/Sao_Paulo'),
    );
    return DateTime(local.year, local.month, local.day);
  }

  void _watchDay() {
    if (!mounted) return;
    final day = _localDay(widget.now());
    if (_lastLocalDay != null && day != _lastLocalDay) {
      _lastLocalDay = day;
      unawaited(_load());
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _deliveryActive = state == AppLifecycleState.resumed;
    if (_deliveryActive) {
      _watchDay();
      unawaited(_automaticAttendance?.refresh(afterCurrent: true));
    }
    if (_deliveryActive && _usingOverviewSnapshot) {
      _reconcileCheckpoints(
        AcademicOverviewSnapshot(
          courses: _courses,
          sessionsByCourse: _sessionsByCourse,
          isLocalCopy: _usingLocalCopy,
        ),
        'app_resumed',
      );
    }
    _refreshDeliveryIfNeeded();
  }

  ProductNavigationController? _navigation;
  AutomaticAttendanceController? _automaticAttendance;
  bool _automationReady = false;
  void _onAutomaticConfiguration() {
    final c = _automaticAttendance;
    final ready = c?.status != null && c!.next == null && !c.permissionError;
    final becameReady = ready && !_automationReady;
    _automationReady = ready;
    if (becameReady) _rescheduleFromSettings();
  }

  void _rescheduleFromSettings() {
    if (mounted && _courses.isNotEmpty) {
      _reconcileCheckpoints(
        AcademicOverviewSnapshot(
          courses: _courses,
          sessionsByCourse: _sessionsByCourse,
          isLocalCopy: _usingLocalCopy,
        ),
        'configuration_changed',
      );
    }
  }

  void _ensureAutomaticAttendance() {
    if (_automaticAttendance == null && widget.attendanceExperience != null) {
      _automaticAttendance = widget.attendanceExperience;
      _automaticAttendance!.addListener(_onAutomaticConfiguration);
      unawaited(_automaticAttendance!.refresh());
      return;
    }
    if (_automaticAttendance != null ||
        (widget.attendancePermissions == null &&
            (kIsWeb || defaultTargetPlatform != TargetPlatform.android))) {
      return;
    }
    final native = FirstCheckpointGateway(
      accountId: widget.user.id,
      logger: widget.logger,
      logReports: false,
    );
    _automaticAttendance = AutomaticAttendanceController(
      accountId: widget.user.id,
      permissions:
          widget.attendancePermissions ?? const AndroidAttendancePermissions(),
      readReports: () => native.perform('read'),
      nativeAction: (action) async {
        await native.perform(action);
      },
      logger: widget.logger,
      now: widget.now,
    );
    _automaticAttendance!.addListener(_onAutomaticConfiguration);
    unawaited(_automaticAttendance!.refresh());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final navigation = ProductNavigation.of(context);
    if (navigation != null) {
      _ensureAutomaticAttendance();
      _navigation = navigation;
      navigation.bind(
        this,
        _openDestination,
        attendance: _automaticAttendance,
        logger: widget.logger,
      );
    }
  }

  final _calendarNavigation = CalendarNavigationState();
  List<CourseRecord> _courses = const [];
  bool _loading = true;
  bool _loadFailed = false;
  String? _deletingId;
  final _savingIds = <String>{};
  int _pastPendingCount = 0;
  _PendingAttendance? _nextPastPending;
  Map<String, List<SessionRecord>> _sessionsByCourse = const {};
  bool _usingOverviewSnapshot = false;
  Map<String, List<PythonMoodleDate>> _datesByCourse = {};
  Set<String> _unavailableDateCourses = {};
  bool _usingLocalCopy = false;
  bool _automaticUFMGSyncStarted = false;
  String? _ufmgSyncNotice;
  AcademicSyncController? _academicSync;
  Future<void>? _academicSyncRestore;
  DateTime? _academicAutoNextAt;
  AcademicSyncHostState? _syncHost;
  bool _syncBannerShown = false;
  bool _academicSyncWasRunning = false;
  final _overviewUpdates = ValueNotifier<AcademicOverviewSnapshot?>(null);

  @override
  void initState() {
    super.initState();
    _automaticCheckpoints = widget.automaticCheckpointScheduler;
    if (_automaticCheckpoints == null &&
        !kIsWeb &&
        defaultTargetPlatform == TargetPlatform.android) {
      final gateway = FirstCheckpointGateway(
        logReports: false,
        accountId: widget.user.id,
        logger: widget.logger,
      );
      _automaticCheckpoints = AutomaticCheckpointScheduler(
        permissions:
            widget.attendancePermissions ??
            const AndroidAttendancePermissions(),
        selection: LocalCampusSelection(),
        logger: widget.logger,
        now: widget.now,
        isActive: () => mounted && _checkpointSchedulingAllowed,
        perform: (action, fields) => gateway.perform(action, fields),
      );
    }
    WidgetsBinding.instance.addObserver(this);
    _lastLocalDay = _localDay(widget.now());
    _dayWatchTimer = Timer.periodic(
      const Duration(minutes: 1),
      (_) => _watchDay(),
    );
    _deliveryActive =
        (WidgetsBinding.instance.lifecycleState ?? AppLifecycleState.resumed) ==
        AppLifecycleState.resumed;
    _deliverySubscription = widget.checkpointDeliveryUpdates?.listen(
      _onDeliveryUpdate,
      onError: (Object error, StackTrace stack) {
        recordOperationalFailure(
          widget.logger,
          error,
          stack,
          'checkpoint_delivery_updates',
          {'stage': 'delivery_events'},
          failureCode: 'checkpoint_delivery_events_failed',
        );
      },
    );
    if (widget.ufmgSessionGateway
        case final BackendAcademicSyncProgressGateway gateway) {
      _academicSync = AcademicSyncController(
        gateway: gateway,
        logger: widget.logger,
      )..addListener(_onAcademicSyncChanged);
      _academicSyncRestore = _academicSync!.restore();
      unawaited(_academicSyncRestore);
    }
    _load();
  }

  Future<void> _refreshAfterAcademicSync() async {
    if (widget.academicSyncSchedule case final schedule?
        when _academicSync?.result != null && !_academicSync!.isRestoring) {
      await _recordAcademicDeadline(schedule, const Duration(hours: 6));
    }
    if (mounted) await _load();
  }

  void _onAcademicSyncChanged() {
    final running = _academicSync!.isRunning;
    if (_academicSyncWasRunning && !running) {
      unawaited(_refreshAfterAcademicSync());
    }
    _academicSyncWasRunning = running;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final controller = _academicSync!;
      final host = _syncHost ??= AcademicSyncHost.maybeOf(context);
      if (host == null) return;
      if (controller.visible && !_syncBannerShown) {
        _syncBannerShown = true;
        host.show(
          controller,
          AcademicSyncBanner(
            controller: controller,
            detailsContext: context,
            onReview: () => unawaited(_openUFMGConnection()),
          ),
        );
      } else if (!controller.visible && _syncBannerShown) {
        _syncBannerShown = false;
        host.clear(controller);
      }
    });
    WidgetsBinding.instance.ensureVisualUpdate();
  }

  @override
  void dispose() {
    _checkpointSchedulingAllowed = false;
    _dayWatchTimer?.cancel();
    _navigation?.unbind(this);
    _automaticAttendance?.removeListener(_onAutomaticConfiguration);
    if (!identical(_automaticAttendance, widget.attendanceExperience)) {
      _automaticAttendance?.dispose();
    }
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_deliverySubscription?.cancel());
    final controller = _academicSync;
    final host = _syncHost;
    if (controller != null && host != null) {
      WidgetsBinding.instance.addPostFrameCallback(
        (_) => host.clear(controller),
      );
    }
    _academicSync?.removeListener(_onAcademicSyncChanged);
    _academicSync?.dispose();
    _overviewUpdates.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    _deliveryDirty = false;
    setState(() {
      _loading = true;
      _loadFailed = false;
    });
    var cachedSnapshotShown = false;
    final overviewRepository = widget.overviewRepository;
    if (widget.overviewReadsEnabled &&
        overviewRepository is LocalFirstAcademicOverviewRepository) {
      final cached = await overviewRepository.loadCachedOverview();
      if (cached != null && mounted) {
        _applyOverviewSnapshot(cached);
        unawaited(widget.logger.logEvent('academic_overview_cache_presented'));
        cachedSnapshotShown = true;
        setState(() => _loading = false);
      }
    }
    try {
      AcademicOverviewSnapshot? snapshot;
      var overviewFallback = false;
      if (widget.overviewReadsEnabled) {
        try {
          snapshot = await widget.overviewRepository!.loadOverview();
        } catch (_) {
          overviewFallback = true;
        }
      }
      late final List<CourseRecord> courses;
      if (snapshot != null) {
        courses = snapshot.courses.toList();
      } else if (overviewFallback) {
        courses = await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.academicOverviewFallback,
          action: widget.fallbackCourseRepository.listCourses,
        );
      } else {
        courses = await widget.repository.listCourses();
      }
      final sessionsByCourse = snapshot == null
          ? <String, List<SessionRecord>>{}
          : {
              for (final entry in snapshot.sessionsByCourse.entries)
                entry.key: List<SessionRecord>.of(entry.value),
            };
      await _removeExpiredCourses(courses);
      sessionsByCourse.removeWhere(
        (courseId, _) => courses.every((course) => course.id != courseId),
      );
      if (!mounted) return;
      // CW09: disciplina criada em estado otimista continua visivel nos
      // recortes ate o servidor confirmar; _persistCreatedCourse faz o
      // rollback se a gravacao falhar.
      for (final item in _courses) {
        if (_savingIds.contains(item.id) &&
            courses.every((course) => course.id != item.id)) {
          courses.add(item);
        }
      }
      courses.sort(compareCourseNames);
      setState(() {
        _courses = courses;
        _sessionsByCourse = sessionsByCourse;
        _usingOverviewSnapshot = snapshot != null;
        _usingLocalCopy = snapshot?.isLocalCopy ?? false;
        _datesByCourse = snapshot?.datesByCourse ?? {};
        _unavailableDateCourses =
            snapshot?.unavailableDateCourses ??
            {for (final course in courses) course.id};
      });
      await CourseVisualHost.of(
        context,
        listen: false,
      )?.update(widget.user.id, _courses, logger: widget.logger);
      if (!mounted) return;
      _overviewUpdates.value = AcademicOverviewSnapshot(
        courses: _courses,
        sessionsByCourse: _sessionsByCourse,
        datesByCourse: _datesByCourse,
        unavailableDateCourses: _unavailableDateCourses,
        isLocalCopy: _usingLocalCopy,
      );
      if (snapshot != null) {
        _reconcileCheckpoints(_overviewUpdates.value!, 'overview_loaded');
      }
      recordAgendaPresentation(
        logger: widget.logger,
        screen: 'home',
        importedCount: _datesByCourse.values.fold(
          0,
          (sum, dates) => sum + dates.length,
        ),
        entryCount: _courses.fold(
          0,
          (sum, course) =>
              sum +
              courseAgenda(
                course,
                _sessionsByCourse[course.id] ?? [],
                _datesByCourse[course.id] ?? [],
              ).length,
        ),
        unavailableCourses: _unavailableDateCourses,
        isLocalCopy: _usingLocalCopy,
      );
      if (snapshot == null) {
        unawaited(
          _loadPastPendingCount(courses, retryOverview: !overviewFallback),
        );
      } else {
        _setPastPending(courses, [
          for (final course in courses)
            sessionsByCourse[course.id] ?? const <SessionRecord>[],
        ]);
      }
    } catch (_) {
      if (mounted && !cachedSnapshotShown) {
        setState(() => _loadFailed = true);
      }
    } finally {
      if (mounted) setState(() => _loading = false);
      _startAutomaticUFMGSync();
      _refreshDeliveryIfNeeded();
    }
  }

  void _startAutomaticUFMGSync() {
    if (_automaticUFMGSyncStarted ||
        widget.ufmgSessionGateway == null ||
        widget.ufmgSyncSchedule == null &&
            widget.academicSyncSchedule == null) {
      return;
    }
    _automaticUFMGSyncStarted = true;
    unawaited(_runAutomaticUFMGSync());
  }

  Future<void> _recordAcademicDeadline(
    UFMGSyncScheduleGateway schedule,
    Duration delay,
  ) async {
    _academicAutoNextAt = widget.now().toUtc().add(delay);
    try {
      await schedule.record(widget.user.id, _academicAutoNextAt!);
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'academic_auto_schedule_write',
        {'stage': 'schedule_write'},
        failureCode: 'academic_auto_schedule_write_failed',
      );
    }
  }

  Future<void> _runAutomaticAcademicSync(
    UFMGSyncScheduleGateway schedule,
  ) async {
    final fields = <String, Object>{
      'operation': 'academic_sync',
      'trigger': 'dashboard_open',
    };
    try {
      await _academicSyncRestore;
      if (!mounted) return;
      if ((_academicAutoNextAt?.isAfter(widget.now().toUtc()) ?? false) ||
          !await schedule.isDue(widget.user.id)) {
        emitOperationalEvent(widget.logger, 'academic_auto_sync_skipped', {
          ...fields,
          'reason': 'not_due',
        });
        return;
      }
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionStatus,
        action: widget.ufmgSessionGateway!.getUFMGSessionStatus,
      );
      if (!status.connected) {
        emitOperationalEvent(widget.logger, 'academic_auto_sync_skipped', {
          ...fields,
          'reason': status.reauthenticationRequired
              ? 'reauthentication_required'
              : 'not_connected',
        });
        await _recordAcademicDeadline(schedule, const Duration(minutes: 15));
        if (status.reauthenticationRequired && mounted) {
          setState(
            () => _ufmgSyncNotice =
                'Reconecte à UFMG para atualizar suas atividades.',
          );
        }
        return;
      }
      await _recordAcademicDeadline(schedule, const Duration(hours: 6));
      emitOperationalEvent(widget.logger, 'academic_auto_sync_started', fields);
      await _academicSync!.start();
      emitOperationalEvent(
        widget.logger,
        'academic_auto_sync_succeeded',
        fields,
      );
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'academic_auto_sync',
        fields,
        failureCode: 'academic_auto_sync_failed',
      );
      await _recordAcademicDeadline(schedule, const Duration(minutes: 15));
    }
  }

  Future<void> _runAutomaticUFMGSync() async {
    if (widget.academicSyncSchedule case final schedule?
        when _academicSync != null) {
      await _runAutomaticAcademicSync(schedule);
      _automaticUFMGSyncStarted = false;
      return;
    }
    final gateway = widget.ufmgSessionGateway!;
    final schedule = widget.ufmgSyncSchedule!;
    try {
      if (!await schedule.isDue(widget.user.id)) {
        unawaited(
          widget.logger.logEvent(
            'ufmg_sync_skipped',
            parameters: {'reason': 'not_due'},
          ),
        );
        return;
      }
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionStatus,
        action: gateway.getUFMGSessionStatus,
      );
      if (!status.connected) {
        unawaited(
          widget.logger.logEvent(
            'ufmg_sync_skipped',
            parameters: {
              'reason': status.reauthenticationRequired
                  ? 'reauthentication_required'
                  : 'not_connected',
            },
          ),
        );
        if (status.reauthenticationRequired && mounted) {
          setState(
            () => _ufmgSyncNotice =
                'Reconecte à UFMG para atualizar disciplinas e horários.',
          );
        }
        return;
      }
      final result = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSync,
        action: gateway.syncSiga,
      );
      await schedule.record(widget.user.id, result.nextAutomaticSyncAt);
      final changed = result.courses.created + result.schedules.updated;
      if (changed > 0 && mounted) await _load();
    } catch (error) {
      if (!mounted) return;
      final reauthenticationRequired =
          error is PythonBackendException &&
          error.code == PythonBackendError.ufmgReauthenticationRequired;
      setState(
        () => _ufmgSyncNotice = reauthenticationRequired
            ? 'Reconecte à UFMG para atualizar disciplinas e horários.'
            : 'Não foi possível sincronizar com a UFMG agora. Seus dados continuam disponíveis.',
      );
    }
  }

  void _applyOverviewSnapshot(AcademicOverviewSnapshot snapshot) {
    final courses = snapshot.courses.toList()..sort(compareCourseNames);
    final sessionsByCourse = {
      for (final entry in snapshot.sessionsByCourse.entries)
        entry.key: List<SessionRecord>.of(entry.value),
    };
    sessionsByCourse.removeWhere(
      (courseId, _) => courses.every((course) => course.id != courseId),
    );
    setState(() {
      _courses = courses;
      _sessionsByCourse = sessionsByCourse;
      _usingOverviewSnapshot = true;
      _usingLocalCopy = true;
      _datesByCourse = snapshot.datesByCourse;
      _unavailableDateCourses = snapshot.unavailableDateCourses;
    });
    _reconcileCheckpoints(
      AcademicOverviewSnapshot(
        courses: courses,
        sessionsByCourse: sessionsByCourse,
        isLocalCopy: true,
      ),
      'cached_overview',
    );
    unawaited(
      CourseVisualHost.of(
        context,
        listen: false,
      )?.update(widget.user.id, courses, logger: widget.logger),
    );
    _setPastPending(courses, [
      for (final course in courses)
        sessionsByCourse[course.id] ?? const <SessionRecord>[],
    ]);
  }

  Future<void> _loadPastPendingCount(
    List<CourseRecord> courses, {
    bool retryOverview = true,
  }) async {
    if (_usingOverviewSnapshot && retryOverview) {
      await _load();
      return;
    }
    try {
      final location = tz.getLocation('America/Sao_Paulo');
      final localNow = tz.TZDateTime.from(widget.now(), location);
      final today = DateTime(localNow.year, localNow.month, localNow.day);
      final loaded = await Future.wait([
        for (final course in courses)
          widget.sessionRepository.listSessions(course.id),
      ]);
      if (mounted) {
        _reconcileCheckpoints(
          AcademicOverviewSnapshot(
            courses: courses,
            sessionsByCourse: {
              for (var i = 0; i < courses.length; i++) courses[i].id: loaded[i],
            },
            // Separate reads are not an authoritative atomic overview.
            isLocalCopy: true,
          ),
          'session_catalog_loaded',
        );
      }
      _setPastPending(courses, loaded, today: today, location: location);
    } catch (error, stackTrace) {
      unawaited(
        widget.logger.recordError(
          error,
          stackTrace,
          context: 'past_attendance_pending_load',
        ),
      );
    }
  }

  void _setPastPending(
    List<CourseRecord> courses,
    List<List<SessionRecord>> loaded, {
    DateTime? today,
    tz.Location? location,
  }) {
    final effectiveLocation = location ?? tz.getLocation('America/Sao_Paulo');
    final localNow = tz.TZDateTime.from(widget.now(), effectiveLocation);
    final effectiveToday =
        today ?? DateTime(localNow.year, localNow.month, localNow.day);
    final pending = <_PendingAttendance>[];
    for (var index = 0; index < courses.length; index++) {
      for (final session in loaded[index]) {
        final localSession = tz.TZDateTime.from(
          session.startsAt,
          effectiveLocation,
        );
        final day = DateTime(
          localSession.year,
          localSession.month,
          localSession.day,
        );
        if (courses[index].tracksAttendance &&
            session.calendarStatus.requiresAttendance &&
            session.absences == null &&
            day.isBefore(effectiveToday)) {
          pending.add(_PendingAttendance(courses[index], session));
        }
      }
    }
    pending.sort(
      (left, right) => right.session.startsAt.compareTo(left.session.startsAt),
    );
    if (mounted) {
      setState(() {
        _pastPendingCount = pending.length;
        _nextPastPending = pending.isEmpty ? null : pending.first;
      });
    }
  }

  Future<void> _removeExpiredCourses(List<CourseRecord> courses) async {
    final policy = AcademicPeriodPolicy(widget.now());
    final expired = courses.where(policy.isExpired).toList(growable: false);
    for (final course in expired) {
      final timer = Stopwatch()..start();
      final fields = <String, Object>{
        'operation_id': newCorrelationId('course_expiration'),
        'screen': 'home',
        'course_id': course.id,
        'course_code': course.code,
        'term': course.term,
        'stage': 'expiration_delete',
      };
      emitOperationalEvent(
        widget.logger,
        'course_expiration_delete_started',
        fields,
      );
      try {
        await widget.repository.deleteCourse(course.id);
        courses.remove(course);
        emitOperationalEvent(
          widget.logger,
          'course_expiration_delete_succeeded',
          {...fields, 'duration_ms': timer.elapsedMilliseconds},
        );
      } catch (error, stackTrace) {
        recordOperationalFailure(
          widget.logger,
          error,
          stackTrace,
          'course_expiration_delete',
          {
            ...fields,
            'duration_ms': timer.elapsedMilliseconds,
            'retained_previous': true,
          },
          failureCode: 'course_expiration_delete_failed',
        );
      }
    }
  }

  static const String _courseDraftSession = 'course-create';

  CourseDraftStore? _lazyDraftStore;

  CourseDraftStore get _draftStore {
    final provided = widget.draftStore;
    if (provided != null) return provided;
    return _lazyDraftStore ??= SharedPreferencesCourseDraftStore();
  }

  BackendRegistrationDraftGateway? get _draftGateway =>
      widget.ufmgSessionGateway is BackendRegistrationDraftGateway
      ? widget.ufmgSessionGateway! as BackendRegistrationDraftGateway
      : null;

  Future<Map<String, Object?>?> _latestCourseDraft() async {
    final store = _draftStore;
    Map<String, Object?>? localDraft;
    try {
      localDraft = await store.read(widget.user.id, _courseDraftSession);
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_local_read')
            .catchError((_) => null),
      );
    }
    if (localDraft != null) return localDraft;
    final gateway = _draftGateway;
    if (gateway == null) return null;
    try {
      final drafts = await gateway.listRegistrationDrafts();
      final matching = [
        for (final draft in drafts)
          if (draft.sessionId == _courseDraftSession) draft,
      ];
      if (matching.isEmpty) return null;
      final formData = matching.last.formData;
      try {
        await store.save(widget.user.id, _courseDraftSession, formData);
      } catch (error, stack) {
        unawaited(
          widget.logger
              .recordError(error, stack, context: 'course_draft_local_cache')
              .catchError((_) => null),
        );
      }
      return formData;
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_restore')
            .catchError((_) => null),
      );
      return localDraft;
    }
  }

  /// Persists the form locally first (the confirmed, offline-safe copy) and
  /// then opportunistically mirrors it to the backend. Returns whether the
  /// local copy was confirmed; the local draft is kept for retry either way.
  Future<bool> _saveCourseDraft(CourseRecord course, String? errorCode) async {
    final formData = <String, Object?>{
      'code': course.code,
      'name': course.name,
      'nickname': course.nickname ?? '',
      'term': course.term,
      'modality': course.modality.code,
      'attendance_policy': course.attendancePolicy.code,
    };
    final store = _draftStore;
    var locallyPersisted = false;
    try {
      await store.save(
        widget.user.id,
        _courseDraftSession,
        formData,
        lastError: errorCode,
      );
      locallyPersisted = true;
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_local_save')
            .catchError((_) => null),
      );
    }
    final gateway = _draftGateway;
    if (gateway == null) return locallyPersisted;
    try {
      await gateway.saveRegistrationDraft(
        courseId: course.id,
        courseCode: course.code,
        sessionId: _courseDraftSession,
        formData: formData,
        lastError: errorCode,
      );
      unawaited(
        widget.logger.logEvent(
          'course_draft_saved',
          parameters: {
            'course_id': course.id,
            'course_code': course.code,
            'last_error': errorCode ?? '',
          },
        ),
      );
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_save')
            .catchError((_) => null),
      );
    }
    return locallyPersisted;
  }

  Future<void> _clearCourseDrafts() async {
    final store = _draftStore;
    try {
      await store.clear(widget.user.id, _courseDraftSession);
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_local_clear')
            .catchError((_) => null),
      );
    }
    final gateway = _draftGateway;
    if (gateway == null) return;
    try {
      final drafts = await gateway.listRegistrationDrafts();
      for (final draft in drafts) {
        if (draft.sessionId == _courseDraftSession) {
          await gateway.deleteRegistrationDraft(draft.id);
        }
      }
    } catch (error, stack) {
      unawaited(
        widget.logger
            .recordError(error, stack, context: 'course_draft_clear')
            .catchError((_) => null),
      );
    }
  }

  Future<void> _openEditor([CourseRecord? course]) async {
    final mode = course == null ? 'create' : 'update';
    final policy = AcademicPeriodPolicy(widget.now());
    unawaited(widget.logger.logEvent('course_${mode}_editor_opened'));
    final draftValues = course == null ? await _latestCourseDraft() : null;
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => CourseEditorDialog(
        course: course,
        draftValues: draftValues,
        initialTerm: course?.term ?? policy.current.term,
        allowedTerms: policy.allowedTerms,
        onSave: (input) => _save(course, input),
        onValidationFailed: () => unawaited(
          widget.logger.logEvent('course_${mode}_validation_failed'),
        ),
      ),
    );
    if (mounted && widget.overviewReadsEnabled) await _load();
  }

  Future<void> _openCourseHub(CourseRecord course) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        settings: const RouteSettings(name: 'course'),
        builder: (context) => CourseHubPage(
          overviewUpdates: _overviewUpdates,
          refreshOverview: widget.overviewReadsEnabled
              ? () async {
                  await _load();
                  if (_loadFailed) throw StateError('overview_refresh_failed');
                }
              : null,
          onEdit: (selected) async {
            await _openEditor(selected);
            return _courses.where((item) => item.id == selected.id).firstOrNull;
          },
          calendarNavigation: _calendarNavigation,
          onOpenCourse: _openCourseHub,
          course: course,
          allCourses: _courses,
          datesByCourse: _datesByCourse,
          unavailableDateCourses: _unavailableDateCourses,
          courseRepository: widget.repository,
          meetingRepository: widget.meetingRepository,
          sessionRepository: widget.sessionRepository,
          logger: widget.logger,
          now: widget.now,
          attendanceEvaluator: widget.attendanceEvaluator,
          scheduleGateway: widget.scheduleGateway,
          scheduleReadsEnabled: widget.scheduleReadsEnabled,
          sessionGateway: widget.sessionGateway,
          scheduleWritesEnabled: widget.scheduleWritesEnabled,
          sessionWritesEnabled: widget.sessionWritesEnabled,
          androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          initialSessionsByCourse: _usingOverviewSnapshot
              ? _sessionsByCourse
              : null,
          ufmgSessionGateway: widget.ufmgSessionGateway,
          academicSync: _academicSync,
          ufmgSyncSchedule: widget.ufmgSyncSchedule,
          userId: widget.user.id,
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _changeSessionStatus(
    String courseId,
    String sessionId,
    SessionCalendarStatus status,
  ) async {
    final current = (_sessionsByCourse[courseId] ?? const <SessionRecord>[])
        .firstWhere((s) => s.id == sessionId);
    await widget.sessionRepository.saveSession(
      courseId,
      SessionRecord(
        id: current.id,
        startsAt: current.startsAt,
        endsAt: current.endsAt,
        lessonCount: current.lessonCount,
        callCount: current.callCount,
        firstPing: current.firstPing,
        secondPing: current.secondPing,
        attendanceStatus: current.attendanceStatus,
        absences: current.absences,
        calendarStatus: status,
        assessmentTitle: current.assessmentTitle,
        createdAt: current.createdAt,
        updatedAt: widget.now().toUtc(),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _openCourseActivities(
    CourseRecord course, {
    String? activityTitle,
  }) async {
    final gateway =
        widget.ufmgSessionGateway! as BackendAcademicWorkspaceGateway;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        settings: const RouteSettings(name: 'course'),
        builder: (_) => CourseWorkspacePage(
          course: course,
          gateway: gateway,
          logger: widget.logger,
          now: widget.now,
          userId: widget.user.id,
          focusActivityTitle: activityTitle,
          datesCache: overviewDatesCache(widget.overviewRepository, course.id),
          onOpenCalendar: () async => Navigator.of(context).pop(),
          onConnect: _openUFMGConnection,
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _openUpcomingEntry(
    CourseRecord course,
    AgendaEntry entry,
  ) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => GeneralCalendarPage(
          onOpenActivities:
              widget.ufmgSessionGateway is BackendAcademicWorkspaceGateway
              ? _openCourseActivities
              : null,
          onChangeSessionStatus: _changeSessionStatus,
          logger: widget.logger,
          onOpenCourse: _openCourseHub,
          courses: _courses,
          repository: widget.sessionRepository,
          location: tz.getLocation('America/Sao_Paulo'),
          now: widget.now,
          initialCourseId: course.id,
          initialDate: entry.startsAt,
          initialEntryId: entry.session?.id ?? entry.date?.id,
          datesByCourse: _datesByCourse,
          unavailableDateCourses: _unavailableDateCourses,
          initialSessionsByCourse: _sessionsByCourse,
        ),
      ),
    );
  }

  Future<void> _openGeneralCalendar() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        settings: const RouteSettings(name: 'agenda'),
        builder: (_) => GeneralCalendarPage(
          onOpenActivities:
              widget.ufmgSessionGateway is BackendAcademicWorkspaceGateway
              ? _openCourseActivities
              : null,
          onChangeSessionStatus: _changeSessionStatus,
          navigationState: _calendarNavigation,
          logger: widget.logger,
          onOpenCourse: _openCourseHub,
          overviewUpdates: _overviewUpdates,
          courses: _courses,
          datesByCourse: _datesByCourse,
          unavailableDateCourses: _unavailableDateCourses,
          repository: widget.sessionRepository,
          location: tz.getLocation('America/Sao_Paulo'),
          now: widget.now,
          initialSessionsByCourse: _usingOverviewSnapshot
              ? _sessionsByCourse
              : null,
        ),
      ),
    );
  }

  Future<void> _openUFMGConnection() async {
    final gateway = widget.ufmgSessionGateway;
    if (gateway == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => UFMGConnectionPage(
          onConnected: () => _ufmgSyncNotice = null,
          academicSync: _academicSync,
          gateway: gateway,
          logger: widget.logger,
          userId: widget.user.id,
          syncSchedule: widget.ufmgSyncSchedule,
          onOpenCourses: () async {
            if (_navigation != null) {
              await _navigation!.select(0);
            } else {
              Navigator.of(context).popUntil((route) => route.isFirst);
            }
          },
          onOpenCalendar: () async {
            if (_navigation != null) {
              await _navigation!.select(1);
              return;
            }
            Navigator.of(context).popUntil((route) => route.isFirst);
            await Future<void>.delayed(Duration.zero);
            if (mounted) await _openGeneralCalendar();
          },
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _openAbsenceDashboard() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        settings: const RouteSettings(name: 'absences'),
        builder: (_) => AbsenceDashboardPage(
          logger: widget.logger,
          onOpenCourse: _openCourseHub,
          courses: _courses,
          repository: widget.sessionRepository,
          location: tz.getLocation('America/Sao_Paulo'),
          now: widget.now,
          initialSessionsByCourse: _usingOverviewSnapshot
              ? _sessionsByCourse
              : null,
        ),
      ),
    );
    if (mounted) await _loadPastPendingCount(_courses);
  }

  void _selectDestination(int index) {
    final navigation = _navigation;
    unawaited(
      navigation == null ? _openDestination(index) : navigation.select(index),
    );
  }

  Future<void> _openDestination(int index) async {
    switch (index) {
      case 1:
        await _openGeneralCalendar();
      case 2:
        await _openAbsenceDashboard();
      case 3:
        await _openSettings();
    }
  }

  Future<void> _openSettings() async {
    _ensureAutomaticAttendance();
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        settings: const RouteSettings(name: 'settings'),
        builder: (_) => AppSettingsPage(
          user: widget.user,
          logger: widget.logger,
          attendance: _automaticAttendance,
          onCampusChanged: _rescheduleFromSettings,
          onAcademicAccount: widget.ufmgSessionGateway == null
              ? null
              : _openUFMGConnection,
          onSignOut: () async {
            Navigator.of(context).popUntil((route) => route.isFirst);
            await _signOut();
          },
        ),
      ),
    );
  }

  Future<void> _signOut() async {
    _checkpointSchedulingAllowed = false;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      try {
        await FirstCheckpointGateway.deactivate();
      } catch (error, stack) {
        unawaited(
          widget.logger
              .recordError(
                error,
                stack,
                context: 'first_checkpoint_logout_cleanup',
              )
              .catchError((Object e) {
                debugPrint(
                  'first_checkpoint_log_delivery_failed type=${e.runtimeType}',
                );
              }),
        );
      }
    }
    await widget.onSignOut();
  }

  Future<void> _openCheckpointPage() async {
    if (_checkpointOpen) return;
    _checkpointOpen = true;
    final operation = newCorrelationId('checkpoint_result');
    final watch = Stopwatch()..start();
    var stage = 'read_receipts';
    try {
      _ensureAutomaticAttendance();
      await _automaticAttendance?.refresh(afterCurrent: true);
      if (!mounted) return;
      final reports =
          List<Map<String, Object?>>.of(
                _automaticAttendance?.reports ?? const [],
              )
              .where(
                (r) => !const {
                  'scheduled',
                  'running',
                  'cancelled',
                  'superseded',
                }.contains(r['status']),
              )
              .toList()
            ..sort(
              (a, b) =>
                  ((b['delivery_updated_at_ms'] ?? b['scheduled_at_ms'] ?? 0)
                          as int)
                      .compareTo(
                        (a['delivery_updated_at_ms'] ??
                                a['scheduled_at_ms'] ??
                                0)
                            as int,
                      ),
            );
      final report = reports.firstOrNull;
      final course = _courses
          .where((c) => c.id == report?['course_id'])
          .firstOrNull;
      if (course == null) {
        stage = 'settings_fallback';
        emitOperationalEvent(widget.logger, 'checkpoint_result_fallback', {
          'operation_id': operation,
          'stage': stage,
          'reason': _automaticAttendance?.reportError == true
              ? 'receipt_read_failed'
              : report == null
              ? 'no_completed_receipt'
              : 'course_not_found',
          'receipt_count': reports.length,
          'duration_ms': watch.elapsedMilliseconds,
        });
        await _openSettings();
        return;
      }
      stage = 'read_sessions';
      final sessions =
          _sessionsByCourse[course.id] ??
          await widget.sessionRepository.listSessions(course.id);
      if (!mounted) return;
      emitOperationalEvent(widget.logger, 'checkpoint_result_opened', {
        'operation_id': operation,
        'stage': 'attendance',
        'duration_ms': watch.elapsedMilliseconds,
        'course_id': course.id,
        'course_code': course.code,
        'session_id': report!['session_id'].toString(),
        'receipt_count': reports.length,
      });
      stage = 'attendance_navigation';
      await Navigator.of(context).push<void>(
        MaterialPageRoute(
          settings: const RouteSettings(name: 'course'),
          builder: (_) => AttendancePage(
            courseId: course.id,
            courseCode: course.code,
            courseName: course.displayName,
            initialSessionId: report['session_id'] as String?,
            initialSessions: sessions,
            repository: widget.sessionRepository,
            logger: widget.logger,
            location: tz.getLocation('America/Sao_Paulo'),
            now: widget.now,
            attendanceEvaluator: widget.attendanceEvaluator,
            sessionGateway: widget.sessionGateway,
            sessionWritesEnabled: widget.sessionWritesEnabled,
            androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          ),
        ),
      );
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'checkpoint_notification_navigation',
        {
          'operation_id': operation,
          'stage': stage,
          'duration_ms': watch.elapsedMilliseconds,
        },
        failureCode: 'checkpoint_notification_navigation_failed',
      );
    } finally {
      _checkpointOpen = false;
    }
    if (mounted) await _load();
  }

  Future<void> _openPendingAttendance() async {
    final pending = _nextPastPending;
    if (pending == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AttendancePage(
          courseId: pending.course.id,
          courseCode: pending.course.code,
          courseName: pending.course.displayName,
          initialSessionId: pending.session.id,
          initialSessions: _usingOverviewSnapshot
              ? _sessionsByCourse[pending.course.id]
              : null,
          repository: widget.sessionRepository,
          logger: widget.logger,
          attendanceEvaluator: widget.attendanceEvaluator,
          sessionGateway: widget.sessionGateway,
          sessionWritesEnabled: widget.sessionWritesEnabled,
          androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          location: tz.getLocation('America/Sao_Paulo'),
          now: widget.now,
        ),
      ),
    );
    if (mounted) await _loadPastPendingCount(_courses);
  }

  Future<String?> _save(CourseRecord? existing, CourseInput input) async {
    final normalizedCode = input.code.toUpperCase();
    final duplicate = _courses.any(
      (course) =>
          course.id != existing?.id &&
          course.code.toUpperCase() == normalizedCode,
    );
    if (duplicate) {
      final mode = existing == null ? 'create' : 'update';
      unawaited(widget.logger.logEvent('course_${mode}_duplicate_code'));
      return 'Já existe uma disciplina com o código $normalizedCode.';
    }
    final identityOperationId = newCorrelationId('course_identity');
    final identityWatch = Stopwatch()..start();
    try {
      final timestamp = widget.now().toUtc();
      final defaultPeriod = AcademicPeriod.forTerm(input.term);
      final movesDefaultPeriod =
          existing != null &&
          existing.term != input.term &&
          _usesDefaultPeriod(existing);
      final course = CourseRecord(
        modality: input.modality,
        attendancePolicy: input.attendancePolicy,
        id: existing?.id ?? widget.idGenerator(),
        code: normalizedCode,
        name: input.name,
        nickname: input.nickname,
        workload: existing?.workload ?? 1,
        term: input.term,
        startsOn: existing == null || movesDefaultPeriod
            ? defaultPeriod.startsOn
            : existing.startsOn ?? defaultPeriod.startsOn,
        endsOn: existing == null || movesDefaultPeriod
            ? defaultPeriod.endsOn
            : existing.endsOn ?? defaultPeriod.endsOn,
        createdAt: existing?.createdAt ?? timestamp,
        updatedAt: timestamp,
      );
      if (existing == null) {
        setState(() {
          _courses = [..._courses, course]..sort(compareCourseNames);
          _savingIds.add(course.id);
        });
        unawaited(_persistCreatedCourse(course));
        return null;
      }
      emitOperationalEvent(widget.logger, 'course_identity_save_started', {
        'operation_id': identityOperationId,
        'stage': 'repository_write',
        'course_id': course.id,
        'course_code': course.code,
        'course_name': course.name,
        'has_nickname': course.nickname != null,
      });
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.courseUpdate,
        action: () => widget.repository.saveCourse(course),
      );
      emitOperationalEvent(widget.logger, 'course_identity_save_succeeded', {
        'operation_id': identityOperationId,
        'stage': 'repository_write',
        'duration_ms': identityWatch.elapsedMilliseconds,
        'course_id': course.id,
        'course_code': course.code,
        'course_name': course.name,
        'display_name': course.displayName,
      });
      if (mounted) {
        setState(() {
          _courses = [
            for (final item in _courses)
              if (item.id != course.id) item,
            course,
          ]..sort(compareCourseNames);
        });
        unawaited(
          CourseVisualHost.of(
            context,
            listen: false,
          )?.update(widget.user.id, _courses, logger: widget.logger),
        );
        unawaited(_loadPastPendingCount(_courses));
      }
      return null;
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_identity_save',
        {
          'operation_id': identityOperationId,
          'stage': 'repository_write',
          'course_id': existing?.id ?? 'new',
          'course_code': normalizedCode,
          'course_name': input.name,
          'duration_ms': identityWatch.elapsedMilliseconds,
        },
        failureCode: 'course_identity_save_failed',
      );
      final code = ErrorLogDetails.from(error).code;
      return code == null
          ? 'Não foi possível salvar a disciplina.'
          : 'Não foi possível salvar a disciplina. Código: $code.';
    }
  }

  Future<void> _persistCreatedCourse(CourseRecord course) async {
    try {
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.courseCreate,
        action: () => widget.repository.saveCourse(course),
      );
      // Cadastro confirmado: o rascunho dos mesmos valores é descartado.
      unawaited(_clearCourseDrafts());
    } catch (error) {
      // Gravação recusada: o formulário é preservado como rascunho local para
      // nova tentativa com os mesmos valores.
      final code = ErrorLogDetails.from(error).code;
      final draftPersisted = await _saveCourseDraft(course, code);
      if (!mounted) return;
      setState(() => _courses.removeWhere((item) => item.id == course.id));
      final diagnostic = code == null ? '' : ' Código: $code.';
      final message = draftPersisted
          ? 'Não foi possível salvar ${course.code}. O rascunho foi guardado para tentar de novo.$diagnostic'
          : 'Não foi possível salvar ${course.code}. Não foi possível guardar o rascunho neste aparelho.$diagnostic';
      _message(message);
    } finally {
      if (mounted) setState(() => _savingIds.remove(course.id));
    }
  }

  void _message(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..clearSnackBars()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _confirmDelete(CourseRecord course) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppDialogHeader(
          icon: Icons.delete_outline,
          title: 'Excluir disciplina?',
          subtitle: 'Esta ação também remove os dados vinculados.',
          destructive: true,
        ),
        content: Text(
          'Todos os horários e registros de ${course.displayName} também serão excluídos.',
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
            child: const Text('Excluir'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _deletingId = course.id);
    try {
      await widget.repository.deleteCourse(course.id);
      await _load();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Não foi possível excluir a disciplina.'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _deletingId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final firstName = widget.user.displayName?.trim().split(' ').first;
    Widget profileMenu() => IconButton(
      key: const Key('profile-menu'),
      tooltip: 'Ajustes',
      onPressed: _openSettings,
      icon: CircleAvatar(
        child: Text(
          firstName == null || firstName.isEmpty
              ? widget.user.email.characters.first.toUpperCase()
              : firstName.characters.first.toUpperCase(),
        ),
      ),
    );
    return AdaptiveAppShell(
      externalNavigation: _navigation != null,
      title: 'Início',
      selectedIndex: 0,
      onDestinationSelected: _selectDestination,
      actions: [profileMenu(), const SizedBox(width: 8)],
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 40),
        children: [
          LayoutBuilder(
            builder: (context, constraints) => Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        firstName == null || firstName.isEmpty
                            ? 'Suas disciplinas'
                            : 'Olá, $firstName',
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 4),
                      if (MediaQuery.textScalerOf(context).scale(14) <= 20)
                        Text(
                          _longDate(widget.now()),
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          if (_automaticAttendance != null &&
              _courses.any((c) => c.tracksAttendance))
            AttendanceSetupReminder(controller: _automaticAttendance!),
          if (_ufmgSyncNotice != null) ...[
            Card(
              key: const Key('ufmg-sync-notice'),
              color: Theme.of(context).colorScheme.tertiaryContainer,
              child: ListTile(
                leading: const Icon(Icons.sync_problem_outlined),
                title: Text(_ufmgSyncNotice!),
              ),
            ),
            const SizedBox(height: 16),
          ],
          if (_usingLocalCopy) ...[
            Card(
              key: const Key('offline-copy-banner'),
              color: Theme.of(context).colorScheme.secondaryContainer,
              child: const ListTile(
                leading: Icon(Icons.cloud_off_outlined),
                title: Text('Modo offline'),
                subtitle: Text('Exibindo a última cópia salva neste aparelho.'),
              ),
            ),
            const SizedBox(height: 16),
          ],
          if (_pastPendingCount > 0) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AGORA',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                        fontWeight: FontWeight.w700,
                        letterSpacing: .8,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Frequência pendente',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 12),
                    const Divider(),
                    ListTile(
                      key: const Key('past-attendance-pending-alert'),
                      contentPadding: EdgeInsets.zero,
                      leading: CourseMark(
                        code: _nextPastPending!.course.code,
                        size: 44,
                      ),
                      title: Text(
                        _pastPendingCount == 1
                            ? '1 aula anterior está sem frequência'
                            : '$_pastPendingCount aulas anteriores estão sem frequência',
                      ),
                      subtitle: Text(
                        'Mais recente: ${_nextPastPending!.course.displayName} • '
                        '${_shortDate(_nextPastPending!.session.startsAt)}',
                      ),
                      trailing: const Icon(Icons.arrow_forward_rounded),
                      onTap: _openPendingAttendance,
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
          ],
          LayoutBuilder(
            builder: (context, constraints) {
              final courses = Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _SectionHeader(onAdd: () => _openEditor()),
                  const SizedBox(height: 14),
                  _content(),
                ],
              );
              final dates = _UpcomingDates(
                datesByCourse: _datesByCourse,
                unavailableDateCourses: _unavailableDateCourses,
                courses: _courses,
                sessionsByCourse: _sessionsByCourse,
                now: widget.now(),
                onOpenCalendar: _openGeneralCalendar,
                onOpenEntry: _openUpcomingEntry,
              );
              if (constraints.maxWidth < 900) {
                final datesFirst = _courses.any(
                  (course) => courseAgenda(
                    course,
                    _sessionsByCourse[course.id] ?? [],
                    _datesByCourse[course.id] ?? [],
                  ).any((event) => !event.startsAt.isBefore(widget.now())),
                );
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: datesFirst
                      ? [dates, const SizedBox(height: 32), courses]
                      : [courses, const SizedBox(height: 32), dates],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(width: constraints.maxWidth * .34, child: dates),
                  const SizedBox(width: 44),
                  Expanded(child: courses),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  Widget _content() {
    if (_loading) {
      return const AppStateTransition(
        stateKey: ValueKey('courses-loading'),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    if (_loadFailed) {
      return AppStateTransition(
        stateKey: const ValueKey('courses-error'),
        child: _MessageState(
          icon: Icons.cloud_off_outlined,
          title: 'Não foi possível carregar suas disciplinas.',
          actionLabel: 'Tentar novamente',
          onAction: _load,
        ),
      );
    }
    if (_courses.isEmpty) {
      return AppStateTransition(
        stateKey: const ValueKey('courses-empty'),
        child: _MessageState(
          icon: Icons.menu_book_outlined,
          title: 'Nenhuma disciplina cadastrada',
          description: 'Adicione as matérias deste período para começar.',
          actionLabel: 'Adicionar disciplina',
          onAction: _openEditor,
        ),
      );
    }
    return AppStateTransition(
      stateKey: const ValueKey('courses-loaded'),
      child: Column(
        children: [
          for (var index = 0; index < _courses.length; index++) ...[
            if (index > 0) const SizedBox(height: 10),
            _CourseTile(
              course: _courses[index],
              sessions: _sessionsByCourse[_courses[index].id],
              dates: _datesByCourse[_courses[index].id] ?? [],
              now: widget.now(),
              deleting: _deletingId == _courses[index].id,
              saving: _savingIds.contains(_courses[index].id),
              onOpen: () => _openCourseHub(_courses[index]),
              onEdit: () => _openEditor(_courses[index]),
              onDelete: () => _confirmDelete(_courses[index]),
            ),
          ],
        ],
      ),
    );
  }
}

class _UpcomingDates extends StatelessWidget {
  const _UpcomingDates({
    required this.courses,
    required this.sessionsByCourse,
    required this.datesByCourse,
    required this.unavailableDateCourses,
    required this.now,
    required this.onOpenCalendar,
    required this.onOpenEntry,
  });

  final List<CourseRecord> courses;
  final Map<String, List<SessionRecord>> sessionsByCourse;
  final Map<String, List<PythonMoodleDate>> datesByCourse;
  final Set<String> unavailableDateCourses;
  final DateTime now;
  final VoidCallback onOpenCalendar;
  final void Function(CourseRecord, AgendaEntry) onOpenEntry;

  @override
  Widget build(BuildContext context) {
    final entries = <({CourseRecord course, AgendaEntry session})>[
      for (final course in courses)
        for (final event in courseAgenda(
          course,
          sessionsByCourse[course.id] ?? [],
          datesByCourse[course.id] ?? [],
        ))
          if (!event.startsAt.isBefore(now)) (course: course, session: event),
    ]..sort((a, b) => a.session.startsAt.compareTo(b.session.startsAt));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 8,
          children: [
            Text(
              'Próximas datas',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            TextButton(
              onPressed: onOpenCalendar,
              child: const Text('Ver calendário'),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (unavailableDateCourses.isNotEmpty)
          const Text(
            'Algumas datas não puderam ser atualizadas. Tente recarregar.',
          ),
        if (entries.isEmpty)
          Text(
            'Nenhuma avaliação ou entrega próxima.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          )
        else
          for (final entry in entries.take(3))
            _UpcomingDateTile(
              course: entry.course,
              session: entry.session,
              onOpen: () => onOpenEntry(entry.course, entry.session),
            ),
      ],
    );
  }
}

class _UpcomingDateTile extends StatelessWidget {
  const _UpcomingDateTile({
    required this.course,
    required this.session,
    required this.onOpen,
  });

  final VoidCallback onOpen;

  final CourseRecord course;
  final AgendaEntry session;

  @override
  Widget build(BuildContext context) {
    final date = tz.TZDateTime.from(
      session.startsAt,
      tz.getLocation('America/Sao_Paulo'),
    );
    const months = [
      'JAN',
      'FEV',
      'MAR',
      'ABR',
      'MAI',
      'JUN',
      'JUL',
      'AGO',
      'SET',
      'OUT',
      'NOV',
      'DEZ',
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        key: ValueKey(
          'upcoming-${course.id}-${session.session?.id ?? session.date?.id}',
        ),
        onTap: onOpen,
        borderRadius: BorderRadius.circular(16),
        child: Row(
          children: [
            Container(
              width: 54,
              height: 54,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: Theme.of(context).colorScheme.surface,
                border: Border.all(color: Theme.of(context).dividerColor),
                borderRadius: BorderRadius.circular(16),
              ),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    '${date.day}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  Text(
                    months[date.month - 1],
                    style: Theme.of(context).textTheme.labelSmall,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    compactAcademicTitle(session.title!),
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 2),
                  Text(
                    course.displayName,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.onAdd});

  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final textScaler = MediaQuery.textScalerOf(context);
        final stacksActions =
            constraints.maxWidth < 500 || textScaler.scale(14) > 20;
        final title = Text(
          'Minhas disciplinas',
          style: Theme.of(context).textTheme.titleLarge,
        );
        final action = TextButton.icon(
          key: const Key('add-course'),
          onPressed: onAdd,
          icon: const Icon(Icons.add_rounded),
          label: Text(
            constraints.maxWidth < 500 ? 'Adicionar' : 'Adicionar disciplina',
          ),
        );
        if (stacksActions) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [title, const SizedBox(height: 12), action],
          );
        }
        return Row(
          children: [
            Expanded(child: title),
            action,
          ],
        );
      },
    );
  }
}

class _CourseTile extends StatelessWidget {
  final List<SessionRecord>? sessions;
  final List<PythonMoodleDate> dates;
  final DateTime now;
  const _CourseTile({
    required this.sessions,
    required this.dates,
    required this.now,
    required this.course,
    required this.deleting,
    required this.saving,
    required this.onOpen,
    required this.onEdit,
    required this.onDelete,
  });

  final CourseRecord course;
  final bool deleting;
  final bool saving;
  final VoidCallback onOpen;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  List<Widget> _contextLabels() {
    final upcoming = courseAgenda(
      course,
      sessions!,
      dates,
      includeLessons: true,
    ).where((event) => !event.startsAt.isBefore(now)).toList();
    final summary = CourseAbsenceSummary.from(
      course,
      sessions!,
      now: now,
      location: tz.getLocation('America/Sao_Paulo'),
    );
    return [
      if (upcoming.isNotEmpty)
        Text('Próxima: ${_nextLabel(upcoming.first.startsAt)}'),
      if (course.tracksAttendance && summary.eligibleLessons > 0)
        Text('Saldo: ${summary.remainingAbsences} faltas'),
    ];
  }

  String _nextLabel(DateTime instant) {
    final local = tz.TZDateTime.from(
      instant,
      tz.getLocation('America/Sao_Paulo'),
    );
    return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')} ${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      clipBehavior: Clip.antiAlias,
      child: ListTile(
        key: Key('course-card-${course.id}'),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 18,
          vertical: 10,
        ),
        onTap: deleting || saving ? null : onOpen,
        leading: CourseMark(
          key: Key('course-mark-${course.id}'),
          code: course.code,
        ),
        title: Text(
          course.displayName,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 6,
                children: [
                  Text(course.code),
                  const Text('·'),
                  Text(course.term),
                ],
              ),
              if (sessions != null) ..._contextLabels(),
              if (!course.tracksAttendance) Text(course.policyLabel),
            ],
          ),
        ),
        trailing: deleting || saving
            ? const SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  PopupMenuButton<_CourseTileAction>(
                    key: ValueKey("course-actions-${course.code}"),
                    tooltip: 'Mais ações de ${course.displayName}',
                    onSelected: (action) {
                      switch (action) {
                        case _CourseTileAction.edit:
                          onEdit();
                        case _CourseTileAction.delete:
                          onDelete();
                      }
                    },
                    itemBuilder: (context) => const [
                      PopupMenuItem(
                        value: _CourseTileAction.edit,
                        child: ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(Icons.edit_outlined),
                          title: Text('Editar'),
                        ),
                      ),
                      PopupMenuItem(
                        value: _CourseTileAction.delete,
                        child: ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(Icons.delete_outline),
                          title: Text('Excluir'),
                        ),
                      ),
                    ],
                  ),
                  Icon(
                    Icons.chevron_right_rounded,
                    color: Theme.of(context).dividerColor,
                  ),
                ],
              ),
      ),
    );
  }
}

class _MessageState extends StatelessWidget {
  const _MessageState({
    required this.icon,
    required this.title,
    required this.actionLabel,
    required this.onAction,
    this.description,
  });

  final IconData icon;
  final String title;
  final String? description;
  final String actionLabel;
  final VoidCallback onAction;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 48),
    child: Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 48, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 16),
          Text(title, style: Theme.of(context).textTheme.titleMedium),
          if (description != null) ...[
            const SizedBox(height: 6),
            Text(description!, textAlign: TextAlign.center),
          ],
          const SizedBox(height: 20),
          OutlinedButton(onPressed: onAction, child: Text(actionLabel)),
        ],
      ),
    ),
  );
}

String _newCourseId() {
  final random = Random.secure();
  return '${DateTime.now().toUtc().microsecondsSinceEpoch.toRadixString(36)}-'
      '${random.nextInt(1 << 30).toRadixString(36)}';
}

String academicTermFor(DateTime date) => AcademicPeriod.current(date).term;

bool _usesDefaultPeriod(CourseRecord course) {
  final defaultPeriod = AcademicPeriod.forTerm(course.term);
  return course.startsOn == null ||
      course.endsOn == null ||
      (course.startsOn == defaultPeriod.startsOn &&
          course.endsOn == defaultPeriod.endsOn);
}

final class _PendingAttendance {
  const _PendingAttendance(this.course, this.session);

  final CourseRecord course;
  final SessionRecord session;
}

String _longDate(DateTime value) {
  const weekdays = [
    'segunda-feira',
    'terça-feira',
    'quarta-feira',
    'quinta-feira',
    'sexta-feira',
    'sábado',
    'domingo',
  ];
  const months = [
    'janeiro',
    'fevereiro',
    'março',
    'abril',
    'maio',
    'junho',
    'julho',
    'agosto',
    'setembro',
    'outubro',
    'novembro',
    'dezembro',
  ];
  return '${weekdays[value.weekday - 1]}, ${value.day} de ${months[value.month - 1]}';
}

String _shortDate(DateTime value) {
  final local = tz.TZDateTime.from(value, tz.getLocation('America/Sao_Paulo'));
  return '${local.day.toString().padLeft(2, '0')}/'
      '${local.month.toString().padLeft(2, '0')}/${local.year}';
}

Future<List<PythonMoodleDate>?> Function()? overviewDatesCache(
  AcademicOverviewRepository? repository,
  String courseId,
) {
  if (repository is! LocalFirstAcademicOverviewRepository) return null;
  final local = repository;
  return () async =>
      (await local.loadCachedOverview())?.datesByCourse[courseId];
}
