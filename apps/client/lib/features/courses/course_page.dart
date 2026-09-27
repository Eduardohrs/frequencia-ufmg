import 'dart:math';

import 'package:flutter/material.dart';

import '../../auth/auth_user.dart';
import '../../data/academic_records.dart';
import '../../data/academic_repositories.dart';
import '../../observability/error_log_details.dart';
import 'course_editor_dialog.dart';

typedef CourseIdGenerator = String Function();
typedef CurrentTime = DateTime Function();

class CoursePage extends StatefulWidget {
  // The runtime defaults intentionally prevent callers from needing utility
  // objects merely to construct the production page.
  // ignore: prefer_const_constructors_in_immutables
  CoursePage({
    required this.repository,
    required this.user,
    required this.onSignOut,
    CourseIdGenerator? idGenerator,
    CurrentTime? now,
    super.key,
  }) : idGenerator = idGenerator ?? _newCourseId,
       now = now ?? DateTime.now;

  final CourseRepository repository;
  final AuthUser user;
  final Future<void> Function() onSignOut;
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
      if (!mounted) return;
      courses.sort((left, right) => left.code.compareTo(right.code));
      setState(() => _courses = courses);
    } catch (_) {
      if (mounted) setState(() => _loadFailed = true);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _openEditor([CourseRecord? course]) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => CourseEditorDialog(
        course: course,
        onSave: (input) => _save(course, input),
      ),
    );
  }

  Future<String?> _save(CourseRecord? existing, CourseInput input) async {
    try {
      final timestamp = widget.now().toUtc();
      final course = CourseRecord(
        id: existing?.id ?? widget.idGenerator(),
        code: input.code,
        name: input.name,
        workload: input.workload,
        term: input.term,
        createdAt: existing?.createdAt ?? timestamp,
        updatedAt: timestamp,
      );
      await widget.repository.saveCourse(course);
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
        onEdit: () => _openEditor(_courses[index]),
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
    required this.onEdit,
    required this.onDelete,
  });

  final CourseRecord course;
  final bool deleting;
  final VoidCallback onEdit;
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
              Text('${course.workload} horas-aula • ${course.term}'),
            ],
          ),
        ),
        trailing: deleting
            ? const SizedBox.square(
                dimension: 24,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
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
      '${random.nextInt(1 << 32).toRadixString(36)}';
}
