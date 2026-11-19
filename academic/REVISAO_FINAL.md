# Revisão da entrega acadêmica PF-02-AGENDA

Revisão interna do pacote `Frequencia_UFMG_Entrega_Final.zip`. Este registro **não substitui a avaliação da professora**. Foi feito sobre os PDFs renderizados, o código e o ZIP extraído, comparados aos enunciados de Produto final e Verificação. A lente acadêmica usa a skill pública `peer-review` em modo *homework*; a lente de primeiro uso usa a skill `impeccable`, adaptada ao terminal e ao material escrito.

## Rodadas de revisão e correção

| Rodada | Achado concreto | Correção | Rechecagem |
| --- | --- | --- | --- |
| Formatação | A versão anterior tinha blocos de texto desalinhados e diagramas pouco legíveis. | Os relatórios foram refeitos em A4 com tipografia, margens, cabeçalhos, rodapés, tabelas e diagramas vetoriais consistentes. | Todas as 9 páginas do Produto e 8 da Verificação foram renderizadas e examinadas visualmente; não há texto sobreposto, cortado ou página órfã. |
| Professora exigente | O protótipo anterior não bastava, por si só, para evidenciar produto completo, persistência e contratos verificáveis. | A entrega ganhou agenda de provas/trabalhos, consulta, correção e renomeação, SQLite, dados fictícios isolados, contratos F01–F07 e diagramas atualizados. | O ZIP extraído executa o menu desde banco vazio, grava presença/atividade/nome e recupera os três após reiniciar. |
| Professora exigente | Uma frase do cálculo usava “A soma as faltas”, deixando a variável A pouco clara. | A definição passou a ser “A é a soma das faltas de registros resolvidos.” | O texto extraído da página 5 do Produto foi relido após gerar o PDF final. |
| Professora exigente | Código e evidência anteriores à última revisão poderiam divergir do pacote enviado. | A evidência de unittest foi regenerada, os arquivos da demo e os PDFs foram copiados novamente para o pacote, e o ZIP foi reconstruído. | 24 testes aprovados; os quatro módulos do programa têm 100% de cobertura de linhas; `verify_package.py` repete testes e fluxo sobre o ZIP extraído. |
| Apresentação oral | Algumas operações do domínio ainda tinham comentários curtos demais para explicar entradas, unidades e momento da persistência. | Foram ampliados os docstrings de cadastro, registro, cálculo, agenda, consulta e renomeação, além das funções do menu. | Leitura do código em `demo/models.py`, `demo/database.py` e `demo/main.py`; testes e formatação continuaram passando. |
| Iniciante sem contexto | O README não especificava que o terminal precisava estar dentro de `demo/`; após reiniciar, o menu exigia lembrar o código. | O README informa a pasta de trabalho e o menu lista código e nome das disciplinas cadastradas. | O comando foi repetido a partir do ZIP extraído; o teste de reabertura verifica a lista. |
| Professora exigente | A opção Corrigir aceitava uma aula pendente, embora o contrato reservasse o primeiro registro à opção Registrar. | Corrigir agora exige situação já resolvida; a mensagem indica a opção certa. O contrato F03 e o cenário C12 registram a rejeição. | O teste compara grade e totais antes e depois das duas rejeições de C12. |
| Usuário sem suporte | Falha do SQLite ao iniciar produzia exceção antes de o menu aparecer. | O programa apresenta uma mensagem compreensível e encerra sem permitir ações que não poderia salvar. | Um teste simula a falha na abertura do banco. |
| Professora exigente, terceira leitura | O relatório dava o identificador da versão, mas não nomeava literalmente o arquivo ZIP exigido no enunciado. | A primeira página agora indica `Frequencia_UFMG_Entrega_Final.zip` e resume seu conteúdo. | O texto da primeira página foi extraído do PDF final e comparado ao nome do arquivo entregue. |
| Professora exigente, quarta leitura | A lista `ControleAcademico.disciplinas` devolvia objetos mutáveis sem a fachada SQLite. Registrar presença por essa lista mudava a memória, mas a reabertura ainda mostrava pendente; atribuir `nome` à fachada também não persistia. | A lista devolve fachadas no modo SQLite e o setter da fachada grava o nome antes de alterar a memória. | T04 registra pela lista e reabre; T17/T18 exercitam o setter, as rejeições e a falha de escrita. Os 24 testes e a cobertura integral passaram novamente. |
| Professora exigente, leitura da matriz | Os títulos dos cenários sugeriam que todos os testes usavam a mesma grade, e F05 não comprovava que uma atividade pode ficar fora de uma data de aula. | Os cabeçalhos e C09 distinguem as bases de teste; T12 agora agenda prova em 03/11, entre aulas de 02/11 e 04/11. C17/C18 também verificam que a frequência não muda. | Código dos testes, linhas C09/C16–C18 e resultados foram conferidos lado a lado. |
| Leitora rigorosa com diagramas | As mensagens dos diagramas de sequência apareciam como linhas sem direção visível. | Cada mensagem recebeu ponta de seta vetorial, inclusive retornos ao menu e ao estudante. | As páginas dos diagramas foram renderizadas novamente e verificadas em tamanho de leitura. |
| Professora exigente, quinta leitura | O enunciado pede uma linha por cenário, mas algumas linhas da matriz juntavam entradas inválidas diferentes. A abertura também apontava o mapa de testes para a “página final”, embora ele estivesse na penúltima. | A matriz passou a separar cada entrada, resultado esperado e observado; a abertura indica as páginas 7 e 8. As rejeições de data inválida em F03 e código inexistente em F07 ganharam cobertura própria. | Cenários C03a–i, C06a–c, C08a–d, C09a–b, C12a–c, C17a–d e C22a–d/C23a–b foram cruzados com T03, T05–T07, T09, T13, T16 e T18. |
| Professora exigente, prova do estado | O teste de renomeação ainda usava uma disciplina sem falta nem atividade; assim, a preservação prometida era quase trivial. | T17 passou a preparar uma ausência e uma prova antes de renomear. | Nome, registros, resumo e atividade foram comparados antes e após reabrir o SQLite. |
| Professora exigente, sexta leitura | F06 prometia ordenar a agenda por data e, em empate, por inserção, mas T14 cadastrava somente uma prova. O tipo permitido `trabalho` também não tinha sucesso explícito no menu. | T14 agora cadastra trabalho e prova fora de ordem, inclui dois itens em 03/11 e confere a sequência antes e depois de reabrir. C16b e C20a–b registram entradas e resultados. | As três linhas saíram em 03/11 prova, 03/11 trabalho, 05/11 trabalho nas duas execuções. |
| Jordan e Casey, nova passagem | O resumo do terminal mostrava “Pendentes”, “Limite” e “Restantes” sem unidade; o menu inteiro ficava em uma linha comprida. | O resumo explicita aulas e flexiona o singular; o menu foi dividido em duas linhas com ações completas. | T11 confere o texto com valores de 0, 1, 2 e 4 aulas; o fluxo inicial foi percorrido desde banco vazio. |
| Riley e professora, sétima leitura | Consultar com código vazio ou não textual e cadastrar com grade não iterável ainda produzia exceções técnicas diferentes das rejeições descritas. | O domínio agora responde com `ValueError` e mensagens de entrada válida, sem alterar o cadastro. Os contratos e cenários C03j, C14b e C14c foram atualizados. | T03 e T10 exercitam essas entradas e comparam o estado anterior; o ZIP extraído repetiu os 24 testes e o fluxo completo. |

## Conferência pelos dois enunciados

| Critério | Onde está demonstrado | Resultado da revisão |
| --- | --- | --- |
| Problema, público, escopo e ajuste do projeto | Produto, pp. 1–2 | Explicita que o controle pessoal é o núcleo e que Moodle, SIGA, autenticação e GPS pertencem à aplicação ampliada. |
| Lista e resultado de todas as funções entregues | Produto, p. 1; contratos nas pp. 3–4 | F01–F07 têm resultado verificável e correspondência com o menu. |
| Condição inicial, entrada, unidade, sucesso, rejeição e estado preservado | Produto, pp. 3–5 | Cada contrato tem as três partes; unidades e cálculo são definidos com exemplos. |
| Pelo menos três classes, abstração, herança, polimorfismo e alteração controlada | Produto, p. 6; `demo/models.py` | `Disciplina`, `Registro`, `Atividade` e `ControleAcademico` têm responsabilidades distintas; `PoliticaChamada` é abstrata e tem duas especializações; `nome` possui getter/setter. |
| Diagramas fiéis ao código | Produto, pp. 6–8 | Diagrama de classes e sequências F01, F02/F03 e F05 mostram validação, persistência e retorno. |
| Camadas e base persistente | Produto, p. 8; `demo/database.py` | Menu, domínio e SQLite separados; cadastro e grade usam transação. |
| Dados fictícios, instruções e dependências | Produto, p. 9; `demo/README.md`; `demo/dados_exemplo.py` | Banco vazio incluído e script cria exemplo separado; Python 3.11+, sem dependência externa no programa. |
| Tabela de verificação por funcionalidade | Verificação, pp. 2–6 | F01–F07 têm estado inicial e tabelas com ID, entrada, esperado, observado, situação e evidência. |
| Testes independentes e dados separados | Verificação, pp. 1 e 8; `demo/test_*.py` | Cada teste constrói objetos ou SQLite temporário; base da demo fica intacta. |
| Evidências da última execução e defeitos | Verificação, pp. 7–8; `evidencias/unittest.txt` | IDs T01–T19 mapeados para métodos; 24 resultados exibidos; defeitos, reprodução, consequência e reteste descritos. |

## Leitura pelo primeiro usuário e pelas personas

Esta aplicação acadêmica usa terminal; a análise de Impeccable foi adaptada ao menu e ao PDF, em vez de fingir que existe uma interface gráfica.

| Lente | Percurso ou pergunta feita | Resultado final |
| --- | --- | --- |
| Pessoa que nunca viu o projeto | Encontrar a pasta correta, iniciar, criar uma disciplina vazia, registrar frequência, sair e voltar. | README informa a pasta `demo/`; o menu mostra os códigos disponíveis ao reabrir. |
| Jordan, iniciante confuso | Entender o que significa “duas chamadas”, “aulas de 50 min” e quando usar Registrar ou Corrigir. | O prompt explica uma ou duas chamadas; entrada incorreta em Corrigir orienta o caminho certo. |
| Riley, testador exigente | Repetir código e data, inserir data impossível, trocar um registro já resolvido e simular falha de escrita. | Rejeições preservam cadastro, grade, registro ou agenda; testes conferem memória e SQLite. |
| Casey, usuário distraído | Fechar após registrar e consultar novamente sem lembrar o código da disciplina. | O SQLite persiste os dados e o menu mostra código e nome; o exemplo usa banco separado. |
| Alex, usuário impaciente | Seguir um exemplo curto sem montar várias configurações. | O roteiro da página 9 e os dados fictícios permitem demonstrar o fluxo principal diretamente. |
| Leitora rigorosa com formatação | Percorrer páginas sem ler o conteúdo e procurar texto encostado, cabeçalhos isolados, células cortadas e diagramas ilegíveis. | Conferência visual de todas as páginas renderizadas: hierarquia e espaçamento consistentes; nenhuma dessas falhas remanesceu. |

## Última rodada, depois das correções

As lentes foram aplicadas novamente ao ZIP reconstruído, não à versão anterior. A professora exigente conferiu os dois enunciados, os contratos, os cenários e o estado efetivamente observado; a nova passagem identificou entradas de domínio que ainda escapavam com erro técnico. Jordan refez o início desde o README e conferiu as unidades do resumo; Riley repetiu rejeições, valores não textuais e falhas de escrita; Casey fechou e reabriu o programa para conferir dados e ordem da agenda; Alex percorreu o caminho mais curto com dados fictícios; a leitora de formatação examinou as 17 páginas renderizadas. A lente de acessibilidade ficou fora desta rodada, conforme o recorte pedido. Depois de corrigir e repetir essas verificações, **não restou comentário acionável nessas lentes dentro do escopo aprovado**. O verificador do ZIP extraiu o pacote, executou os 24 testes e confirmou persistência desde um banco vazio. Esta conclusão é da revisão interna e não prevê a nota da docente.

## Limites que permanecem explícitos

- A grade admite uma data por encontro e duração fixa por disciplina; não há inclusão posterior de reposição.
- Uma atividade é cadastrada e consultada, sem edição ou lembrete automático.
- O executável acadêmico não sincroniza com a universidade e não capta localização. O aplicativo ampliado é apresentado como contexto, sem atribuir essas funções à demo.
- A aceitação do recorte pela professora e a nota final dependem da avaliação dela; a revisão interna confirma os critérios verificáveis do material entregue, não promete uma nota.
