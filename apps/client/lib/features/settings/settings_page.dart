import 'dart:async';
import 'package:flutter/material.dart';
import '../../auth/auth_user.dart';
import '../../data/campus_location.dart';
import '../../domain/campus_areas.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/operation_diagnostics.dart';
import 'automatic_attendance_controller.dart';

Future<void> showAttendanceSetup(
  BuildContext context,
  AutomaticAttendanceController controller,
) async {
  emitOperationalEvent(controller.logger, 'attendance_setup_opened', {
    'operation_id': newCorrelationId('attendance_setup'),
    'stage': 'guided_setup',
    'missing_count': controller.needs.length,
  });
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => _AttendanceSetup(controller: controller),
  );
}

class AttendanceSetupReminder extends StatelessWidget {
  const AttendanceSetupReminder({required this.controller, super.key});
  final AutomaticAttendanceController controller;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) => !controller.showReminder
        ? const SizedBox.shrink()
        : Card(
            key: const Key('attendance-setup-reminder'),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Conclua a configuração da presença',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  Text(controller.instruction),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      TextButton(
                        onPressed: () => unawaited(controller.defer()),
                        child: const Text('Agora não'),
                      ),
                      TextButton(
                        onPressed: () =>
                            showAttendanceSetup(context, controller),
                        child: const Text('Concluir'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
  );
}

class _AttendanceSetup extends StatefulWidget {
  const _AttendanceSetup({required this.controller});
  final AutomaticAttendanceController controller;
  @override
  State<_AttendanceSetup> createState() => _AttendanceSetupState();
}

class _AttendanceSetupState extends State<_AttendanceSetup> {
  String? _error, _hint;
  AttendanceSetupNeed? _hintNeed;
  Future<void> _resolve() async {
    final previous = widget.controller.next;
    _hintNeed = previous;
    setState(() {
      _error = null;
      _hint = null;
    });
    try {
      await widget.controller.resolveNext();
      if (mounted &&
          previous == widget.controller.next &&
          !widget.controller.permissionError) {
        setState(
          () => _hint =
              "O ajuste ainda não foi ativado. Você pode tentar novamente ou deixar para depois.",
        );
      }
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Não foi possível abrir o ajuste. Tente novamente.',
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) {
      final c = widget.controller;
      return Padding(
        padding: const EdgeInsets.all(24),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                c.permissionError
                    ? 'Conferir configuração'
                    : c.status == null
                    ? 'Conferindo configuração'
                    : c.next == null
                    ? 'Tudo pronto'
                    : 'Presença nas suas aulas',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 12),
              Text(
                c.permissionError
                    ? 'Não foi possível conferir as permissões. Tente atualizar.'
                    : c.instruction,
              ),
              const SizedBox(height: 12),
              if (c.next != null)
                const Text(
                  'Você pode continuar registrando sua frequência manualmente.',
                ),
              if (_hint != null && c.next == _hintNeed) Text(_hint!),
              if (_error != null && c.next != null)
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              const SizedBox(height: 20),
              if (c.busy && c.status == null)
                const LinearProgressIndicator()
              else if (c.permissionError)
                FilledButton(
                  onPressed: c.busy ? null : c.refresh,
                  child: const Text('Tentar novamente'),
                )
              else if (c.next != null)
                FilledButton(
                  onPressed: c.acting ? null : _resolve,
                  child: Text(c.acting ? 'Aguardando…' : 'Continuar'),
                )
              else
                FilledButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Concluir'),
                ),
              if (c.next != null)
                TextButton(
                  onPressed: () async {
                    await c.defer();
                    if (context.mounted) Navigator.pop(context);
                  },
                  child: const Text('Agora não'),
                ),
            ],
          ),
        ),
      );
    },
  );
}

class AppSettingsPage extends StatelessWidget {
  const AppSettingsPage({
    required this.user,
    required this.logger,
    required this.onSignOut,
    this.attendance,
    this.onAcademicAccount,
    this.onSavedFiles,
    this.campusSelection,
    this.onCampusChanged,
    super.key,
  });
  final AuthUser user;
  final AppLogger logger;
  final AutomaticAttendanceController? attendance;
  final Future<void> Function() onSignOut;
  final Future<void> Function()? onAcademicAccount, onSavedFiles;
  final CampusSelectionGateway? campusSelection;
  final VoidCallback? onCampusChanged;
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Ajustes')),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(
              user.displayName ?? 'Sua conta',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            Text(user.email),
            const SizedBox(height: 24),
            if (attendance case final c?)
              ListenableBuilder(
                listenable: c,
                builder: (context, _) => Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(
                              c.status != null &&
                                      c.next == null &&
                                      !c.permissionError
                                  ? Icons.check_circle_outline
                                  : Icons.info_outline,
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Text(
                                'Presença nas aulas',
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(c.title),
                        const SizedBox(height: 4),
                        Text(c.instruction),
                        if (c.next != null || c.permissionError)
                          TextButton(
                            onPressed: () => showAttendanceSetup(context, c),
                            child: const Text('Concluir configuração'),
                          ),
                        if (c.reportError)
                          const Text(
                            'Não foi possível conferir os últimos resultados neste aparelho.',
                          )
                        else
                          Text(
                            c.busy
                                ? 'Conferindo resultados…'
                                : c.reports.any(
                                    (r) => r['status'] == 'succeeded',
                                  )
                                ? 'Os resultados estão na frequência de cada disciplina.'
                                : 'Ainda não há verificações concluídas neste aparelho.',
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            if (attendance != null)
              ListTile(
                leading: const Icon(Icons.location_on_outlined),
                title: const Text('Local das aulas'),
                subtitle: const Text('Campus usado na presença automática'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push<void>(
                  MaterialPageRoute(
                    builder: (_) => _CampusPicker(
                      selection: campusSelection ?? LocalCampusSelection(),
                      logger: logger,
                      onSaved: onCampusChanged,
                    ),
                  ),
                ),
              ),
            if (onAcademicAccount != null)
              ListTile(
                leading: const Icon(Icons.account_balance_outlined),
                key: const Key('settings-academic-account'),
                title: const Text('Conta acadêmica UFMG'),
                subtitle: const Text('Acesso e sincronização'),
                trailing: const Icon(Icons.chevron_right),
                onTap: onAcademicAccount,
              ),
            if (onSavedFiles != null)
              ListTile(
                leading: const Icon(Icons.offline_pin_outlined),
                title: const Text('Arquivos no aparelho'),
                trailing: const Icon(Icons.chevron_right),
                onTap: onSavedFiles,
              ),
            const SizedBox(height: 24),
            TextButton.icon(
              onPressed: onSignOut,
              icon: const Icon(Icons.logout),
              label: const Text('Sair da conta'),
            ),
          ],
        ),
      ),
    ),
  );
}

class _CampusPicker extends StatefulWidget {
  const _CampusPicker({
    required this.selection,
    required this.logger,
    this.onSaved,
  });
  final CampusSelectionGateway selection;
  final AppLogger logger;
  final VoidCallback? onSaved;
  @override
  State<_CampusPicker> createState() => _CampusPickerState();
}

class _CampusPickerState extends State<_CampusPicker> {
  String? _selected;
  bool _busy = true;
  bool _failed = false;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    try {
      final id = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.campusSelectionRead,
        action: widget.selection.read,
      );
      if (mounted) {
        setState(() {
          _selected =
              CampusAreas.find(id ?? '')?.id ?? CampusAreas.defaultArea.id;
          _failed = false;
        });
      }
    } catch (error, stack) {
      recordOperationalFailure(
        widget.logger,
        error,
        stack,
        'campus_selection_read',
        {'stage': 'settings'},
        failureCode: 'campus_selection_read_failed',
      );
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save(String id) async {
    setState(() => _busy = true);
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.campusSelectionSave,
        action: () => widget.selection.save(id),
      );
      if (mounted) {
        widget.onSaved?.call();
        Navigator.pop(context);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _busy = false);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Não foi possível salvar o campus.')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Local das aulas')),
    body: _busy
        ? const Center(child: CircularProgressIndicator())
        : _failed
        ? Center(
            child: TextButton(
              onPressed: _load,
              child: const Text('Tentar novamente'),
            ),
          )
        : ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Text(
                'Escolha onde você tem aulas. A área é aproximada; estar no campus não comprova participação.',
              ),
              for (final campus in CampusAreas.values)
                ListTile(
                  title: Text(campus.name),
                  trailing: campus.id == _selected
                      ? const Icon(Icons.check)
                      : null,
                  onTap: () => _save(campus.id),
                ),
            ],
          ),
  );
}
