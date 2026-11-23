# Guia para apresentar a demo

Execute `python web.py` dentro de `demo/`. A página abre no navegador. Clique
**Usar dados de exemplo** ou crie uma disciplina em **Nova disciplina**. Registre
uma ausência e mostre o saldo; corrija para presença e mostre a mudança. Abra
**Agenda**, adicione uma prova e recarregue a página para mostrar a persistência.
Em **Ajustes**, execute os testes. O botão de reset permite recomeçar sem apagar
arquivos manualmente.

## Código que vale dominar

- `demo/models.py`: `Registro` guarda a situação atual de um encontro. A linha
  `self._registros[dia_encontro] = Registro(...)` associa uma data ao seu
  registro. Corrigir uma presença altera a situação daquele encontro depois de
  salvar no banco. `Disciplina.resumo()` recalcula os totais.
- `PoliticaChamada` é abstrata. `ChamadaUnica` e `ChamadaDupla` especializam
  `calcular_faltas()`. `Disciplina` chama a mesma operação nas duas políticas,
  demonstrando polimorfismo.
- `ControleAcademico` coordena a operação e liga funções de gravação à
  `Disciplina`. O setter `Disciplina.nome` valida e grava antes de alterar o
  nome; a presença exige operação própria e também grava antes da atualização.
- `demo/database.py` contém as transações SQLite. `demo/web.py` recebe dados da
  página e chama o controle. `demo/exemplo.py` monta uma amostra fictícia fora
  das classes; ela não é uma regra de frequência.

## Mapa do código por blocos

As linhas abaixo são um roteiro de leitura da cópia da demo. A ideia é explicar
um bloco por vez, acompanhando o fluxo de uma ação, e não comentar cada linha
trivial isoladamente.

### `demo/models.py` — regras e POO

| Linhas | Bloco | O que explicar |
|---|---|---|
| 24–49 | `PoliticaChamada`, `ChamadaUnica`, `ChamadaDupla` | A classe abstrata define o contrato `calcular_faltas`. As duas subclasses implementam a mesma operação com regras diferentes; isso é herança e polimorfismo. |
| 55–90 | `Registro` e `Atividade` | `Registro` representa a situação atual de uma data. `Atividade` representa prova ou trabalho e valida seus próprios dados. |
| 93–229 | `Disciplina` | Valida a grade, protege `_registros`, registra/corrige uma aula e recalcula o resumo. A gravação ocorre antes da alteração em memória para preservar o estado em caso de erro. |
| 234–391 | `ControleAcademico` | Coordena cadastro, busca, agenda, renomeação e reinício. `_vincular` conecta o domínio ao SQLite sem colocar SQL dentro das regras. |

### `demo/database.py` — persistência

| Linhas | Bloco | O que explicar |
|---|---|---|
| 18–67 | conexão e criação das tabelas | Abre o SQLite local e garante a estrutura mínima antes do uso. |
| 69–133 | cadastro e exemplo | Grava disciplina, registros pendentes e os dados de exemplo numa transação. |
| 135–199 | leitura e alterações | Recupera disciplinas/registros/atividades e salva correções, nomes e atividades. |
| 201–210 | `apagar_tudo` | Limpa as tabelas numa única operação; se houver erro, a transação não é confirmada. |

### `demo/web.py` — entrada da aplicação

| Linhas | Bloco | O que explicar |
|---|---|---|
| 31–119 | conversão, estado e rotas | Converte datas, transforma objetos em JSON e encaminha cada ação para `ControleAcademico`. |
| 121–222 | `DemoHandler` | Recebe GET/POST da página, traduz erros para respostas HTTP e executa os testes sem reutilizar os dados da demo. |
| 224–240 | `criar_servidor` e entrada | Inicia o servidor local em `127.0.0.1:8878`; este é o ponto de entrada, não existe um `main.py` separado. |

### O que mostrar ao professor

1. **Principal:** `demo/models.py`, porque concentra as classes, encapsulamento,
   abstração, herança e polimorfismo.
2. **Suporte indispensável:** `demo/database.py`, para mostrar persistência e
   transações, e `demo/web.py`, para mostrar a separação entre interface e
   regras de negócio.
3. **Evidência:** `demo/test_models.py` e `demo/test_web.py`, escolhendo um
   teste de sucesso e um de rejeição que preserva o estado.
4. **Auxiliares:** `demo/exemplo.py` apenas prepara os dados fictícios; os
   arquivos em `demo/web/` implementam a tela e não são o foco da explicação
   de POO. Não há `main.py` na versão final: `web.py` é o executável da demo.

## Perguntas prováveis

**Uma correção guarda o valor antigo?** Não. A mesma aula recebe a nova situação;
o banco mantém uma linha por data e recalcula o resumo depois da alteração.

**Como evita perda de dados quando o banco falha?** O SQLite conclui a transação
antes de atualizar a memória. Em erro, a situação anterior permanece.

**Por que existe uma classe abstrata?** As duas formas de chamada têm o mesmo
contrato de cálculo e regras distintas para atraso e saída antecipada.

**Por que há agenda?** É o menor complemento que vincula avaliações à matéria
sem alterar o controle de faltas. A integração automática ficou fora da demo.

**Como reiniciar?** Ajustes → Apagar dados da demo → digitar `APAGAR`.
