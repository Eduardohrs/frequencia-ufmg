import 'package:flutter/material.dart';

import '../../data/academic_records.dart';

final class CourseInput {
  const CourseInput({
    required this.code,
    required this.name,
    required this.workload,
    required this.term,
  });

  final String code;
  final String name;
  final int workload;
  final String term;
}

class CourseEditorDialog extends StatefulWidget {
  const CourseEditorDialog({required this.onSave, this.course, super.key});

  final CourseRecord? course;
  final Future<String?> Function(CourseInput input) onSave;

  @override
  State<CourseEditorDialog> createState() => _CourseEditorDialogState();
}

class _CourseEditorDialogState extends State<CourseEditorDialog> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _code;
  late final TextEditingController _name;
  late final TextEditingController _workload;
  late final TextEditingController _term;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final course = widget.course;
    _code = TextEditingController(text: course?.code);
    _name = TextEditingController(text: course?.name);
    _workload = TextEditingController(text: course?.workload.toString());
    _term = TextEditingController(text: course?.term);
  }

  @override
  void dispose() {
    _code.dispose();
    _name.dispose();
    _workload.dispose();
    _term.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    final error = await widget.onSave(
      CourseInput(
        code: _code.text.trim(),
        name: _name.text.trim(),
        workload: int.parse(_workload.text),
        term: _term.text.trim(),
      ),
    );
    if (!mounted) return;
    if (error == null) {
      Navigator.of(context).pop();
    } else {
      setState(() {
        _saving = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(
        widget.course == null ? 'Nova disciplina' : 'Editar disciplina',
      ),
      content: SizedBox(
        width: 480,
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  key: const Key('course-code'),
                  controller: _code,
                  enabled: !_saving,
                  textCapitalization: TextCapitalization.characters,
                  decoration: const InputDecoration(
                    labelText: 'Código',
                    hintText: 'DCC203',
                  ),
                  validator: (value) =>
                      _required(value, 'Informe o código.', 32),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('course-name'),
                  controller: _name,
                  enabled: !_saving,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: const InputDecoration(
                    labelText: 'Nome',
                    hintText: 'Programação Orientada a Objetos',
                  ),
                  validator: (value) =>
                      _required(value, 'Informe o nome.', 160),
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('course-workload'),
                  controller: _workload,
                  enabled: !_saving,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Carga horária',
                    suffixText: 'horas-aula',
                  ),
                  validator: (value) {
                    final parsed = int.tryParse(value?.trim() ?? '');
                    return parsed == null || parsed <= 0
                        ? 'Use um número maior que zero.'
                        : null;
                  },
                ),
                const SizedBox(height: 16),
                TextFormField(
                  key: const Key('course-term'),
                  controller: _term,
                  enabled: !_saving,
                  decoration: const InputDecoration(
                    labelText: 'Período letivo',
                    hintText: '2026-2',
                  ),
                  validator: (value) =>
                      RegExp(r'^\d{4}-[12]$').hasMatch(value?.trim() ?? '')
                      ? null
                      : 'Use o formato AAAA-S, como 2026-2.',
                ),
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      _error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _saving ? null : _submit,
          child: _saving
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Salvar'),
        ),
      ],
    );
  }
}

String? _required(String? value, String message, int maxLength) {
  final normalized = value?.trim() ?? '';
  if (normalized.isEmpty) return message;
  if (normalized.length > maxLength) {
    return 'Use no máximo $maxLength caracteres.';
  }
  return null;
}
