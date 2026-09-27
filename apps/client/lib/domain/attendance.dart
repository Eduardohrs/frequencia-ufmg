enum QuantidadeAulas {
  one(1),
  two(2),
  four(4);

  const QuantidadeAulas(this.value);

  final int value;

  static QuantidadeAulas fromValue(int value) {
    for (final option in values) {
      if (option.value == value) return option;
    }
    throw ArgumentError.value(value, 'value', 'unsupported lesson count');
  }
}

enum NumeroChamadas {
  one(1),
  two(2);

  const NumeroChamadas(this.value);

  final int value;

  static NumeroChamadas fromValue(int value) {
    for (final option in values) {
      if (option.value == value) return option;
    }
    throw ArgumentError.value(value, 'value', 'unsupported call count');
  }
}

enum EstadoPing {
  onCampus('no_campus'),
  away('fora'),
  unavailable('indisponivel');

  const EstadoPing(this.code);

  final String code;

  static EstadoPing fromCode(String code) {
    for (final option in values) {
      if (option.code == code) return option;
    }
    throw ArgumentError.value(code, 'code', 'unsupported ping state');
  }
}

enum SituacaoFrequencia {
  present('presente'),
  arrivedLate('chegou_atrasado'),
  leftEarly('saiu_mais_cedo'),
  absent('ausente'),
  pending('pendente');

  const SituacaoFrequencia(this.code);

  final String code;

  static SituacaoFrequencia fromCode(String code) {
    for (final option in values) {
      if (option.code == code) return option;
    }
    throw ArgumentError.value(code, 'code', 'unsupported attendance status');
  }
}

abstract interface class PoliticaFrequencia {
  SituacaoFrequencia classificar(
    EstadoPing primeiroPing,
    EstadoPing segundoPing,
  );

  int? calcularFaltas(QuantidadeAulas aulas, SituacaoFrequencia situacao);
}

final class ConfiguracaoSessao {
  ConfiguracaoSessao({required this.aulas, required this.chamadas}) {
    if (aulas == QuantidadeAulas.one && chamadas == NumeroChamadas.two) {
      throw ArgumentError('one lesson cannot have two attendance calls');
    }
  }

  final QuantidadeAulas aulas;
  final NumeroChamadas chamadas;
}

final class SessaoAula {
  SessaoAula(String identifier, this.configuracao)
    : identifier = _requiredText(identifier, 'identifier');

  final String identifier;
  final ConfiguracaoSessao configuracao;

  SituacaoFrequencia classificar(
    EstadoPing primeiroPing,
    EstadoPing segundoPing,
  ) => _politicaFrequencia(
    configuracao.chamadas,
  ).classificar(primeiroPing, segundoPing);

  int? calcularFaltas(SituacaoFrequencia situacao) => _politicaFrequencia(
    configuracao.chamadas,
  ).calcularFaltas(configuracao.aulas, situacao);
}

final class RegistroFrequencia {
  RegistroFrequencia(this.sessao, SituacaoFrequencia situacao)
    : _situacao = situacao,
      _faltas = sessao.calcularFaltas(situacao);

  final SessaoAula sessao;
  SituacaoFrequencia _situacao;
  int? _faltas;

  SituacaoFrequencia get situacao => _situacao;
  int? get faltas => _faltas;

  void corrigir(SituacaoFrequencia situacao, int? faltas) {
    if (situacao == SituacaoFrequencia.pending) {
      if (faltas != null) {
        throw ArgumentError('a pending status cannot have absences');
      }
    } else {
      if (faltas == null) {
        throw ArgumentError('a resolved status requires absences');
      }
      if (faltas < 0 || faltas > sessao.configuracao.aulas.value) {
        throw ArgumentError.value(
          faltas,
          'faltas',
          'absences must fit the session lesson count',
        );
      }
    }
    _situacao = situacao;
    _faltas = faltas;
  }
}

final class ResumoDisciplina {
  const ResumoDisciplina({
    required this.codigo,
    required this.totalSessoes,
    required this.sessoesPendentes,
    required this.faltasConsumidas,
    required this.limiteFaltas,
    required this.faltasRestantes,
  });

  final String codigo;
  final int totalSessoes;
  final int sessoesPendentes;
  final int faltasConsumidas;
  final int limiteFaltas;
  final int faltasRestantes;
}

final class Disciplina {
  Disciplina(String codigo, String nome, this.cargaHoraria)
    : codigo = _requiredText(codigo, 'codigo'),
      nome = _requiredText(nome, 'nome') {
    if (cargaHoraria <= 0) {
      throw ArgumentError.value(
        cargaHoraria,
        'cargaHoraria',
        'workload must be positive',
      );
    }
  }

  final String codigo;
  final String nome;
  final int cargaHoraria;
  final List<SessaoAula> _sessoes = [];
  final Map<String, RegistroFrequencia> _registros = {};

  int get limiteFaltas => cargaHoraria ~/ 4;
  List<SessaoAula> get sessoes => List.unmodifiable(_sessoes);

  List<RegistroFrequencia> get registros => List.unmodifiable(
    _sessoes
        .where((session) => _registros.containsKey(session.identifier))
        .map((session) => _registros[session.identifier]!),
  );

  void adicionarSessao(SessaoAula sessao) {
    if (_sessoes.any((item) => item.identifier == sessao.identifier)) {
      throw StateError('session already belongs to this course');
    }
    _sessoes.add(sessao);
  }

  int faltasRestantes(int faltasConsumidas) {
    if (faltasConsumidas < 0) {
      throw ArgumentError.value(
        faltasConsumidas,
        'faltasConsumidas',
        'consumed absences cannot be negative',
      );
    }
    final remaining = limiteFaltas - faltasConsumidas;
    return remaining < 0 ? 0 : remaining;
  }

  RegistroFrequencia registrarFrequencia(
    String identificadorSessao,
    SituacaoFrequencia situacao,
  ) {
    final session = _buscarSessao(identificadorSessao);
    final record = RegistroFrequencia(session, situacao);
    _registros[session.identifier] = record;
    return record;
  }

  ResumoDisciplina resumo() {
    final currentRecords = registros;
    final consumedAbsences = currentRecords.fold(
      0,
      (total, record) => total + (record.faltas ?? 0),
    );
    final resolvedSessions = currentRecords
        .where((record) => record.faltas != null)
        .length;
    return ResumoDisciplina(
      codigo: codigo,
      totalSessoes: _sessoes.length,
      sessoesPendentes: _sessoes.length - resolvedSessions,
      faltasConsumidas: consumedAbsences,
      limiteFaltas: limiteFaltas,
      faltasRestantes: faltasRestantes(consumedAbsences),
    );
  }

  SessaoAula _buscarSessao(String identifier) {
    final normalized = identifier.trim();
    for (final session in _sessoes) {
      if (session.identifier == normalized) return session;
    }
    throw ArgumentError.value(
      identifier,
      'identificadorSessao',
      'session does not belong to this course',
    );
  }
}

final class _PoliticaChamadaUnica implements PoliticaFrequencia {
  const _PoliticaChamadaUnica();

  @override
  SituacaoFrequencia classificar(
    EstadoPing primeiroPing,
    EstadoPing segundoPing,
  ) {
    if (primeiroPing == EstadoPing.unavailable ||
        segundoPing == EstadoPing.unavailable) {
      if (primeiroPing == EstadoPing.onCampus ||
          segundoPing == EstadoPing.onCampus) {
        return SituacaoFrequencia.present;
      }
      return SituacaoFrequencia.pending;
    }
    return _classificarPingsValidos(primeiroPing, segundoPing);
  }

  @override
  int? calcularFaltas(QuantidadeAulas aulas, SituacaoFrequencia situacao) {
    if (situacao == SituacaoFrequencia.pending) return null;
    if (situacao == SituacaoFrequencia.absent) return aulas.value;
    return 0;
  }
}

final class _PoliticaDuasChamadas implements PoliticaFrequencia {
  const _PoliticaDuasChamadas();

  @override
  SituacaoFrequencia classificar(
    EstadoPing primeiroPing,
    EstadoPing segundoPing,
  ) {
    if (primeiroPing == EstadoPing.unavailable ||
        segundoPing == EstadoPing.unavailable) {
      return SituacaoFrequencia.pending;
    }
    return _classificarPingsValidos(primeiroPing, segundoPing);
  }

  @override
  int? calcularFaltas(QuantidadeAulas aulas, SituacaoFrequencia situacao) {
    if (situacao == SituacaoFrequencia.pending) return null;
    if (situacao == SituacaoFrequencia.present) return 0;
    if (situacao == SituacaoFrequencia.absent) return aulas.value;
    return aulas.value ~/ 2;
  }
}

PoliticaFrequencia _politicaFrequencia(NumeroChamadas chamadas) =>
    switch (chamadas) {
      NumeroChamadas.one => const _PoliticaChamadaUnica(),
      NumeroChamadas.two => const _PoliticaDuasChamadas(),
    };

SituacaoFrequencia _classificarPingsValidos(
  EstadoPing primeiroPing,
  EstadoPing segundoPing,
) {
  if (primeiroPing == EstadoPing.onCampus) {
    return segundoPing == EstadoPing.onCampus
        ? SituacaoFrequencia.present
        : SituacaoFrequencia.leftEarly;
  }
  return segundoPing == EstadoPing.onCampus
      ? SituacaoFrequencia.arrivedLate
      : SituacaoFrequencia.absent;
}

String _requiredText(String value, String field) {
  final normalized = value.trim();
  if (normalized.isEmpty) {
    throw ArgumentError.value(value, field, 'value is required');
  }
  return normalized;
}
