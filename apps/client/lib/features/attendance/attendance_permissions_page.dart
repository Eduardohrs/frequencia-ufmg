import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';

import '../../data/attendance_permissions.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

class AttendancePermissionsPage extends StatefulWidget {
  const AttendancePermissionsPage({
    required this.gateway,
    required this.logger,
    super.key,
  });
  final AttendancePermissionsGateway gateway;
  final AppLogger logger;
  @override
  State<AttendancePermissionsPage> createState() =>
      _AttendancePermissionsPageState();
}

class _AttendancePermissionsPageState extends State<AttendancePermissionsPage>
    with WidgetsBindingObserver {
  AttendancePermissionStatus? _status;
  bool _failed = false, _busy = false;
  int _revision = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(_refresh());
  }

  void _log(String event, Map<String, Object> fields) {
    unawaited(
      widget.logger
          .logEvent(
            event,
            parameters: {...fields, 'operation_id': currentOperationId!},
          )
          .catchError((Object error) {
            debugPrint(
              'attendance_permission_log_delivery_failed type=${error.runtimeType}',
            );
          }),
    );
  }

  Future<void> _refresh() async {
    final revision = ++_revision;
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.attendancePermissionsRead,
        action: () async {
          final value = await widget.gateway.read();
          _log('attendance_permission_status', {
            ...value.logFields,
            'details': jsonEncode(value.logFields),
          });
          return value;
        },
      );
      if (!mounted || revision != _revision) return;
      setState(() {
        _status = status;
        _failed = false;
      });
    } catch (_) {
      if (!mounted || revision != _revision) return;
      setState(() => _failed = true);
    }
  }

  Future<void> _act(AttendancePermissionAction action) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.attendancePermissionAction,
        action: () async {
          _log('attendance_permission_action_selected', {
            'action': action.name,
          });
          await widget.gateway.perform(action);
        },
      );
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Não foi possível abrir essa opção do Android. Tente novamente.',
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
        await _refresh();
      }
    }
  }

  Widget _item({
    required String title,
    required String status,
    required String description,
    required IconData icon,
    required bool granted,
    required String button,
    required AttendancePermissionAction action,
    bool enabled = true,
  }) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: 22),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text(status),
                  ],
                ),
              ),
              if (granted) const Icon(Icons.check_circle_outline, size: 20),
            ],
          ),
          const SizedBox(height: 10),
          Text(description, style: Theme.of(context).textTheme.bodyMedium),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              key: Key('permission-${action.name}'),
              onPressed: _busy || !enabled ? null : () => _act(action),
              child: Text(button),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = _status;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Permissões'),
        actions: [
          IconButton(
            tooltip: 'Atualizar permissões',
            onPressed: _busy ? null : _refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                s?.locationReady == true
                    ? 'Acesso à localização pronto'
                    : 'Localização e avisos',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 12),
              const Text(
                'A localização permite estimar a presença no campus. Seus registros podem ser corrigidos manualmente.',
              ),
              const SizedBox(height: 20),
              if (_failed)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        const Text('Não foi possível atualizar as permissões.'),
                        TextButton(
                          onPressed: _refresh,
                          child: const Text('Tentar novamente'),
                        ),
                      ],
                    ),
                  ),
                ),
              if (s == null && !_failed)
                const Center(child: CircularProgressIndicator()),
              if (s != null) ...[
                Card(
                  child: Column(
                    children: [
                      _item(
                        title: 'Localização do aparelho',
                        status: s.locationServices ? 'Ativada' : 'Desativada',
                        description:
                            'O serviço de localização do Android precisa estar ligado.',
                        icon: Icons.location_on_outlined,
                        granted: s.locationServices,
                        button: 'Abrir localização',
                        action: AttendancePermissionAction.locationSettings,
                      ),
                      const Divider(height: 1),
                      _item(
                        title: 'Localização precisa',
                        status: s.preciseLocation
                            ? 'Permitida'
                            : s.foregroundLocation
                            ? 'Somente aproximada'
                            : 'Não permitida',
                        description:
                            'A precisão ajuda a diferenciar o campus de regiões próximas.',
                        icon: Icons.gps_fixed,
                        granted: s.preciseLocation,
                        button: s.locationRequestable
                            ? 'Permitir localização'
                            : 'Ajustar localização',
                        action: s.locationRequestable
                            ? AttendancePermissionAction.requestLocation
                            : AttendancePermissionAction.appSettings,
                      ),
                      const Divider(height: 1),
                      _item(
                        title: 'Localização em segundo plano',
                        status: s.backgroundLocation
                            ? 'Permitida'
                            : 'Não permitida',
                        description: s.foregroundLocation
                            ? 'Nas permissões de localização do aplicativo, escolha “${s.backgroundOptionLabel}”.'
                            : 'Primeiro permita a localização durante o uso do aplicativo.',
                        icon: Icons.location_searching,
                        granted: s.backgroundLocation,
                        button: 'Revisar acesso em segundo plano',
                        action: AttendancePermissionAction.backgroundSettings,
                        enabled: s.foregroundLocation,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Card(
                  child: _item(
                    title: 'Notificações',
                    status: s.notifications ? 'Permitidas' : 'Desativadas',
                    description:
                        'Receba lembretes e avisos de situações que precisam da sua atenção.',
                    icon: Icons.notifications_none,
                    granted: s.notifications,
                    button: s.notificationsRequestable
                        ? 'Permitir notificações'
                        : 'Revisar notificações',
                    action: s.notificationsRequestable
                        ? AttendancePermissionAction.requestNotifications
                        : AttendancePermissionAction.notificationSettings,
                  ),
                ),
                const SizedBox(height: 12),
                Card(
                  child: _item(
                    title: 'Bateria',
                    status: s.batteryUnrestricted
                        ? 'Sem otimização de bateria'
                        : 'Otimizada pelo Android',
                    description:
                        'Se tarefas em segundo plano forem adiadas, revise as opções de bateria deste aplicativo. Esse ajuste é opcional.',
                    icon: Icons.battery_saver_outlined,
                    granted: s.batteryUnrestricted,
                    button: 'Revisar bateria',
                    action: AttendancePermissionAction.batterySettings,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
