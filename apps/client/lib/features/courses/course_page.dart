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
import '../../data/python_overview_repository.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/adaptive_app_shell.dart';
import '../../design/app_feedback.dart';
import '../../design/app_motion.dart';
import '../../design/course_identity.dart';
import '../../observability/error_log_details.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../attendance/absence_dashboard_page.dart';
import '../attendance/attendance_page.dart';
import '../attendance/attendance_permissions_page.dart';
import '../schedule/general_calendar_page.dart';
import '../ufmg/ufmg_connection_page.dart';
import '../ufmg/academic_sync_controller.dart';
import '../ufmg/academic_sync_banner.dart';
import 'course_editor_dialog.dart';
import 'course_hub_page.dart';

typedef CourseIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

enum _ProfileAction { ufmgAccount, permissions, signOut }

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
    this.overviewRepository,
    this.scheduleReadsEnabled = true,
    this.scheduleWritesEnabled = false,
    this.sessionWritesEnabled = false,
    this.overviewReadsEnabled = false,
    this.androidOfflineQueueEnabled = false,
    this.attendancePermissions,
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
  final AcademicOverviewRepository? overviewRepository;
  final bool scheduleReadsEnabled;
  final bool scheduleWritesEnabled;
  final bool sessionWritesEnabled;
  final bool overviewReadsEnabled;
  final bool androidOfflineQueueEnabled;
  final AttendancePermissionsGateway? attendancePermissions;
  final CourseIdGenerator idGenerator;
  final CurrentTime now;

  @override
  State<CoursePage> createState() => _CoursePageState();
}

class _CoursePageState extends State<CoursePage> {
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
  OverlayEntry? _syncIndicator;
  bool _academicSyncWasRunning = false;
  final _overviewUpdates = ValueNotifier<AcademicOverviewSnapshot?>(null);

  @override
  void initState() {
    super.initState();
    if (widget.ufmgSessionGateway
        case final BackendAcademicSyncProgressGateway gateway) {
      _academicSync = AcademicSyncController(
        gateway: gateway,
        logger: widget.logger,
      )..addListener(_onAcademicSyncChanged);
    }
    _load();
  }

  void _onAcademicSyncChanged() {
    final running = _academicSync!.isRunning;
    if (_academicSyncWasRunning && !running) unawaited(_load());
    _academicSyncWasRunning = running;
    if (_syncIndicator == null && _academicSync!.visible) {
      _syncIndicator = OverlayEntry(
        builder: (context) => Positioned(
          left: 0,
          right: 0,
          bottom: MediaQuery.sizeOf(context).width < 840 ? 80 : 12,
          child: AcademicSyncBanner(
            controller: _academicSync!,
            onReview: () => unawaited(_openUFMGConnection()),
          ),
        ),
      );
      Overlay.of(context, rootOverlay: true).insert(_syncIndicator!);
    }
  }

  @override
  void dispose() {
    _syncIndicator?.remove();
    _syncIndicator?.dispose();
    _academicSync?.removeListener(_onAcademicSyncChanged);
    _academicSync?.dispose();
    _overviewUpdates.dispose();
    super.dispose();
  }

  Future<void> _load() async {
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
      courses.sort((left, right) => left.code.compareTo(right.code));
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
      _overviewUpdates.value = AcademicOverviewSnapshot(
        courses: _courses,
        sessionsByCourse: _sessionsByCourse,
        datesByCourse: _datesByCourse,
        unavailableDateCourses: _unavailableDateCourses,
        isLocalCopy: _usingLocalCopy,
      );
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
    }
  }

  void _startAutomaticUFMGSync() {
    if (_automaticUFMGSyncStarted ||
        widget.ufmgSessionGateway == null ||
        widget.ufmgSyncSchedule == null) {
      return;
    }
    _automaticUFMGSyncStarted = true;
    unawaited(_runAutomaticUFMGSync());
  }

  Future<void> _runAutomaticUFMGSync() async {
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
    final courses = snapshot.courses.toList()
      ..sort((left, right) => left.code.compareTo(right.code));
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
      unawaited(
        widget.logger.logEvent(
          'course_expiration_delete_started',
          parameters: {'term': course.term},
        ),
      );
      try {
        await widget.repository.deleteCourse(course.id);
        courses.remove(course);
        unawaited(
          widget.logger.logEvent(
            'course_expiration_delete_succeeded',
            parameters: {'term': course.term},
          ),
        );
      } catch (error, stackTrace) {
        unawaited(
          widget.logger.recordError(
            error,
            stackTrace,
            context: 'course_expiration_delete',
            parameters: {'term': course.term},
          ),
        );
      }
    }
  }

  Future<void> _openEditor([CourseRecord? course]) async {
    final mode = course == null ? 'create' : 'update';
    final policy = AcademicPeriodPolicy(widget.now());
    unawaited(widget.logger.logEvent('course_${mode}_editor_opened'));
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => CourseEditorDialog(
        course: course,
        initialTerm: course?.term ?? policy.current.term,
        allowedTerms: policy.allowedTerms,
        onSave: (input) => _save(course, input),
        onValidationFailed: () => unawaited(
          widget.logger.logEvent('course_${mode}_validation_failed'),
        ),
      ),
    );
  }

  Future<void> _openCourseHub(CourseRecord course) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (context) => CourseHubPage(
          overviewUpdates: _overviewUpdates,
          refreshOverview: widget.overviewReadsEnabled
              ? () async {
                  await _load();
                  if (_loadFailed) throw StateError('overview_refresh_failed');
                }
              : null,
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

  Future<void> _openGeneralCalendar() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => GeneralCalendarPage(
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
          academicSync: _academicSync,
          gateway: gateway,
          logger: widget.logger,
          userId: widget.user.id,
          syncSchedule: widget.ufmgSyncSchedule,
          onOpenCourses: () async {
            Navigator.of(context).pop();
          },
          onOpenCalendar: () async {
            Navigator.of(context).pop();
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
        builder: (_) => AbsenceDashboardPage(
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
    switch (index) {
      case 0:
        return;
      case 1:
        unawaited(_openGeneralCalendar());
        return;
      case 2:
        unawaited(_openAbsenceDashboard());
        return;
    }
  }

  Future<void> _selectProfileAction(_ProfileAction action) async {
    switch (action) {
      case _ProfileAction.ufmgAccount:
        await _openUFMGConnection();
      case _ProfileAction.permissions:
        await runAuditedOperation(
          logger: widget.logger,
          operation: AuditedOperation.attendancePermissionsOpen,
          action: () => Navigator.of(context).push<void>(
            MaterialPageRoute(
              builder: (_) => AttendancePermissionsPage(
                gateway:
                    widget.attendancePermissions ??
                    const AndroidAttendancePermissions(),
                logger: widget.logger,
              ),
            ),
          ),
        );
      case _ProfileAction.signOut:
        await widget.onSignOut();
    }
  }

  Future<void> _openPendingAttendance() async {
    final pending = _nextPastPending;
    if (pending == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AttendancePage(
          courseId: pending.course.id,
          courseCode: pending.course.code,
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
          _courses = [..._courses, course]
            ..sort((left, right) => left.code.compareTo(right.code));
          _savingIds.add(course.id);
        });
        unawaited(_persistCreatedCourse(course));
        return null;
      }
      await runAuditedOperation<void>(
        logger: widget.logger,
        operation: AuditedOperation.courseUpdate,
        action: () => widget.repository.saveCourse(course),
      );
      if (mounted) {
        setState(() {
          _courses = [
            for (final item in _courses)
              if (item.id != course.id) item,
            course,
          ]..sort((left, right) => left.code.compareTo(right.code));
        });
        unawaited(_loadPastPendingCount(_courses));
      }
      return null;
    } catch (error) {
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
    } catch (error) {
      if (!mounted) return;
      setState(() => _courses.removeWhere((item) => item.id == course.id));
      final code = ErrorLogDetails.from(error).code;
      final diagnostic = code == null ? '' : ' Código: $code.';
      _message(
        'Não foi possível salvar ${course.code}. A disciplina foi removida.'
        '$diagnostic',
      );
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
          'Todos os horários e registros de ${course.code} também serão excluídos.',
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
    final enlargedText = MediaQuery.textScalerOf(context).scale(14) > 20;
    Widget profileMenu() => PopupMenuButton<_ProfileAction>(
      key: const Key('profile-menu'),
      tooltip: 'Perfil e configurações',
      onSelected: (action) => unawaited(_selectProfileAction(action)),
      icon: CircleAvatar(
        child: Text(
          firstName == null || firstName.isEmpty
              ? widget.user.email.characters.first.toUpperCase()
              : firstName.characters.first.toUpperCase(),
        ),
      ),
      itemBuilder: (context) => [
        if (widget.attendancePermissions != null ||
            (!kIsWeb && defaultTargetPlatform == TargetPlatform.android))
          const PopupMenuItem(
            key: Key('profile-permissions'),
            value: _ProfileAction.permissions,
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.settings_outlined),
              title: Text('Permissões do aplicativo'),
            ),
          ),
        if (widget.ufmgSessionGateway != null)
          const PopupMenuItem(
            key: Key('profile-ufmg-account'),
            value: _ProfileAction.ufmgAccount,
            child: ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.account_balance_outlined),
              title: Text('Conta acadêmica UFMG'),
            ),
          ),
        const PopupMenuItem(
          value: _ProfileAction.signOut,
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.logout),
            title: Text('Sair'),
          ),
        ),
      ],
    );
    return AdaptiveAppShell(
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
                      if (!enlargedText) ...[
                        Text(
                          _longDate(widget.now()),
                          style: Theme.of(context).textTheme.labelMedium
                              ?.copyWith(
                                color: Theme.of(
                                  context,
                                ).colorScheme.onSurfaceVariant,
                                fontWeight: FontWeight.w700,
                                letterSpacing: .4,
                              ),
                        ),
                        const SizedBox(height: 6),
                      ],
                      Text(
                        firstName == null || firstName.isEmpty
                            ? 'Suas disciplinas'
                            : 'Olá, $firstName',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                      if (!enlargedText) ...[
                        const SizedBox(height: 4),
                        Text(
                          widget.user.email,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(
                                color: Theme.of(
                                  context,
                                ).colorScheme.onSurfaceVariant,
                              ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
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
                        'Mais recente: ${_nextPastPending!.course.code} • '
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
  });

  final List<CourseRecord> courses;
  final Map<String, List<SessionRecord>> sessionsByCourse;
  final Map<String, List<PythonMoodleDate>> datesByCourse;
  final Set<String> unavailableDateCourses;
  final DateTime now;
  final VoidCallback onOpenCalendar;

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
            _UpcomingDateTile(course: entry.course, session: entry.session),
      ],
    );
  }
}

class _UpcomingDateTile extends StatelessWidget {
  const _UpcomingDateTile({required this.course, required this.session});

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
                  session.title!,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 2),
                Text(
                  course.code,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
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
        final action = FilledButton.icon(
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
  const _CourseTile({
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
          course.name,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(course.code),
              if (!course.tracksAttendance) Text(course.policyLabel),
              const SizedBox(height: 2),
              Text(
                course.term,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
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
                    tooltip: 'Mais ações de ${course.code}',
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
