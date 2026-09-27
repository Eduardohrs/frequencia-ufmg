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
}
