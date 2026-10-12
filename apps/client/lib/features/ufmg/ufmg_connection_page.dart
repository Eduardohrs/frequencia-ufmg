import 'package:flutter/material.dart';

import '../../backend/python_backend_transport.dart';
import '../../observability/app_logger.dart';
import '../../observability/audited_operation.dart';

class UFMGConnectionPage extends StatefulWidget {
  const UFMGConnectionPage({
    required this.gateway,
    required this.logger,
    super.key,
  });

  final BackendUFMGSessionGateway gateway;
  final AppLogger logger;

  @override
  State<UFMGConnectionPage> createState() => _UFMGConnectionPageState();
}

class _UFMGConnectionPageState extends State<UFMGConnectionPage> {
  final _formKey = GlobalKey<FormState>();
  final _username = TextEditingController();
  final _password = TextEditingController();
  PythonUFMGSessionStatus? _status;
  bool _loading = true;
  bool _busy = false;
  bool _showReconnectForm = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionStatus,
        action: widget.gateway.getUFMGSessionStatus,
      );
      if (mounted) setState(() => _status = status);
    } catch (_) {
      if (mounted) {
        setState(
          () => _error = 'Não foi possível consultar a conexão com a UFMG.',
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _connect() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionConnect,
        action: () => widget.gateway.connectUFMG(
          username: _username.text,
          password: _password.text,
        ),
      );
      _username.clear();
      if (mounted) {
        setState(() {
          _status = status;
          _showReconnectForm = false;
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = _messageFor(error));
    } finally {
      _password.clear();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDisconnect() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Desconectar da UFMG?'),
        content: const Text(
          'A sessão acadêmica salva será apagada. Seus registros de frequência permanecem intactos.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancelar'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Desconectar'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await runAuditedOperation(
        logger: widget.logger,
        operation: AuditedOperation.ufmgSessionDisconnect,
        action: widget.gateway.disconnectUFMG,
      );
      if (mounted) setState(() => _status = status);
    } catch (error) {
      if (mounted) setState(() => _error = _messageFor(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Conexão UFMG')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 560),
              child: _loading ? const CircularProgressIndicator() : _content(),
            ),
          ),
        ),
      ),
    );
  }

  Widget _content() {
    final status = _status;
    final connected = status?.connected ?? false;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Icon(
          connected
              ? Icons.verified_user_outlined
              : Icons.account_balance_outlined,
          size: 56,
          color: connected
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(height: 16),
        Text(
          connected
              ? 'UFMG conectada'
              : status?.reauthenticationRequired == true
              ? 'Sua sessão expirou'
              : 'Conectar à UFMG',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          connected
              ? 'A sessão acadêmica pode ser usada nas próximas sincronizações.'
              : 'Use seu login institucional para permitir sincronizações. Sua senha não é armazenada.',
          textAlign: TextAlign.center,
        ),
        if (connected && status?.expiresAt != null) ...[
          const SizedBox(height: 16),
          Card(
            child: ListTile(
              leading: const Icon(Icons.schedule_outlined),
              title: const Text('Sessão temporária'),
              subtitle: Text(
                'Válida até ${_formattedExpiry(status!.expiresAt!)}',
              ),
            ),
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 16),
          Semantics(
            liveRegion: true,
            child: Text(
              _error!,
              textAlign: TextAlign.center,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        ],
        const SizedBox(height: 24),
        if (!connected || _showReconnectForm) _connectionForm(),
        if (connected && !_showReconnectForm) ...[
          FilledButton.icon(
            key: const Key('ufmg-reconnect'),
            onPressed: _busy
                ? null
                : () => setState(() => _showReconnectForm = true),
            icon: const Icon(Icons.sync),
            label: const Text('Reconectar'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('ufmg-disconnect'),
            onPressed: _busy ? null : _confirmDisconnect,
            icon: const Icon(Icons.link_off),
            label: const Text('Desconectar'),
          ),
        ],
      ],
    );
  }

  Widget _connectionForm() {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextFormField(
            key: const Key('ufmg-username'),
            controller: _username,
            enabled: !_busy,
            autofillHints: const [AutofillHints.username],
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Usuário MinhaUFMG',
              prefixIcon: Icon(Icons.person_outline),
            ),
            validator: (value) => value == null || value.trim().isEmpty
                ? 'Informe seu usuário da UFMG.'
                : null,
          ),
          const SizedBox(height: 16),
          TextFormField(
            key: const Key('ufmg-password'),
            controller: _password,
            enabled: !_busy,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            autofillHints: const [AutofillHints.password],
            onFieldSubmitted: (_) => _busy ? null : _connect(),
            decoration: const InputDecoration(
              labelText: 'Senha MinhaUFMG',
              prefixIcon: Icon(Icons.lock_outline),
            ),
            validator: (value) => value == null || value.isEmpty
                ? 'Informe sua senha da UFMG.'
                : null,
          ),
          const SizedBox(height: 20),
          FilledButton.icon(
            key: const Key('ufmg-connect'),
            onPressed: _busy ? null : _connect,
            icon: _busy
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.link),
            label: Text(connectedLabel),
          ),
          if (_showReconnectForm) ...[
            const SizedBox(height: 8),
            TextButton(
              onPressed: _busy
                  ? null
                  : () => setState(() {
                      _showReconnectForm = false;
                      _username.clear();
                      _password.clear();
                    }),
              child: const Text('Cancelar'),
            ),
          ],
        ],
      ),
    );
  }

  String get connectedLabel =>
      _showReconnectForm ? 'Renovar conexão' : 'Conectar';

  String _formattedExpiry(DateTime expiry) {
    final local = expiry.toLocal();
    return '${MaterialLocalizations.of(context).formatMediumDate(local)} às '
        '${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(local))}';
  }

  static String _messageFor(Object error) {
    if (error is PythonBackendException) {
      return switch (error.code) {
        PythonBackendError.ufmgCredentialsInvalid =>
          'Usuário ou senha da UFMG inválidos.',
        PythonBackendError.ufmgUnavailable || PythonBackendError.timeout =>
          'A UFMG está indisponível no momento. Tente novamente mais tarde.',
        PythonBackendError.rateLimited =>
          'Muitas tentativas seguidas. Aguarde um pouco e tente novamente.',
        _ => 'Não foi possível atualizar a conexão com a UFMG.',
      };
    }
    return 'Não foi possível atualizar a conexão com a UFMG.';
  }
}
