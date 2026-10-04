import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:timezone/timezone.dart' as tz;

import '../../auth/auth_user.dart';
import '../../backend/python_backend_transport.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../data/academic_period.dart';
import '../../observability/error_log_details.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../attendance/absence_dashboard_page.dart';
import '../schedule/course_schedule_page.dart';
import '../schedule/general_calendar_page.dart';
import 'course_editor_dialog.dart';

typedef CourseIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

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
    this.attendanceEvaluator,
    CourseIdGenerator? idGenerator,
    CurrentTime? now,
    super.key,
  }) : idGenerator = idGenerator ?? _newCourseId,
       now = now ?? DateTime.now;

  final CourseRepository repository;
  final MeetingRepository meetingRepository;
  final SessionRepository sessionRepository;
  final AuthUser user;
  final AppLogger logger;
  final Future<void> Function() onSignOut;
  final BackendAttendanceEvaluator? attendanceEvaluator;
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

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadFailed = false;
    });
    try {
      final courses = await widget.repository.listCourses();
      await _removeExpiredCourses(courses);
      if (!mounted) return;
      courses.sort((left, right) => left.code.compareTo(right.code));
      setState(() => _courses = courses);
    } catch (_) {
      if (mounted) setState(() => _loadFailed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
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

  Future<void> _openSchedule(CourseRecord course) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (context) => CourseSchedulePage(
          course: course,
          courseRepository: widget.repository,
          repository: widget.meetingRepository,
          sessionRepository: widget.sessionRepository,
          logger: widget.logger,
          attendanceEvaluator: widget.attendanceEvaluator,
          allCourses: _courses,
          allCourseIds: _courses.map((item) => item.id),
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _openGeneralCalendar() async {
    Navigator.of(context).pop();
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => GeneralCalendarPage(
          courses: _courses,
          repository: widget.sessionRepository,
          location: tz.getLocation('America/Sao_Paulo'),
          now: widget.now,
        ),
      ),
    );
  }

  Future<void> _openAbsenceDashboard() async {
    Navigator.of(context).pop();
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => AbsenceDashboardPage(
          courses: _courses,
          repository: widget.sessionRepository,
          location: tz.getLocation('America/Sao_Paulo'),
        ),
      ),
    );
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
        title: const Text('Excluir disciplina?'),
        content: Text(
          'Todos os horários e registros de ${course.code} também serão excluídos.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
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
    return Scaffold(
      drawer: Drawer(
        child: SafeArea(
          child: ListView(
            children: [
              const ListTile(
                title: Text('Frequência UFMG'),
                subtitle: Text('Navegação'),
              ),
              ListTile(
                key: const Key('nav-courses'),
                title: const Text('Disciplinas'),
                onTap: () => Navigator.of(context).pop(),
              ),
              ListTile(
                key: const Key('nav-general-calendar'),
                title: const Text('Calendário geral'),
                onTap: _openGeneralCalendar,
              ),
              ListTile(
                key: const Key('nav-absence-dashboard'),
                title: const Text('Faltas restantes'),
                onTap: _openAbsenceDashboard,
              ),
            ],
          ),
        ),
      ),
      appBar: AppBar(
        title: const Text('Frequência UFMG'),
        actions: [
          IconButton(
            tooltip: 'Sair',
            onPressed: widget.onSignOut,
            icon: const Icon(Icons.logout),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 960),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 40),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    firstName == null || firstName.isEmpty
                        ? 'Suas disciplinas'
                        : 'Olá, $firstName',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    widget.user.email,
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 28),
                  _SectionHeader(onAdd: () => _openEditor()),
                  const SizedBox(height: 16),
                  Expanded(child: _content()),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _content() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_loadFailed) {
      return _MessageState(
        icon: Icons.cloud_off_outlined,
        title: 'Não foi possível carregar suas disciplinas.',
        actionLabel: 'Tentar novamente',
        onAction: _load,
      );
    }
    if (_courses.isEmpty) {
      return _MessageState(
        icon: Icons.menu_book_outlined,
        title: 'Nenhuma disciplina cadastrada',
        description: 'Adicione as matérias deste período para começar.',
        actionLabel: 'Adicionar disciplina',
        onAction: _openEditor,
      );
    }
    return ListView.separated(
      itemCount: _courses.length,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (context, index) => _CourseTile(
        course: _courses[index],
        deleting: _deletingId == _courses[index].id,
        saving: _savingIds.contains(_courses[index].id),
        onEdit: () => _openEditor(_courses[index]),
        onSchedule: () => _openSchedule(_courses[index]),
        onDelete: () => _confirmDelete(_courses[index]),
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
      builder: (context, constraints) => Row(
        children: [
          Expanded(
            child: Text(
              'Disciplinas',
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          FilledButton.icon(
            key: const Key('add-course'),
            onPressed: onAdd,
            icon: const Icon(Icons.add),
            label: Text(
              constraints.maxWidth < 500 ? 'Adicionar' : 'Adicionar disciplina',
            ),
          ),
        ],
      ),
    );
  }
}

class _CourseTile extends StatelessWidget {
  const _CourseTile({
    required this.course,
    required this.deleting,
    required this.saving,
    required this.onEdit,
    required this.onSchedule,
    required this.onDelete,
  });

  final CourseRecord course;
  final bool deleting;
  final bool saving;
  final VoidCallback onEdit;
  final VoidCallback onSchedule;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      clipBehavior: Clip.antiAlias,
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
        title: Text(
          course.code,
          style: Theme.of(context).textTheme.titleMedium,
        ),
        subtitle: Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(course.name),
              const SizedBox(height: 2),
              Text(course.term),
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
                  IconButton(
                    tooltip: 'Horários ${course.code}',
                    onPressed: onSchedule,
                    icon: const Icon(Icons.calendar_view_week_outlined),
                  ),
                  IconButton(
                    tooltip: 'Editar ${course.code}',
                    onPressed: onEdit,
                    icon: const Icon(Icons.edit_outlined),
                  ),
                  IconButton(
                    tooltip: 'Excluir ${course.code}',
                    onPressed: onDelete,
                    icon: const Icon(Icons.delete_outline),
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
  Widget build(BuildContext context) {
    return Center(
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
    );
  }
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
