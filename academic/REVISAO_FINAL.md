# Revisão interna da entrega acadêmica PF-02-AGENDA

Este registro descreve a versão do ZIP da PR #269. A avaliação é uma simulação de professora exigente e de pessoas usando a interface local e o terminal; **não é aprovação nem previsão de nota da professora**. A lente de acessibilidade ficou fora, conforme o recorte solicitado.

## Interface local acrescentada

O navegador agora é a apresentação principal: lista matérias pelo nome, abre os encontros da matéria, registra e corrige presença, mostra o saldo, reúne provas e trabalhos e oferece o reset em Ajustes. `web.py` é um servidor local da biblioteca padrão que converte pedidos JSON em operações de `ControleAcademico`; regras, faltas e persistência continuam em `models.py` e `database.py`. O terminal permanece como alternativa. O servidor escuta apenas `127.0.0.1`, e a demo não depende do aplicativo real, de login ou de rede externa.

Quatro testes da interface percorrem criação, ausência, correção de presença e data, atividade, renomeação, reabertura, reset, rejeições, falhas de banco e encerramento. Dois testes adicionais isolam a correção de data no domínio e no SQLite. A interface foi aberta em Chrome no computador e em larguras móveis de 390 e 320 px. O PDF do produto recebeu arquitetura, sequência e roteiro do navegador; a Verificação inclui W01–W06 e T23–T28.

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
| Interface local | A página usa o mesmo domínio, oferece seleção por nome, correção de data e preserva os dados após atualizar. | T23–T28, conferência visual em Chrome. |
| 0 Sair, fim de entrada e interrupção | Encerra sem traceback; dados salvos reaparecem na abertura seguinte. | T04, T11, T14 e testes do menu. |

## Leitura por perspectivas

| Perspectiva | Pergunta prática | Resultado desta rodada |
| --- | --- | --- |
| Professora exigente | O produto final entrega todas as funções declaradas, contratos, camadas, classes, persistência e diagramas fiéis? A Verificação cobre sucesso, rejeição, estado e evidência por função? | F01–F08 constam no produto e na matriz; o novo fluxo e o reset aparecem nos contratos, código, cenários e diagrama. Os enunciados foram relidos e comparados aos PDFs. |
| Jordan, iniciante | Consigo começar pelo estado vazio e entender a primeira ação? | A agenda vazia oferece Criar disciplina; o cadastro aceita a data digitada sem exigir um segundo botão; uma aula impede a opção impossível de duas chamadas. |
| Riley, testador exigente | Título enorme, data repetida, colisão de datas, falha no disco ou reset errado alteram dados? | Título de 110 caracteres não ampliou a tela; testes rejeitaram colisões e falha de escrita sem trocar a presença; `APAGAR` continua obrigatório. |
| Casey, pessoa distraída | Se eu mudar de aba, recarregar ou errar a data de uma aula registrada, perco o contexto? | A aba e a disciplina selecionada persistem; Corrigir data preserva situação e faltas após recarregar. No celular, um seletor mostra todas as matérias pelo nome. |
| Alex, usuário impaciente | Preciso de cliques extras ou decorar códigos? | A data do formulário entra no cadastro ao enviar; lista e detalhe usam nome como referência principal; a agenda vazia leva diretamente ao cadastro. |
| Estudante exigente | Uma mensagem sem ação ou um layout cortado me obriga a adivinhar o próximo passo? | A ação vazia da agenda é explícita; título longo e três matérias em 320 px não cortam controles; presença e mudança de data dão retorno visível. |
| Leitora rigorosa de formatação | Há título isolado, tabela cortada, página órfã ou diagrama ilegível? | Os dois PDFs foram renderizados novamente: 12 páginas no Produto e 11 na Verificação. A tabela de testes, que havia gerado uma página órfã, foi compactada e conferida. |

Uma nova passada encontrou um estado que a anterior não havia exercitado: duas ausências de duas aulas numa grade de oito produzem quatro faltas usadas, limite de duas e excesso de duas. O domínio devolvia `excesso=2`, mas a página mostrava somente “0 faltas restantes”. A tela agora mostra “2 faltas acima do limite” em destaque. O caso foi reproduzido no Chrome a 320 px, com banco temporário; a largura permaneceu 320 px. As seis perspectivas não deixaram comentário de correção aberto **nos fluxos examinados após essa correção**. A automação também percorreu desktop e 390 px: estado vazio, cadastro, configuração incompatível, ausência, mudança de data, recarga, título longo, alternância de disciplina, agenda e reset. Os testes de domínio cobrem rejeições e rollback. Essa conclusão não equivale a uma avaliação externa nem cobre serviços do aplicativo completo.

Uma terceira passada examinou a falha inicial de leitura do SQLite. Antes, um aviso desaparecia após alguns segundos e restava uma tela sem dados nem caminho de recuperação. Agora o erro permanece visível, as ações que dependem dos dados ficam ocultas e **Tentar novamente** recarrega o estado quando o banco volta. O Chrome repetiu a falha por mais de cinco segundos, restaurou a leitura e confirmou a recuperação com banco temporário. Depois disso, os percursos de cadastro, correção, agenda, excesso de faltas, recarga e reset foram repetidos. Nenhuma correção permanece aberta **nesses caminhos testados**.

A quarta passada acrescentou cenários que as anteriores não haviam coberto. Com três disciplinas a 320 px, a terceira estava totalmente escondida numa faixa horizontal sem indicador; um seletor nativo agora lista todas pelo nome e troca a matéria. Um nome longo era quebrado no meio de palavras pelo botão Renomear; em telas estreitas, o botão desce e o nome usa a largura disponível. A agenda omitia o ano, tornando prazos de 2026 e 2027 indistinguíveis; o cartão agora exibe os quatro dígitos. Ao voltar de outra aba, os dados ficavam antigos; a página relê o SQLite quando retorna e, se havia formulário aberto, relê após fechá-lo. Uma falha nessa releitura escondia dados já carregados; agora mantém a última leitura visível com aviso de desatualização e recuperação por botão.

Após essas correções, a passada completa em Chrome com bancos temporários percorreu estado vazio, três disciplinas, formulário curto de 320 × 568 px, seis situações de frequência, falha e recuperação de gravação, colisão e correção de data, duas atividades em anos diferentes, renomeação, recarga, reset cancelado e confirmado, troca entre abas com e sem formulário aberto, falhas de leitura inicial e posterior, além de larguras de 320 e 390 px e desktop. Nenhum defeito novo apareceu **nesses caminhos executados**. Os serviços externos e o aplicativo completo permanecem fora desta revisão da demo acadêmica.

Na quinta passada, a perspectiva de estudante exigente encontrou três confirmações enganosas: Renomear com o mesmo nome, Corrigir data com o mesmo dia e Corrigir registro sem mudar a situação permitiam clicar em Salvar e anunciavam uma alteração inexistente. Os três botões agora começam desabilitados e só habilitam quando o campo muda; voltar ao valor original os desabilita novamente. Também foi repetida a rejeição de código duplicado e de título ou nome vazios. Após a correção, a matriz funcional e as passadas de 320 px, 390 px, desktop, duas abas e falhas de leitura passaram novamente sem nova observação nos caminhos executados.

## Critérios dos enunciados e evidências

- **Produto final:** problema, público, recorte e alterações de escopo nas páginas iniciais; contratos F01–F08; regras com unidades e exemplos; classes, especialização e polimorfismo; sequências do cadastro, registro, atividade e reset; camadas e SQLite; instruções, dados fictícios e limites. O ZIP identificado no relatório contém código, banco vazio, gerador de exemplo, README e testes.
- **Verificação:** uma matriz por função com estado inicial, regra e entrada, esperado, observado, situação e teste associado; cenários da interface e mapa T01–T28; defeitos reproduzidos e corrigidos; resultado integral da última execução no PDF e em `evidencias/unittest.txt`.
- **Execução independente:** o verificador extrai o ZIP, roda os testes e percorre criação, registro, atividade, renomeação, consulta, reabertura, reset e nova abertura. Os testes usam bancos temporários; não tocam nos dados reais do aplicativo.
- **Resultado técnico:** 33 testes aprovados, incluindo quatro da interface e dois novos da correção de data; cobertura de linhas de 100% nos módulos Python da demo e análise estática aprovadas. No Chrome, o fluxo completo passou em computador, 390 px e 320 px com banco temporário. Os checks da PR devem ser verificados no commit final antes do merge.

## Limites declarados

A demo acadêmica não conecta ao Moodle/SIGA nem usa GPS; a grade precisa ser informada no cadastro, e não há inclusão posterior de reposição. O reset apaga os dados **desta demo** e exige confirmação. A aceitação do escopo e a nota dependem da professora. A revisão interna confirma os comportamentos testados, sem prometer avaliação externa.
