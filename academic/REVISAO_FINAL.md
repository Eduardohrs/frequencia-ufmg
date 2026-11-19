# Revisão interna da entrega acadêmica PF-02-AGENDA

Este registro descreve a versão do ZIP da PR #269. A avaliação é uma simulação de professora exigente e de pessoas usando a interface local e o terminal; **não é aprovação nem previsão de nota da professora**. A lente de acessibilidade ficou fora, conforme o recorte solicitado.

## Interface local acrescentada

O navegador agora é a apresentação principal: lista matérias pelo nome, abre os encontros da matéria, registra e corrige presença, mostra o saldo, reúne provas e trabalhos e oferece o reset em Ajustes. `web.py` é um servidor local da biblioteca padrão que converte pedidos JSON em operações de `ControleAcademico`; regras, faltas e persistência continuam em `models.py` e `database.py`. O terminal permanece como alternativa. O servidor escuta apenas `127.0.0.1`, e a demo não depende do aplicativo real, de login ou de rede externa.

Quatro testes da interface percorrem criação, ausência, correção, atividade, renomeação, reabertura, reset, rejeições, falhas de banco e encerramento. A interface foi aberta em Chrome com largura de computador e celular. A primeira inspeção detectou que a política de estilo bloqueava a barra de frequência; a correção foi aplicada antes da última conferência. O PDF do produto recebeu arquitetura, sequência e roteiro do navegador; a Verificação recebeu os cenários W01–W05 e T23–T26.

## Falha que invalidou a revisão anterior

Depois de abrir a demo, Eduardo percebeu que Consultar ainda exigia digitar o código da disciplina. O menu anterior mostrava os códigos, mas isso não resolvia o esforço de lembrar, copiar ou adivinhar qual escolher. A revisão anterior chamou esse caminho de aprovado sem percorrer a consulta como um estudante real; essa conclusão estava errada.

Agora Registrar, Consultar, Corrigir, Adicionar atividade e Renomear mostram a mesma lista **numerada por nome**, com o código secundário entre parênteses. A lista aceita um número exibido ou `0` para voltar. A agenda também identifica cada atividade pelo nome da disciplina. O programa mostra uma mensagem curta se ainda não existe disciplina.

O menu ganhou **8 Recomeçar do zero**. Ele só apaga depois de receber exatamente `APAGAR`. O banco remove atividades, registros e disciplinas em uma transação; a memória muda após o commit. Resposta diferente cancela. Uma falha SQL desfaz a transação e mantém o estado anterior. O banco permanece utilizável para criar disciplinas de novo.

## Inventário percorrido nesta rodada

| Caminho do usuário | Estado e efeito verificados | Evidência |
| --- | --- | --- |
| Abrir banco vazio; tentar ações 2, 3, 4, 5 e 7 | Cada ação orienta a criar disciplina, sem pedir código nem alterar dados. | T16 e execução real do terminal. |
| 1 Criar disciplina | Código, nome, chamadas, aulas e datas validados; cadastro e grade entram juntos ou não entram. | T01–T04, T15 e T16. |
| 2 Registrar presença | Seleção numerada, data da grade, situação e cálculo por política; escrita confirmada antes da memória. | T05–T07, T11 e T19. |
| 3 Consultar frequência | Nome numerado em ordem alfabética; número válido abre a matéria certa. Número inválido e `0` não alteram estado. | T10, T11 e T20. |
| 4 Corrigir registro | Exige data resolvida, substitui o registro e recalcula sem acumular falta. | T08, T09 e T11. |
| 5 Adicionar atividade | Seleciona pelo nome; prova ou trabalho persistem sem mudar a frequência. | T12–T14. |
| 6 Ver agenda | Mostra nome e código secundário, ordem por data e inserção; informa agenda vazia. | T14 e T21. |
| 7 Renomear disciplina | Seleciona pelo nome; altera só o nome após escrita confirmada, inclusive após reabrir. | T14, T17 e T18. |
| 8 Recomeçar do zero | Enter e resposta errada cancelam; `APAGAR` limpa banco e memória; falha no segundo `DELETE` faz rollback. | T21 e T22. |
| Interface local | A página usa o mesmo domínio, oferece seleção por nome e preserva os dados após atualizar. | T23–T26, conferência visual em Chrome. |
| 0 Sair, fim de entrada e interrupção | Encerra sem traceback; dados salvos reaparecem na abertura seguinte. | T04, T11, T14 e testes do menu. |

## Leitura por perspectivas

| Perspectiva | Pergunta prática | Resultado desta rodada |
| --- | --- | --- |
| Professora exigente | O produto final entrega todas as funções declaradas, contratos, camadas, classes, persistência e diagramas fiéis? A Verificação cobre sucesso, rejeição, estado e evidência por função? | F01–F08 constam no produto e na matriz; o novo fluxo e o reset aparecem nos contratos, código, cenários e diagrama. Os enunciados foram relidos e comparados aos PDFs. |
| Jordan, iniciante | Consigo começar sem saber um código e descobrir como consultar? | A opção 3 mostra nomes e números; sem cadastro, aponta a opção 1. O README explica o percurso. |
| Riley, testador exigente | Número errado, cancelamento, valores inválidos e falha durante o reset deixam dados parciais? | A escolha rejeita ou volta; `APAGAR` é obrigatório; uma falha no segundo `DELETE` preservou falta, atividade e cadastro no SQLite reaberto. |
| Casey, pessoa distraída | Se eu sair, voltar ou escolher a matéria errada, perco dados? | As matérias aparecem por nome a cada seleção; reabertura preservou registros e agenda; `0` volta sem mudança. |
| Alex, usuário impaciente | Preciso copiar códigos ou executar comando externo para recomeçar? | Escolhe por número; reset está no menu. O caminho curto cria, registra, consulta e recomeça sem comando de sistema. |
| Leitora rigorosa de formatação | Há título isolado, tabela cortada, página órfã ou diagrama ilegível? | Os dois PDFs foram renderizados e conferidos novamente: 12 páginas no Produto e 11 na Verificação, sem página órfã. |

## Critérios dos enunciados e evidências

- **Produto final:** problema, público, recorte e alterações de escopo nas páginas iniciais; contratos F01–F08; regras com unidades e exemplos; classes, especialização e polimorfismo; sequências do cadastro, registro, atividade e reset; camadas e SQLite; instruções, dados fictícios e limites. O ZIP identificado no relatório contém código, banco vazio, gerador de exemplo, README e testes.
- **Verificação:** uma matriz por função com estado inicial, regra e entrada, esperado, observado, situação e teste associado; cenários da interface e mapa T01–T26; defeitos reproduzidos e corrigidos; resultado integral da última execução no PDF e em `evidencias/unittest.txt`.
- **Execução independente:** o verificador extrai o ZIP, roda os testes e percorre criação, registro, atividade, renomeação, consulta, reabertura, reset e nova abertura. Os testes usam bancos temporários; não tocam nos dados reais do aplicativo.
- **Resultado técnico:** 31 testes aprovados, incluindo quatro da interface; cobertura de linhas de 100% nos módulos Python da demo e análise estática aprovadas. Os checks da PR devem ser verificados no commit final antes do merge.

## Limites declarados

A demo acadêmica não conecta ao Moodle/SIGA nem usa GPS; a grade precisa ser informada no cadastro, e não há inclusão posterior de reposição. O reset apaga os dados **desta demo** e exige confirmação. A aceitação do escopo e a nota dependem da professora. A revisão interna confirma os comportamentos testados, sem prometer avaliação externa.
