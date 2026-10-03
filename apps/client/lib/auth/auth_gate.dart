import 'dart:async';

import 'package:flutter/material.dart';

import 'auth_gateway.dart';
import 'auth_user.dart';
import '../backend/python_backend_transport.dart';
import '../data/academic_repositories.dart';
import '../features/courses/course_page.dart';
import '../observability/app_logger.dart';
import '../observability/audited_operation.dart';

class AuthGate extends StatefulWidget {
  const AuthGate({
    required this.authGateway,
    required this.logger,
    required this.courseRepositoryFactory,
    required this.meetingRepositoryFactory,
    required this.sessionRepositoryFactory,
    this.backendIdentityVerifier,
    super.key,
  });

  final AuthGateway authGateway;
  final AppLogger logger;
  final CourseRepository Function(String userId) courseRepositoryFactory;
  final MeetingRepository Function(String userId) meetingRepositoryFactory;
  final SessionRepository Function(String userId) sessionRepositoryFactory;
  final BackendIdentityVerifier? backendIdentityVerifier;

  @override
  State<AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<AuthGate> {
  bool _busy = false;
  String? _error;
  String? _repositoryUserId;
  CourseRepository? _courseRepository;
  MeetingRepository? _meetingRepository;
  SessionRepository? _sessionRepository;
  String? _verifiedBackendUserId;

  void _verifyBackendFor(String userId) {
    final verifier = widget.backendIdentityVerifier;
    if (verifier == null || _verifiedBackendUserId == userId) return;
    _verifiedBackendUserId = userId;
    unawaited(_verifyBackend(verifier));
  }

  Future<void> _verifyBackend(BackendIdentityVerifier verifier) async {
    try {
      await verifier.verifyIdentity();
      await widget.logger.logEvent('python_backend_identity_succeeded');
    } catch (error, stackTrace) {
      await widget.logger.recordError(
        error,
        stackTrace,
        context: 'python_backend_identity',
      );
    }
  }

  CourseRepository _repositoryFor(String userId) {
    if (_repositoryUserId != userId) {
      _repositoryUserId = userId;
      _courseRepository = widget.courseRepositoryFactory(userId);
      _meetingRepository = widget.meetingRepositoryFactory(userId);
      _sessionRepository = widget.sessionRepositoryFactory(userId);
    }
    return _courseRepository!;
  }

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
        if (user != null) {
          _verifyBackendFor(user.id);
          return CoursePage(
            repository: _repositoryFor(user.id),
            meetingRepository: _meetingRepository!,
            sessionRepository: _sessionRepository!,
            user: user,
            logger: widget.logger,
            onSignOut: () =>
                _run(AuditedOperation.logout, widget.authGateway.signOut),
          );
        }
        _verifiedBackendUserId = null;
        return Scaffold(
          appBar: AppBar(title: const Text('Frequência UFMG')),
          body: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: _signedOut(context),
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
}
