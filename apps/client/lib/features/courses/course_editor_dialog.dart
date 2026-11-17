import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../data/academic_records.dart';
import '../../design/app_feedback.dart';

final class CourseInput {
  const CourseInput({
    this.nickname,
    this.modality = CourseModality.inPerson,
    this.attendancePolicy = CourseAttendancePolicy.required,
    required this.code,
    required this.name,
    required this.term,
  });

  final String code;
  final CourseModality modality;
  final CourseAttendancePolicy attendancePolicy;
  final String name;
  final String? nickname;
  final String term;
}

class _CloseDialogIntent extends Intent {
  const _CloseDialogIntent();
}

class _SubmitFormIntent extends Intent {
  const _SubmitFormIntent();
}

class CourseEditorDialog extends StatefulWidget {
  const CourseEditorDialog({
    required this.onSave,
    required this.onValidationFailed,
    required this.initialTerm,
    required this.allowedTerms,
    this.course,
    this.draftValues,
    this.clock = DateTime.now,
    super.key,
  });

  final CourseRecord? course;
  final Future<String?> Function(CourseInput input) onSave;
  final VoidCallback onValidationFailed;
  final String initialTerm;
  final List<String> allowedTerms;
  final Map<String, Object?>? draftValues;
  final DateTime Function() clock;

  @override
  State<CourseEditorDialog> createState() => _CourseEditorDialogState();
}

class _CourseEditorDialogState extends State<CourseEditorDialog> {
  // 55.33: debounce de 300ms no envio evita cliques duplicados.
  static const _submitDebounce = Duration(milliseconds: 300);
  // 55.33: alvos de toque com pelo menos 48x48dp.
  static const _minTouchTarget = Size(48, 48);

  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _code;
  late final TextEditingController _name;
  late final TextEditingController _nickname;
  late final TextEditingController _term;
  bool _saving = false;
  bool _busy = false;
  DateTime? _lastSubmitAt;
  late CourseModality _modality;
  late CourseAttendancePolicy _attendancePolicy;
  String? _error;

  @override
  void initState() {
    super.initState();
    final course = widget.course;
    final draft = course == null ? widget.draftValues : null;
    _modality = course?.modality ?? CourseModality.fromCode(draft?['modality']);
    _attendancePolicy =
        course?.attendancePolicy ??
        CourseAttendancePolicy.fromCode(draft?['attendance_policy']);
    _code = TextEditingController(
      text: course?.code ?? _draftString(draft, 'code'),
    );
    _name = TextEditingController(
      text: course?.name ?? _draftString(draft, 'name'),
    );
    _nickname = TextEditingController(
      text: course?.nickname ?? _draftString(draft, 'nickname'),
    );
    _term = TextEditingController(
      text: course?.term ?? _draftString(draft, 'term') ?? widget.initialTerm,
    );
  }

  static String? _draftString(Map<String, Object?>? draft, String key) {
    final value = draft?[key];
    return value is String && value.isNotEmpty ? value : null;
  }

  @override
  void dispose() {
    _code.dispose();
    _name.dispose();
    _nickname.dispose();
    _term.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) {
      widget.onValidationFailed();
      return;
    }
    final now = widget.clock();
    final last = _lastSubmitAt;
    if (last != null && now.difference(last) < _submitDebounce) return;
    if (_saving || _busy) return;
    _lastSubmitAt = now;
    // _busy trava reentradas síncronas (duplo clique) sem esconder o
    // diálogo de confirmação atrás de um spinner.
    _busy = true;
    final previous = widget.course;
    if (previous != null &&
        (previous.modality != _modality ||
            previous.attendancePolicy != _attendancePolicy)) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('Alterar controle de frequência?'),
          content: Text(
            _attendancePolicy == CourseAttendancePolicy.noCall
                ? 'Esta disciplina deixará de entrar nos cálculos de frequência e nas pendências. '
                      'Os registros existentes serão preservados. Atividades e materiais continuam disponíveis.'
                : 'A disciplina voltará aos cálculos e às pendências de frequência, '
                      'usando seus registros e horários preservados.',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancelar'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Aplicar'),
            ),
          ],
        ),
      );
      if (!mounted) return;
      if (confirmed != true) {
        _busy = false;
        _lastSubmitAt = null;
        return;
      }
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final error = await widget.onSave(
      CourseInput(
        modality: _modality,
        attendancePolicy: _attendancePolicy,
        code: _code.text.trim(),
        name: _name.text.trim(),
        nickname: _nickname.text.trim().isEmpty ? null : _nickname.text.trim(),
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
      _busy = false;
      _lastSubmitAt = null;
    }
  }

  @override
  Widget build(BuildContext context) {
    final media = MediaQuery.of(context);
    final scaler = media.textScaler;
    // 55.33: no mobile, garante fonte mínima legível no formulário
    // (a partir de 360dp de largura, para não transbordar telas muito estreitas).
    final mobile = media.size.width >= 360 && media.size.width < 600;
    final effectiveScaler = mobile && scaler.scale(1) < 1.15
        ? TextScaler.linear(1.15)
        : scaler;
    final isCreate = widget.course == null;
    return MediaQuery(
      data: media.copyWith(textScaler: effectiveScaler),
      child: Shortcuts(
        shortcuts: const <ShortcutActivator, Intent>{
          SingleActivator(LogicalKeyboardKey.escape): _CloseDialogIntent(),
          SingleActivator(LogicalKeyboardKey.enter): _SubmitFormIntent(),
        },
        child: Actions(
          actions: <Type, Action<Intent>>{
            _CloseDialogIntent: CallbackAction<_CloseDialogIntent>(
              onInvoke: (_) {
                if (!_saving && !_busy) Navigator.of(context).maybePop();
                return null;
              },
            ),
            _SubmitFormIntent: CallbackAction<_SubmitFormIntent>(
              onInvoke: (_) {
                _submit();
                return null;
              },
            ),
          },
          child: AlertDialog(
            title: AppDialogHeader(
              icon: isCreate ? Icons.add_circle_outline : Icons.edit_outlined,
              title: isCreate ? 'Nova disciplina' : 'Editar disciplina',
              subtitle: isCreate
                  ? 'Identifique a matéria para começar a acompanhar sua frequência.'
                  : 'Atualize os dados sem alterar o histórico da matéria.',
            ),
            content: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Form(
                key: _formKey,
                autovalidateMode: AutovalidateMode.onUserInteraction,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      TextFormField(
                        key: const Key('course-code'),
                        controller: _code,
                        autofocus: true,
                        enabled: !_saving,
                        textCapitalization: TextCapitalization.characters,
                        textInputAction: TextInputAction.next,
                        onFieldSubmitted: (_) => _submit(),
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
                        textInputAction: TextInputAction.next,
                        onFieldSubmitted: (_) => _submit(),
                        decoration: const InputDecoration(
                          labelText: 'Nome',
                          hintText: 'Programação Orientada a Objetos',
                        ),
                        validator: (value) =>
                            _required(value, 'Informe o nome.', 160),
                      ),
                      // 55.33: ao criar, o formulário fica enxuto (código + nome);
                      // apelido/modalidade/frequência ficam em "Opções avançadas".
                      if (isCreate) ...[
                        const SizedBox(height: 8),
                        ExpansionTile(
                          key: const Key('course-advanced-options'),
                          title: const Text('Opções avançadas'),
                          subtitle: const Text(
                            'Apelido, modalidade e frequência',
                          ),
                          children: [
                            _nicknameField(),
                            const SizedBox(height: 16),
                            _modalityDropdown(),
                            if (_modality == CourseModality.inPerson) ...[
                              const SizedBox(height: 16),
                              _attendanceDropdown(),
                            ],
                          ],
                        ),
                      ] else ...[
                        const SizedBox(height: 16),
                        _nicknameField(),
                        const SizedBox(height: 16),
                        _modalityDropdown(),
                        if (_modality == CourseModality.inPerson) ...[
                          const SizedBox(height: 16),
                          _attendanceDropdown(),
                        ],
                        const SizedBox(height: 16),
                        TextFormField(
                          key: const Key('course-term'),
                          controller: _term,
                          enabled: !_saving,
                          textInputAction: TextInputAction.done,
                          onFieldSubmitted: (_) => _submit(),
                          decoration: const InputDecoration(
                            labelText: 'Período letivo',
                            hintText: '2026-2',
                          ),
                          validator: (value) =>
                              widget.allowedTerms.contains(value?.trim())
                              ? null
                              : 'Escolha o período atual (${widget.allowedTerms.first}) '
                                    'ou o próximo (${widget.allowedTerms.last}).',
                        ),
                      ],
                      if (_error != null) ...[
                        const SizedBox(height: 16),
                        AppInlineMessage(
                          tone: AppMessageTone.error,
                          message: _error!,
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
            // Wrap em vez de Row reta: em telas estreitas os botões quebram
            // de linha em vez de transbordar (55.33).
            actions: [
              Wrap(
                alignment: WrapAlignment.end,
                spacing: 8,
                runSpacing: 8,
                children: [
                  TextButton(
                    onPressed: _saving
                        ? null
                        : () => Navigator.of(context).pop(),
                    style: TextButton.styleFrom(minimumSize: _minTouchTarget),
                    child: const Text('Cancelar'),
                  ),
                  FilledButton(
                    onPressed: _saving ? null : _submit,
                    style: FilledButton.styleFrom(
                      minimumSize: const Size(88, 48),
                    ),
                    child: _saving
                        ? const Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              SizedBox.square(
                                dimension: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              ),
                              SizedBox(width: 10),
                              Flexible(
                                child: Text(
                                  'Salvando...',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ],
                          )
                        : const Text('Salvar'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _nicknameField() => TextFormField(
    key: const Key('course-nickname'),
    controller: _nickname,
    enabled: !_saving,
    textInputAction: TextInputAction.next,
    onFieldSubmitted: (_) => _submit(),
    decoration: const InputDecoration(
      labelText: 'Apelido (opcional)',
      hintText: 'Ex.: POO',
      helperText:
          'Como você quer ver esta disciplina. Deixe vazio para usar o nome.',
      helperMaxLines: 2,
    ),
    validator: (value) => (value?.trim().length ?? 0) > 48
        ? 'Use no máximo 48 caracteres.'
        : null,
  );

  Widget _modalityDropdown() => DropdownButtonFormField<CourseModality>(
    isExpanded: true,
    key: const Key('course-modality'),
    initialValue: _modality,
    decoration: const InputDecoration(labelText: 'Modalidade'),
    items: [
      for (final value in CourseModality.values)
        DropdownMenuItem(value: value, child: Text(value.label)),
    ],
    onChanged: _saving
        ? null
        : (value) => setState(() {
            _modality = value!;
            if (_modality == CourseModality.online) {
              _attendancePolicy = CourseAttendancePolicy.noCall;
            }
          }),
  );

  Widget _attendanceDropdown() =>
      DropdownButtonFormField<CourseAttendancePolicy>(
        isExpanded: true,
        key: ValueKey('course-attendance-${_attendancePolicy.code}'),
        initialValue: _attendancePolicy,
        decoration: const InputDecoration(labelText: 'Frequência'),
        items: [
          for (final value in CourseAttendancePolicy.values)
            DropdownMenuItem(value: value, child: Text(value.label)),
        ],
        onChanged: _saving
            ? null
            : (value) => setState(() => _attendancePolicy = value!),
      );
}

String? _required(String? value, String message, int maxLength) {
  final normalized = value?.trim() ?? '';
  if (normalized.isEmpty) return message;
  if (normalized.length > maxLength) {
    return 'Use no máximo $maxLength caracteres.';
  }
  return null;
}
