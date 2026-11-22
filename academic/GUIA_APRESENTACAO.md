# Guia para apresentar a demo

Execute `python web.py` dentro de `demo/`. A página abre no navegador. Clique
**Usar dados de exemplo** ou crie uma disciplina em **Nova disciplina**. Registre
uma ausência e mostre o saldo; corrija para presença e mostre a mudança. Abra
**Agenda**, adicione uma prova e recarregue a página para mostrar a persistência.
Em **Ajustes**, execute os testes. O botão de reset permite recomeçar sem apagar
arquivos manualmente.

## Código que vale dominar

- `demo/models.py`: `Registro` é um retrato imutável de um encontro. A linha
  `self._registros[dia_encontro] = Registro(...)` associa uma data ao seu
  registro. Corrigir uma presença cria outro `Registro` e troca apenas o valor
  daquela data. `Disciplina.resumo()` recalcula os totais.
- `PoliticaChamada` é abstrata. `ChamadaUnica` e `ChamadaDupla` especializam
  `calcular_faltas()`. `Disciplina` chama a mesma operação nas duas políticas,
  demonstrando polimorfismo.
- `ControleAcademico` coordena a operação e liga funções de gravação à
  `Disciplina`. O setter `Disciplina.nome` valida e grava antes de alterar o
  nome; a presença exige operação própria e também grava antes da troca.
- `demo/database.py` contém as transações SQLite. `demo/web.py` recebe dados da
  página e chama o controle. `demo/exemplo.py` monta uma amostra fictícia fora
  das classes; ela não é uma regra de frequência.

## Perguntas prováveis

**Por que o registro é imutável se dá para corrigir?** O objeto não muda. A
disciplina guarda uma nova versão para a mesma data, após validar e salvar.

**Como evita perda de dados quando o banco falha?** O SQLite conclui a transação
antes de atualizar a memória. Em erro, a substituição não acontece.

**Por que existe uma classe abstrata?** As duas formas de chamada têm o mesmo
contrato de cálculo e regras distintas para atraso e saída antecipada.

**Por que há agenda?** É o menor complemento que vincula avaliações à matéria
sem alterar o controle de faltas. A integração automática ficou fora da demo.

**Como reiniciar?** Ajustes → Apagar dados da demo → digitar `APAGAR`.
