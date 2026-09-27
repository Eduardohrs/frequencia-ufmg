import 'package:flutter_test/flutter_test.dart';
import 'package:frequencia_ufmg/domain/attendance.dart';

void main() {
  group('session configuration', () {
    test('rejects two calls for a one-lesson session', () {
      expect(
        () => ConfiguracaoSessao(
          aulas: QuantidadeAulas.one,
          chamadas: NumeroChamadas.two,
        ),
        throwsArgumentError,
      );
    });

    test('rejects unsupported serialized enum values', () {
      expect(() => QuantidadeAulas.fromValue(3), throwsArgumentError);
      expect(() => NumeroChamadas.fromValue(3), throwsArgumentError);
      expect(() => EstadoPing.fromCode('unknown'), throwsArgumentError);
      expect(() => SituacaoFrequencia.fromCode('unknown'), throwsArgumentError);
    });
  });

  test('session normalizes and requires its identifier', () {
    final session = SessaoAula(
      '  class-01  ',
      ConfiguracaoSessao(
        aulas: QuantidadeAulas.two,
        chamadas: NumeroChamadas.one,
      ),
    );

    expect(session.identifier, 'class-01');
    expect(
      () => SessaoAula(
        '   ',
        ConfiguracaoSessao(
          aulas: QuantidadeAulas.two,
          chamadas: NumeroChamadas.one,
        ),
      ),
      throwsArgumentError,
    );
  });

  group('course aggregate', () {
    test('normalizes its data and protects its session collection', () {
      final course = Disciplina('  DCC203 ', ' POO  ', 60);
      final session = _session('class-01');

      course.adicionarSessao(session);

      expect(course.codigo, 'DCC203');
      expect(course.nome, 'POO');
      expect(course.cargaHoraria, 60);
      expect(course.limiteFaltas, 15);
      expect(course.sessoes, [session]);
      expect(
        () => course.sessoes.add(_session('class-02')),
        throwsUnsupportedError,
      );
      expect(
        () => course.adicionarSessao(_session('class-01')),
        throwsStateError,
      );
    });

    test('requires course text and a positive workload', () {
      expect(() => Disciplina(' ', 'POO', 60), throwsArgumentError);
      expect(() => Disciplina('DCC203', ' ', 60), throwsArgumentError);
      expect(() => Disciplina('DCC203', 'POO', 0), throwsArgumentError);
    });

    test('reports a registered result and the remaining allowance', () {
      final course = Disciplina('DCC203', 'POO', 60);
      final session = SessaoAula(
        'class-01',
        ConfiguracaoSessao(
          aulas: QuantidadeAulas.four,
          chamadas: NumeroChamadas.two,
        ),
      );
      course.adicionarSessao(session);

      final record = course.registrarFrequencia(
        ' class-01 ',
        SituacaoFrequencia.arrivedLate,
      );
      final summary = course.resumo();

      expect(record.sessao, same(session));
      expect(record.situacao, SituacaoFrequencia.arrivedLate);
      expect(record.faltas, 2);
      expect(course.registros, [record]);
      expect(summary.codigo, 'DCC203');
      expect(summary.totalSessoes, 1);
      expect(summary.sessoesPendentes, 0);
      expect(summary.faltasConsumidas, 2);
      expect(summary.limiteFaltas, 15);
      expect(summary.faltasRestantes, 13);
    });

    test('counts missing and pending sessions without consuming absences', () {
      final course = Disciplina('DCC203', 'POO', 60);
      course.adicionarSessao(_session('class-01'));
      course.adicionarSessao(_session('class-02'));

      final record = course.registrarFrequencia(
        'class-01',
        SituacaoFrequencia.pending,
      );
      final summary = course.resumo();

      expect(record.faltas, isNull);
      expect(summary.totalSessoes, 2);
      expect(summary.sessoesPendentes, 2);
      expect(summary.faltasConsumidas, 0);
      expect(summary.faltasRestantes, 15);
    });

    test('replaces the current result without retaining history', () {
      final course = Disciplina('DCC203', 'POO', 60);
      course.adicionarSessao(_session('class-01'));

      final previous = course.registrarFrequencia(
        'class-01',
        SituacaoFrequencia.absent,
      );
      final current = course.registrarFrequencia(
        'class-01',
        SituacaoFrequencia.present,
      );

      expect(current, isNot(same(previous)));
      expect(course.registros, [current]);
      expect(course.resumo().faltasConsumidas, 0);
      expect(() => course.registros.clear(), throwsUnsupportedError);
    });

    test('rejects an unknown session and invalid consumed absences', () {
      final course = Disciplina('DCC203', 'POO', 60);

      expect(
        () => course.registrarFrequencia('unknown', SituacaoFrequencia.present),
        throwsArgumentError,
      );
      expect(() => course.faltasRestantes(-1), throwsArgumentError);
      expect(course.faltasRestantes(0), 15);
      expect(course.faltasRestantes(15), 0);
      expect(course.faltasRestantes(16), 0);
    });
  });

  group('manual correction', () {
    test('overwrites the current status and absence count', () {
      final record = RegistroFrequencia(
        _session('class-01'),
        SituacaoFrequencia.absent,
      );

      record.corrigir(SituacaoFrequencia.leftEarly, 1);
      expect(record.situacao, SituacaoFrequencia.leftEarly);
      expect(record.faltas, 1);

      record.corrigir(SituacaoFrequencia.pending, null);
      expect(record.situacao, SituacaoFrequencia.pending);
      expect(record.faltas, isNull);
    });

    test('rejects inconsistent or out-of-range absence counts', () {
      final record = RegistroFrequencia(
        _session('class-01'),
        SituacaoFrequencia.present,
      );

      expect(
        () => record.corrigir(SituacaoFrequencia.pending, 0),
        throwsArgumentError,
      );
      expect(
        () => record.corrigir(SituacaoFrequencia.present, null),
        throwsArgumentError,
      );
      expect(
        () => record.corrigir(SituacaoFrequencia.present, -1),
        throwsArgumentError,
      );
      expect(
        () => record.corrigir(SituacaoFrequencia.present, 3),
        throwsArgumentError,
      );
    });
  });
}

SessaoAula _session(String identifier) => SessaoAula(
  identifier,
  ConfiguracaoSessao(aulas: QuantidadeAulas.two, chamadas: NumeroChamadas.one),
);
