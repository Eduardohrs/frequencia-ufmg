import 'package:flutter/foundation.dart';
import '../../data/python_overview_repository.dart';
import '../../data/academic_agenda.dart';
import 'dart:async';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../backend/python_backend_transport.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/calendar_status.dart';
import '../../data/ufmg_sync_schedule.dart';
import '../../design/attendance_progress_bar.dart';
import '../../design/app_theme.dart';
import '../../design/course_identity.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';
import '../attendance/absence_dashboard_page.dart';
import '../activities/course_workspace_page.dart';
import '../attendance/attendance_page.dart';
import '../schedule/course_schedule_page.dart';
import '../schedule/general_calendar_page.dart';
import '../ufmg/ufmg_connection_page.dart';
import '../ufmg/academic_sync_controller.dart';

class CourseHubPage extends StatefulWidget {
  const CourseHubPage({
    required this.course,
    required this.allCourses,
    required this.courseRepository,
    required this.meetingRepository,
    required this.sessionRepository,
    required this.logger,
    required this.now,
    this.initialSessionsByCourse,
    this.calendarNavigation,
    this.onOpenCourse,
    this.overviewUpdates,
    this.refreshOverview,
    this.workspaceGateway,
    this.datesByCourse = const {},
    this.unavailableDateCourses = const {},
    this.attendanceEvaluator,
    this.scheduleGateway,
    this.sessionGateway,
    this.ufmgSessionGateway,
    this.ufmgSyncSchedule,
    this.userId,
    this.academicSync,
    this.scheduleReadsEnabled = true,
    this.scheduleWritesEnabled = false,
    this.sessionWritesEnabled = false,
    this.androidOfflineQueueEnabled = false,
    super.key,
  });

  final ValueListenable<AcademicOverviewSnapshot?>? overviewUpdates;
  final Future<void> Function()? refreshOverview;
  final BackendAcademicWorkspaceGateway? workspaceGateway;
  final CalendarNavigationState? calendarNavigation;
  final Future<void> Function(CourseRecord)? onOpenCourse;
  final CourseRecord course;
  final List<CourseRecord> allCourses;
  final CourseRepository courseRepository;
  final MeetingRepository meetingRepository;
  final SessionRepository sessionRepository;
  final AppLogger logger;
  final DateTime Function() now;
  final Map<String, List<SessionRecord>>? initialSessionsByCourse;
  final Map<String, List<PythonMoodleDate>> datesByCourse;
  final Set<String> unavailableDateCourses;
  final BackendAttendanceEvaluator? attendanceEvaluator;
  final BackendScheduleGateway? scheduleGateway;
  final BackendSessionGateway? sessionGateway;
  final BackendUFMGSessionGateway? ufmgSessionGateway;
  final UFMGSyncScheduleGateway? ufmgSyncSchedule;
  final String? userId;
  final AcademicSyncController? academicSync;
  final bool scheduleReadsEnabled;
  final bool scheduleWritesEnabled;
  final bool sessionWritesEnabled;
  final bool androidOfflineQueueEnabled;

  @override
  State<CourseHubPage> createState() => _CourseHubPageState();
}

class _CourseHubPageState extends State<CourseHubPage> {
  static final _location = tz.getLocation('America/Sao_Paulo');
  List<SessionRecord> _sessions = const [];
  List<MeetingRecord> _meetings = const [];
  PythonMoodleCourseContent? _materials;
  bool _sessionsFailed = false;
  bool _courseFailed = false;
  bool _meetingsFailed = false;
  bool _loading = true;
  bool _materialsFailed = false;
  bool _materialsLoading = false;
  int _generation = 0;
  bool _localSessionsRefreshed = false;
  late CourseRecord _course;

  @override
  void initState() {
    super.initState();
    _course = widget.course;
    widget.overviewUpdates?.addListener(_overviewChanged);
    _load();
  }

  @override
  void dispose() {
    widget.overviewUpdates?.removeListener(_overviewChanged);
    super.dispose();
  }

  void _overviewChanged() {
    final snapshot = widget.overviewUpdates?.value;
    if (snapshot == null) return;
    setState(() {
      for (final course in snapshot.courses) {
        if (course.id == _course.id) _course = course;
      }
      final sessions = snapshot.sessionsByCourse[_course.id];
      if (sessions != null) {
        _localSessionsRefreshed = false;
        _sessions = List.of(sessions)
          ..sort((a, b) => a.startsAt.compareTo(b.startsAt));
        _sessionsFailed = false;
      }
    });
  }

  Map<String, List<PythonMoodleDate>> get _datesByCourse =>
      widget.overviewUpdates?.value?.datesByCourse ?? widget.datesByCourse;
  Set<String> get _unavailableDateCourses =>
      widget.overviewUpdates?.value?.unavailableDateCourses ??
      widget.unavailableDateCourses;

  Future<void> _readSection<T>(
    String stage,
    Future<T> Function() read,
    void Function(T) adopt,
    void Function() fail,
    int generation,
  ) async {
    final watch = Stopwatch()..start();
    final operationId = newCorrelationId('course_hub_$stage');
    final fields = <String, Object>{
      'operation_id': operationId,
      'screen': 'course',
      'course_id': _course.id,
      'course_code': _course.code,
      'stage': stage,
    };
    emitOperationalEvent(widget.logger, 'course_hub_read_started', fields);
    try {
      final result = await read();
      if (!mounted || generation != _generation) {
        emitOperationalEvent(widget.logger, 'course_hub_read_succeeded', {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
          'applied_to_view': false,
        });
        return;
      }
      setState(() => adopt(result));
      emitOperationalEvent(widget.logger, 'course_hub_read_succeeded', {
        ...fields,
        'applied_to_view': true,
        'duration_ms': watch.elapsedMilliseconds,
      });
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_hub_${stage}_failed',
        {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
          'retained_previous': true,
        },
        failureCode: 'course_hub_read_failed',
      );
      if (mounted && generation == _generation) setState(fail);
    }
  }

  Future<void> _load({bool refresh = false}) async {
    final generation = ++_generation;
    final initial = refresh
        ? null
        : widget.initialSessionsByCourse?[_course.id];
    if (initial != null) _sessions = List.of(initial);
    // The catalog is independent: it must not block attendance and timetable.
    unawaited(_loadMaterials());
    await Future.wait([
      if (refresh && widget.refreshOverview != null)
        _readSection(
          'overview',
          widget.refreshOverview!,
          (_) => _overviewChanged(),
          () => _sessionsFailed = true,
          generation,
        )
      else ...[
        if (initial == null)
          _readSection(
            'sessions',
            () => widget.sessionRepository.listSessions(_course.id),
            (value) {
              _sessions = List.of(value)
                ..sort((a, b) => a.startsAt.compareTo(b.startsAt));
              _sessionsFailed = false;
              _localSessionsRefreshed = refresh;
            },
            () => _sessionsFailed = true,
            generation,
          ),
        if (refresh)
          _readSection(
            'course',
            widget.courseRepository.listCourses,
            (value) {
              for (final course in value) {
                if (course.id == _course.id) _course = course;
              }
              _courseFailed = false;
            },
            () => _courseFailed = true,
            generation,
          ),
      ],
      _readSection(
        'meetings',
        () => widget.meetingRepository.listMeetings(_course.id),
        (value) {
          _meetings = List.of(value)
            ..sort((a, b) {
              final weekday = a.weekday.compareTo(b.weekday);
              return weekday != 0
                  ? weekday
                  : a.startMinutes.compareTo(b.startMinutes);
            });
          _meetingsFailed = false;
        },
        () => _meetingsFailed = true,
        generation,
      ),
    ]);
    if (!mounted || generation != _generation) return;
    recordAgendaPresentation(
      logger: widget.logger,
      screen: 'course',
      importedCount: _datesByCourse[_course.id]?.length ?? 0,
      entryCount: courseAgenda(
        _course,
        _sessions,
        _datesByCourse[_course.id] ?? [],
      ).length,
      unavailableCourses: _unavailableDateCourses.where(
        (id) => id == _course.id,
      ),
    );
    setState(() => _loading = false);
  }

  int _catalogGeneration = 0;
  Future<void> _loadMaterials() async {
    final gateway = widget.ufmgSessionGateway;
    if (gateway == null) return;
    final generation = ++_catalogGeneration;
    setState(() => _materialsLoading = true);
    final watch = Stopwatch()..start();
    final fields = <String, Object>{
      'operation_id': newCorrelationId('course_catalog'),
      'screen': 'course',
      'course_id': _course.id,
      'course_code': _course.code,
      'stage': 'catalog',
    };
    emitOperationalEvent(widget.logger, 'course_hub_catalog_started', fields);
    try {
      final catalog = await gateway.listMoodleMaterialCatalog();
      if (!mounted || generation != _catalogGeneration) {
        emitOperationalEvent(widget.logger, 'course_hub_catalog_succeeded', {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
          'applied_to_view': false,
        });
        return;
      }
      PythonMoodleCourseContent? match;
      for (final item in catalog.courses) {
        if (_matchesCourse(item)) {
          match = item;
          break;
        }
      }
      setState(() {
        _materials = match;
        _materialsFailed = false;
      });
      emitOperationalEvent(widget.logger, 'course_hub_catalog_succeeded', {
        ...fields,
        'duration_ms': watch.elapsedMilliseconds,
        'material_count': match?.candidates.length ?? 0,
        'applied_to_view': true,
      });
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'course_hub_catalog_failed',
        {
          ...fields,
          'duration_ms': watch.elapsedMilliseconds,
          'retained_previous': _materials != null,
        },
        failureCode: 'course_catalog_read_failed',
      );
      if (mounted && generation == _catalogGeneration) {
        setState(() => _materialsFailed = true);
      }
    } finally {
      if (mounted && generation == _catalogGeneration) {
        setState(() => _materialsLoading = false);
      }
    }
  }

  bool _matchesCourse(PythonMoodleCourseContent item) =>
      item.courseId == _course.id ||
      (item.courseCode.toUpperCase() == _course.code.toUpperCase() &&
          item.term == _course.term);

  void _logNavigation(String action) =>
      emitOperationalEvent(widget.logger, 'course_hub_navigation', {
        'operation_id': newCorrelationId('course_navigation'),
        'screen': 'course',
        'action': action,
        'course_id': _course.id,
        'course_code': _course.code,
      });

  Future<void> _openAttendance() async {
    _logNavigation('attendance');
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AttendancePage(
          courseId: _course.id,
          courseCode: _course.code,
          repository: widget.sessionRepository,
          logger: widget.logger,
          location: _location,
          now: widget.now,
          attendanceEvaluator: widget.attendanceEvaluator,
          sessionGateway: widget.sessionGateway,
          sessionWritesEnabled: widget.sessionWritesEnabled,
          androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          initialSessions: _sessions,
          initialSessionId: _firstPending?.id,
        ),
      ),
    );
    if (mounted) await _reloadSessions();
  }

  Future<void> _reloadSessions() => _load(refresh: true);

  SessionRecord? get _firstPending {
    if (!_course.tracksAttendance) return null;
    final today = tz.TZDateTime.from(widget.now(), _location);
    for (final session in _sessions.reversed) {
      final local = tz.TZDateTime.from(session.startsAt, _location);
      final beforeToday = DateTime(
        local.year,
        local.month,
        local.day,
      ).isBefore(DateTime(today.year, today.month, today.day));
      if (beforeToday &&
          session.calendarStatus.requiresAttendance &&
          session.absences == null) {
        return session;
      }
    }
    return null;
  }

  Future<void> _openCalendar([AgendaEntry? event]) async {
    _logNavigation('calendar');
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => GeneralCalendarPage(
          navigationState: widget.calendarNavigation,
          onOpenCourse: widget.onOpenCourse,
          initialDate: event?.startsAt,
          logger: widget.logger,
          overviewUpdates: _localSessionsRefreshed
              ? null
              : widget.overviewUpdates,
          courses: [
            for (final item
                in widget.overviewUpdates?.value?.courses ?? widget.allCourses)
              item.id == _course.id ? _course : item,
          ],
          datesByCourse: _datesByCourse,
          unavailableDateCourses: _unavailableDateCourses,
          repository: widget.sessionRepository,
          location: _location,
          now: widget.now,
          initialCourseId: _course.id,
          initialSessionsByCourse: {
            ...?widget.initialSessionsByCourse,
            _course.id: _sessions,
          },
        ),
      ),
    );
  }

  Future<void> _openSchedule() async {
    _logNavigation('schedule');
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => CourseSchedulePage(
          course: _course,
          courseRepository: widget.courseRepository,
          repository: widget.meetingRepository,
          sessionRepository: widget.sessionRepository,
          logger: widget.logger,
          attendanceEvaluator: widget.attendanceEvaluator,
          scheduleGateway: widget.scheduleGateway,
          scheduleReadsEnabled: widget.scheduleReadsEnabled,
          sessionGateway: widget.sessionGateway,
          scheduleWritesEnabled: widget.scheduleWritesEnabled,
          sessionWritesEnabled: widget.sessionWritesEnabled,
          androidOfflineQueueEnabled: widget.androidOfflineQueueEnabled,
          initialSessionsByCourse: widget.initialSessionsByCourse,
          allCourses: widget.allCourses,
          datesByCourse: _datesByCourse,
          unavailableDateCourses: _unavailableDateCourses,
          allCourseIds: widget.allCourses.map((item) => item.id),
        ),
      ),
    );
    if (mounted) await _load(refresh: true);
  }

  BackendAcademicWorkspaceGateway? get _workspaceGateway {
    if (widget.workspaceGateway case final gateway?) return gateway;
    if (widget.ufmgSessionGateway
        case BackendAcademicWorkspaceGateway gateway) {
      return gateway;
    }
    return null;
  }

  Future<void> _openWorkspace(BackendAcademicWorkspaceGateway gateway) async {
    _logNavigation('activities_and_plan');
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => CourseWorkspacePage(
          course: _course,
          gateway: gateway,
          logger: widget.logger,
          now: widget.now,
          userId: widget.userId,
          onConnect: widget.ufmgSessionGateway == null
              ? null
              : () => _openMaterials(manageConnection: true),
        ),
      ),
    );
    if (mounted) await _load(refresh: true);
  }

  Future<void> _openMaterials({bool manageConnection = false}) async {
    _logNavigation('materials');
    final gateway = widget.ufmgSessionGateway!;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => UFMGConnectionPage(
          academicSync: widget.academicSync,
          gateway: gateway,
          logger: widget.logger,
          userId: widget.userId,
          syncSchedule: widget.ufmgSyncSchedule,
          materialCourseId: manageConnection ? null : _course.id,
          materialCourseCode: manageConnection ? null : _course.code,
          materialCourseTerm: manageConnection ? null : _course.term,
        ),
      ),
    );
    if (mounted) await _load(refresh: true);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      toolbarHeight: 64,
      leadingWidth: 76,
      leading: Padding(
        padding: const EdgeInsets.only(left: 18, top: 8, bottom: 8),
        child: Tooltip(
          message: 'Voltar',
          child: DecoratedBox(
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.secondaryContainer,
              shape: BoxShape.circle,
            ),
            child: MediaQuery.withClampedTextScaling(
              maxScaleFactor: 1,
              child: CupertinoNavigationBarBackButton(
                previousPageTitle: '',
                color: Theme.of(context).colorScheme.onSecondaryContainer,
                onPressed: () => Navigator.of(context).maybePop(),
              ),
            ),
          ),
        ),
      ),
    ),
    body: SafeArea(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 780;
          return Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1080),
              child: SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                  compact ? 18 : 36,
                  compact ? 24 : 42,
                  compact ? 18 : 36,
                  56,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (_sessionsFailed || _meetingsFailed || _courseFailed)
                      TextButton(
                        key: const Key('course-hub-retry'),
                        onPressed: () => _load(refresh: true),
                        child: const Text(
                          'Atualização incompleta. Tentar novamente',
                        ),
                      ),

                    _courseIdentity(compact),
                    if (_firstPending != null) ...[
                      const SizedBox(height: 24),
                      _pendingAction(compact),
                    ],
                    SizedBox(height: compact ? 28 : 34),
                    _courseContent(compact),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    ),
  );

  Widget _courseIdentity(bool compact) => Row(
    key: const Key('course-hub-identity'),
    children: [
      CourseMark(
        key: const Key('course-hub-course-mark'),
        code: _course.code,
        size: compact ? 50 : 62,
      ),
      SizedBox(width: compact ? 12 : 18),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(
              spacing: 0,
              runSpacing: 2,
              children: [
                Text(
                  _course.code,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  ),
                ),
                Text(
                  ' · ${_course.term.replaceFirst('-', '/')}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                    letterSpacing: .6,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              _course.name,
              maxLines: compact ? 2 : 1,
              overflow: TextOverflow.ellipsis,
              style:
                  (compact
                          ? Theme.of(context).textTheme.headlineSmall
                          : Theme.of(context).textTheme.headlineMedium)
                      ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    ],
  );

  Widget _pendingAction(bool compact) {
    final pending = _firstPending!;
    return Container(
      key: const Key('course-hub-pending-action'),
      padding: const EdgeInsets.all(16),
      decoration: _panelDecoration(context, radius: 18),
      child: compact
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _pendingCopy(pending),
                const SizedBox(height: 16),
                FilledButton(
                  key: const Key('course-hub-open-attendance'),
                  onPressed: _openAttendance,
                  child: const Text('Resolver agora'),
                ),
              ],
            )
          : Row(
              children: [
                Expanded(child: _pendingCopy(pending)),
                const SizedBox(width: 20),
                FilledButton(
                  key: const Key('course-hub-open-attendance'),
                  onPressed: _openAttendance,
                  child: const Text('Resolver agora'),
                ),
              ],
            ),
    );
  }

  Widget _pendingCopy(SessionRecord pending) => Row(
    children: [
      Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Theme.of(context).colorScheme.error,
          boxShadow: [
            BoxShadow(
              color: Theme.of(context).colorScheme.error.withValues(alpha: .15),
              spreadRadius: 6,
            ),
          ],
        ),
      ),
      const SizedBox(width: 14),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Frequência pendente',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 3),
            Text(
              _pendingDescription(pending),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ),
      ),
    ],
  );

  Widget _courseContent(bool compact) {
    final main = Column(
      children: [
        _frequencySection(),
        const SizedBox(height: 28),
        _agendaSection(),
        if (_workspaceGateway case final gateway?) ...[
          const SizedBox(height: 20),
          ListTile(
            key: const Key('course-hub-workspace'),
            contentPadding: const EdgeInsets.symmetric(horizontal: 20),
            title: const Text('Atividades e plano de ensino'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => _openWorkspace(gateway),
          ),
        ],
      ],
    );
    final side = Column(
      children: [
        if (_course.modality != CourseModality.online) _scheduleSection(),
        const SizedBox(height: 28),
        _materialsSection(),
      ],
    );
    return KeyedSubtree(
      key: const Key('course-hub-section-grid'),
      child: compact
          ? Column(children: [main, const SizedBox(height: 28), side])
          : Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 165, child: main),
                const SizedBox(width: 28),
                Expanded(flex: 80, child: side),
              ],
            ),
    );
  }

  Widget _frequencySection() {
    if (!_course.tracksAttendance) {
      return _Panel(
        key: const Key('course-hub-frequency'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              _course.policyLabel,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            const Text(
              'Frequência: não se aplica. Atividades e materiais continuam disponíveis.',
            ),
          ],
        ),
      );
    }
    final summary = CourseAbsenceSummary.from(
      _course,
      _sessions,
      now: widget.now(),
      location: _location,
    );
    return _Panel(
      key: const Key('course-hub-frequency'),
      child: Column(
        key: const Key('course-hub-frequency-summary'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _SectionHeading(
            eyebrow: 'Situação atual',
            title: 'Frequência',
            action: TextButton.icon(
              key: Key(
                _firstPending == null
                    ? 'course-hub-open-attendance'
                    : 'course-hub-open-attendance-secondary',
              ),
              onPressed: _openAttendance,
              iconAlignment: IconAlignment.end,
              icon: const Icon(Icons.arrow_forward, size: 18),
              label: const Text('Ver registros'),
            ),
          ),
          const SizedBox(height: 22),
          if (_sessionsFailed)
            const Text('Não foi possível carregar a frequência agora.')
          else if (_loading && _sessions.isEmpty)
            const Text('Carregando…')
          else
            _FrequencyFigure(summary: summary),
        ],
      ),
    );
  }

  Widget _agendaSection() {
    final now = widget.now();
    final upcoming = courseAgenda(
      _course,
      _sessions,
      _datesByCourse[_course.id] ?? [],
    ).where((event) => !event.startsAt.isBefore(now)).take(3).toList();
    return _HubSection(
      key: const Key('course-hub-agenda'),
      eyebrow: 'Agenda',
      title: 'Próximas datas',
      actionKey: const Key('course-hub-open-calendar'),
      actionLabel: 'Ver calendário',
      onAction: _openCalendar,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_unavailableDateCourses.contains(_course.id))
            const Text(
              'Datas não atualizadas. Exibindo as informações disponíveis.',
            ),
          upcoming.isEmpty
              ? const Text('Nenhuma avaliação ou entrega futura encontrada.')
              : Column(
                  children: [
                    for (final session in upcoming)
                      _EventRow(
                        session: session,
                        date: _shortDate(session.startsAt),
                        onOpen: () => _openCalendar(session),
                      ),
                  ],
                ),
        ],
      ),
    );
  }

  Widget _scheduleSection() => _HubSection(
    key: const Key('course-hub-schedule'),
    eyebrow: 'Organização',
    title: _course.tracksAttendance ? 'Grade e período' : 'Grade · Sem chamada',
    actionKey: const Key('course-hub-open-schedule'),
    actionLabel: 'Ver grade',
    onAction: _openSchedule,
    child: _meetingsFailed
        ? const Text('Não foi possível carregar a grade agora.')
        : _meetings.isEmpty
        ? const Text('Nenhum horário cadastrado.')
        : Column(
            children: [
              for (final meeting in _meetings)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _ScheduleRow(meeting: meeting),
                ),
            ],
          ),
  );

  Widget _materialsSection() {
    final count = _materials?.candidates.length ?? 0;
    return _HubSection(
      key: const Key('course-hub-materials'),
      eyebrow: 'Moodle',
      title: 'Materiais',
      actionKey: const Key('course-hub-open-materials'),
      actionLabel: 'Ver todos',
      onAction: widget.ufmgSessionGateway == null ? null : _openMaterials,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_materialsFailed) ...[
            const Text('Não foi possível atualizar os materiais.'),
            TextButton(
              key: const Key('course-hub-retry-materials'),
              onPressed: _materialsLoading ? null : _loadMaterials,
              child: const Text('Tentar novamente'),
            ),
          ],
          if (count > 0)
            _MaterialPreview(
              candidate: _materials!.candidates.first,
              count: count,
            )
          else if (_materialsLoading)
            const Text('Carregando materiais…')
          else if (!_materialsFailed)
            const Text('Nenhum material sincronizado para esta disciplina.'),
        ],
      ),
    );
  }

  String _shortDate(DateTime value) {
    final local = tz.TZDateTime.from(value, _location);
    return '${local.day.toString().padLeft(2, '0')}/${local.month.toString().padLeft(2, '0')}';
  }

  String _pendingDescription(SessionRecord session) {
    final local = tz.TZDateTime.from(session.startsAt, _location);
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
    return '${local.day} de ${months[local.month - 1]} · ${_clock(local.hour * 60 + local.minute)}';
  }
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child, super.key});
  final Widget child;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(22),
    decoration: _panelDecoration(context),
    child: child,
  );
}

class _HubSection extends StatelessWidget {
  const _HubSection({
    required this.eyebrow,
    required this.title,
    required this.child,
    required this.actionLabel,
    this.actionKey,
    this.onAction,
    super.key,
  });
  final String eyebrow;
  final String title;
  final Widget child;
  final String actionLabel;
  final Key? actionKey;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) => _Panel(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _SectionHeading(
          eyebrow: eyebrow,
          title: title,
          action: TextButton(
            key: actionKey,
            onPressed: onAction,
            child: Text(actionLabel),
          ),
        ),
        const SizedBox(height: 16),
        child,
      ],
    ),
  );
}

BoxDecoration _panelDecoration(BuildContext context, {double radius = 22}) =>
    BoxDecoration(
      color: Theme.of(context).colorScheme.surface.withValues(alpha: .84),
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: _semantic(context).separator),
    );

AppSemanticColors _semantic(BuildContext context) =>
    Theme.of(context).extension<AppSemanticColors>() ??
    const AppSemanticColors(
      success: Color(0xFF197A3E),
      warning: Color(0xFF925900),
      info: Color(0xFF1769AA),
      subtleSurface: Color(0xFFEEF2EF),
      separator: Color(0xFFDCE3DE),
    );

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({
    required this.eyebrow,
    required this.title,
    required this.action,
  });
  final String eyebrow;
  final String title;
  final Widget action;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final copy = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            eyebrow.toUpperCase(),
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
              fontWeight: FontWeight.w700,
              letterSpacing: .6,
            ),
          ),
          const SizedBox(height: 4),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
        ],
      );
      if (constraints.maxWidth < 300) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            copy,
            Align(alignment: Alignment.centerLeft, child: action),
          ],
        );
      }
      return Row(
        children: [
          Expanded(child: copy),
          action,
        ],
      );
    },
  );
}

class _FrequencyFigure extends StatelessWidget {
  const _FrequencyFigure({required this.summary});
  final CourseAbsenceSummary summary;
  @override
  Widget build(BuildContext context) {
    final figure = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${summary.remainingAbsences}',
          style: Theme.of(context).textTheme.displaySmall?.copyWith(
            color: _semantic(context).success,
            fontWeight: FontWeight.w700,
            letterSpacing: -1.5,
            height: .95,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          summary.remainingMeetingsLabel,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
    final track = AttendanceProgressBar(
      present: summary.presentLessons,
      unresolved: summary.unresolvedLessons,
      absent: summary.consumedAbsences,
      barKey: const Key('course-hub-frequency-track'),
      markerKey: const Key('course-hub-frequency-limit-marker'),
    );
    return LayoutBuilder(
      builder: (context, constraints) => constraints.maxWidth < 520
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [figure, const SizedBox(height: 22), track],
            )
          : Row(
              children: [
                SizedBox(width: 136, child: figure),
                const SizedBox(width: 20),
                Expanded(child: track),
              ],
            ),
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({
    required this.session,
    required this.date,
    required this.onOpen,
  });
  final VoidCallback onOpen;
  final AgendaEntry session;
  final String date;
  @override
  Widget build(BuildContext context) {
    final parts = date.split('/');
    return InkWell(
      onTap: onOpen,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 11),
        decoration: BoxDecoration(
          border: Border(top: BorderSide(color: _semantic(context).separator)),
        ),
        child: Row(
          children: [
            Container(
              width: 46,
              height: 50,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: _semantic(context).subtleSurface,
                borderRadius: BorderRadius.circular(13),
              ),
              child: Text(
                '${parts[0]}\n${parts[1]}',
                textAlign: TextAlign.center,
                style: Theme.of(
                  context,
                ).textTheme.labelMedium?.copyWith(fontWeight: FontWeight.w700),
              ),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Text(
                session.title!,
                style: Theme.of(
                  context,
                ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
            ),
            const Icon(Icons.chevron_right, size: 20),
          ],
        ),
      ),
    );
  }
}

class _ScheduleRow extends StatelessWidget {
  const _ScheduleRow({required this.meeting});
  final MeetingRecord meeting;
  @override
  Widget build(BuildContext context) => Row(
    children: [
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 7),
        decoration: BoxDecoration(
          color: _semantic(context).success.withValues(alpha: .10),
          borderRadius: BorderRadius.circular(9),
        ),
        child: Text(
          _weekday(meeting.weekday),
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
            color: _semantic(context).success,
            fontWeight: FontWeight.w800,
          ),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Text(
          '${_clock(meeting.startMinutes)}–${_clock(meeting.endMinutes)}',
        ),
      ),
    ],
  );
}

class _MaterialPreview extends StatelessWidget {
  const _MaterialPreview({required this.candidate, required this.count});
  final PythonMoodleContentCandidate candidate;
  final int count;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Container(height: 1, color: _semantic(context).separator),
      const SizedBox(height: 12),
      Row(
        children: [
          Container(
            width: 38,
            height: 44,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Theme.of(
                context,
              ).colorScheme.errorContainer.withValues(alpha: .65),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Text(
              candidate.kind == 'file' ? 'PDF' : 'WEB',
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  candidate.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 3),
                Text(
                  'Disponível no Moodle',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          const Icon(Icons.arrow_forward, size: 19),
        ],
      ),
      const SizedBox(height: 10),
      Text(
        '$count ${count == 1 ? 'material disponível' : 'materiais disponíveis'}',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
      ),
    ],
  );
}

String _weekday(int weekday) => const [
  'Segunda',
  'Terça',
  'Quarta',
  'Quinta',
  'Sexta',
  'Sábado',
  'Domingo',
][weekday - 1];

String _clock(int minutes) =>
    '${(minutes ~/ 60).toString().padLeft(2, '0')}:${(minutes % 60).toString().padLeft(2, '0')}';
