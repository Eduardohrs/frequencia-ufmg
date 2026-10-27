import 'dart:async';
import 'package:flutter/material.dart';
import '../../data/campus_location.dart';
import '../../domain/attendance.dart';
import '../../domain/campus_areas.dart';
import '../../domain/campus_detector.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';
import '../../observability/error_log_details.dart';

class CampusLocationPage extends StatefulWidget {
  const CampusLocationPage({
    required this.selection,
    required this.checker,
    required this.logger,
    super.key,
  });
  final CampusSelectionGateway selection;
  final CampusCheckGateway checker;
  final AppLogger logger;
  @override
  State<CampusLocationPage> createState() => _CampusLocationPageState();
}

class _CampusLocationPageState extends State<CampusLocationPage> {
  CampusArea? _area;
  CampusDetection? _result;
  String? _message, _progress;
  bool _loading = true;
  bool get _busy => _loading || _progress != null;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _message = null;
    });
    try {
      final area = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.campusSelectionRead,
        action: () async {
          final id = await widget.selection.read();
          final area = id == null
              ? CampusAreas.defaultArea
              : CampusAreas.find(id);
          if (area == null) {
            throw CampusCheckFailure('invalid_campus', 'selection_read', id!);
          }
          emitCampusEvent(widget.logger, 'campus_selection_loaded', {
            'campus_id': area.id,
            'campus_name': area.name,
            'used_default': id == null,
          });
          return area;
        },
      );
      if (mounted) setState(() => _area = area);
    } catch (_) {
      if (mounted) {
        setState(
          () => _message =
              'Não foi possível recuperar seu campus. Selecione abaixo ou tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _choose(CampusArea area) async {
    if (_busy) return;
    setState(() {
      _progress = 'Salvando campus…';
      _message = null;
      _result = null;
    });
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.campusSelectionSave,
        action: () async {
          await widget.selection.save(area.id);
          emitCampusEvent(widget.logger, 'campus_selection_saved', {
            'campus_id': area.id,
            'campus_name': area.name,
          });
        },
      );
      if (mounted) setState(() => _area = area);
    } catch (_) {
      if (mounted) {
        setState(
          () => _message = 'Não foi possível salvar o campus. Tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _progress = null);
    }
  }

  Future<void> _check() async {
    final area = _area;
    if (_busy || area == null) return;
    setState(() {
      _progress = 'Obtendo localização…';
      _message = null;
      _result = null;
    });
    try {
      final result = await widget.checker.check(area);
      if (mounted) setState(() => _result = result);
    } catch (error) {
      if (error is! CampusCheckFailure) {
        final details = ErrorLogDetails.from(error);
        emitCampusEvent(widget.logger, 'campus_location_ui_failed', {
          'campus_id': area.id,
          'stage': 'ui_callback',
          'cause_type': details.type,
          'cause_message': details.message ?? '',
        });
      }
      if (mounted) {
        setState(
          () => _message = error is CampusCheckFailure
              ? error.userMessage
              : 'Não foi possível consultar a localização. Tente novamente.',
        );
      }
    } finally {
      if (mounted) setState(() => _progress = null);
    }
  }

  String _resultDescription(CampusDetection result) => switch (result.reason) {
    CampusDetectionReason.poorAccuracy =>
      'A leitura está imprecisa. Tente novamente em um local aberto.',
    CampusDetectionReason.stale => 'A leitura está antiga. Tente novamente.',
    CampusDetectionReason.future =>
      'O horário da leitura está inconsistente. Tente novamente.',
    _ =>
      'Precisão estimada de ${(result.diagnostics['accuracy_m']! as double).round()} m.',
  };

  @override
  Widget build(BuildContext context) {
    final result = _result;
    return Scaffold(
      appBar: AppBar(title: const Text('Campus e localização')),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                'Seu campus',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: 12),
              const Text(
                'A escolha fica salva neste aparelho. Verificar a localização não registra presença.',
              ),
              const SizedBox(height: 24),
              InputDecorator(
                decoration: const InputDecoration(
                  labelText: 'Campus ou unidade',
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    key: const Key('campus-selector'),
                    value: _area?.id,
                    isExpanded: true,
                    itemHeight: null,
                    hint: Text(
                      _loading ? 'Carregando campus…' : 'Selecione um campus',
                    ),
                    items: [
                      for (final area in CampusAreas.values)
                        DropdownMenuItem(
                          value: area.id,
                          child: Text(
                            area.name,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: _busy
                        ? null
                        : (id) {
                            if (id != null) {
                              unawaited(_choose(CampusAreas.find(id)!));
                            }
                          },
                  ),
                ),
              ),
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('campus-check'),
                onPressed: _busy || _area == null ? null : _check,
                child: const Text('Verificar minha localização'),
              ),
              if (_busy) ...[
                const SizedBox(height: 16),
                const LinearProgressIndicator(),
                const SizedBox(height: 8),
                Text(_progress ?? 'Carregando campus…'),
              ],
              if (_message case final message?) ...[
                const SizedBox(height: 20),
                Semantics(liveRegion: true, child: Text(message)),
                if (_area == null && !_loading)
                  TextButton(
                    onPressed: _load,
                    child: const Text('Tentar novamente'),
                  ),
              ],
              if (result != null) ...[
                const SizedBox(height: 24),
                Semantics(
                  liveRegion: true,
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(switch (result.state) {
                            EstadoPing.onCampus => 'Dentro da área selecionada',
                            EstadoPing.away => 'Fora da área selecionada',
                            EstadoPing.unavailable =>
                              'Localização inconclusiva',
                          }, style: Theme.of(context).textTheme.titleMedium),
                          const SizedBox(height: 8),
                          Text(_resultDescription(result)),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              Text(
                'As áreas são aproximadas. Estar no campus não comprova participação na aula.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
