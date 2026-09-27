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
