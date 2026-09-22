import 'package:flutter/material.dart';

import 'auth_gateway.dart';
import 'auth_user.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';

class AuthGate extends StatefulWidget {
  const AuthGate({required this.authGateway, required this.logger, super.key});

  final AuthGateway authGateway;
  final AppLogger logger;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool _busy = false;
  String? _error;

  Future<void> _run(
    AuditedOperation operation,
    Future<void> Function() action,
  ) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await runAuditedOperation(
        logger: widget.logger,
        operation: operation,
        action: action,
      );
    } catch (_) {
      if (mounted) {
        setState(() => _error = 'Não foi possível entrar. Tente novamente.');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<AuthUser?>(
      stream: widget.authGateway.authStateChanges,
      initialData: widget.authGateway.currentUser,
      builder: (context, snapshot) {
        final user = snapshot.data;
        return Scaffold(
          appBar: AppBar(title: const Text('Frequência UFMG')),
          body: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: user == null ? _signedOut(context) : _signedIn(user),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _signedOut(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          Icons.school_outlined,
          size: 64,
          color: Theme.of(context).colorScheme.primary,
        ),
        const SizedBox(height: 20),
        Text(
          'Seu controle de presença',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        const Text(
          'Entre para manter seus dados sincronizados no Android e na web.',
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 24),
        FilledButton.icon(
          onPressed: _busy
              ? null
              : () => _run(
                  AuditedOperation.googleSignIn,
                  widget.authGateway.signInWithGoogle,
                ),
          icon: _busy
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.login),
          label: const Text('Entrar com Google'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 16),
          Text(
            _error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
            textAlign: TextAlign.center,
          ),
        ],
      ],
    );
  }

  Widget _signedIn(AuthUser user) {
    final name = user.displayName?.trim();
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.check_circle_outline, size: 64),
        const SizedBox(height: 20),
        Text(
          name == null || name.isEmpty ? 'Login concluído' : 'Olá, $name!',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(user.email),
        const SizedBox(height: 24),
        OutlinedButton(
          onPressed: _busy
              ? null
              : () => _run(AuditedOperation.logout, widget.authGateway.signOut),
          child: const Text('Sair'),
        ),
      ],
    );
  }
}
