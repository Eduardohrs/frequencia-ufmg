# Revisão da entrega acadêmica PF-02-AGENDA

Revisão interna do pacote `Frequencia_UFMG_Entrega_Final.zip`. Este registro **não substitui a avaliação da professora**. Foi feito sobre os PDFs renderizados, o código e o ZIP extraído, comparados aos enunciados de Produto final e Verificação. A lente acadêmica usa a skill pública `peer-review` em modo *homework*; a lente de primeiro uso usa a skill `impeccable`, adaptada ao terminal e ao material escrito.

## Rodadas de revisão e correção

| Rodada | Achado concreto | Correção | Rechecagem |
| --- | --- | --- | --- |
| Formatação | A versão anterior tinha blocos de texto desalinhados e diagramas pouco legíveis. | Os relatórios foram refeitos em A4 com tipografia, margens, cabeçalhos, rodapés, tabelas e diagramas vetoriais consistentes. | Todas as 9 páginas do Produto e 8 da Verificação foram renderizadas e examinadas visualmente; não há texto sobreposto, cortado ou página órfã. |
| Professora exigente | O protótipo anterior não bastava, por si só, para evidenciar produto completo, persistência e contratos verificáveis. | A entrega ganhou agenda de provas/trabalhos, consulta, correção e renomeação, SQLite, dados fictícios isolados, contratos F01–F07 e diagramas atualizados. | O ZIP extraído executa o menu desde banco vazio, grava presença/atividade/nome e recupera os três após reiniciar. |
| Professora exigente | Uma frase do cálculo usava “A soma as faltas”, deixando a variável A pouco clara. | A definição passou a ser “A é a soma das faltas de registros resolvidos.” | O texto extraído da página 5 do Produto foi relido após gerar o PDF final. |
| Professora exigente | Código e evidência anteriores à última revisão poderiam divergir do pacote enviado. | A evidência de unittest foi regenerada, os arquivos da demo e os PDFs foram copiados novamente para o pacote, e o ZIP foi reconstruído. | 23 testes aprovados; os quatro módulos do programa têm 100% de cobertura de linhas; `verify_package.py` repete testes e fluxo sobre o ZIP extraído. |
| Apresentação oral | Algumas operações do domínio ainda tinham comentários curtos demais para explicar entradas, unidades e momento da persistência. | Foram ampliados os docstrings de cadastro, registro, cálculo, agenda, consulta e renomeação, além das funções do menu. | Leitura do código em `demo/models.py`, `demo/database.py` e `demo/main.py`; testes e formatação continuaram passando. |

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
| Evidências da última execução e defeitos | Verificação, pp. 7–8; `evidencias/unittest.txt` | IDs T01–T19 mapeados para métodos; 23 resultados exibidos; defeitos, reprodução, consequência e reteste descritos. |

## Leitura pelo primeiro usuário e pelas personas

Esta aplicação acadêmica usa terminal; a análise de Impeccable foi adaptada ao menu e ao PDF, em vez de fingir que existe uma interface gráfica.

| Lente | Percurso ou pergunta feita | Resultado final |
| --- | --- | --- |
| Pessoa que nunca viu o projeto | Encontrar o comando de início, criar uma disciplina vazia, registrar frequência, sair e voltar. | README começa por requisitos e comandos; o programa explica valores aceitos e mostra o registro recuperado. |
| Jordan, iniciante confuso | Entender o que significa “duas chamadas”, “aulas de 50 min” e “pendente”. | Os termos aparecem nos prompts, na explicação do README e nas regras do Produto. |
| Riley, testador exigente | Repetir código e data, inserir data impossível, trocar um registro já resolvido e simular falha de escrita. | Rejeições preservam cadastro, grade, registro ou agenda; testes conferem memória e SQLite. |
| Casey, usuário distraído | Fechar após registrar e consultar novamente sem lembrar a sessão anterior. | O SQLite persiste os dados; há um script de exemplo separado para experimentar sem alterar a base principal. |
| Alex, usuário impaciente | Seguir um exemplo curto sem montar várias configurações. | O roteiro da página 9 e os dados fictícios permitem demonstrar o fluxo principal diretamente. |
| Leitora rigorosa com formatação | Percorrer páginas sem ler o conteúdo e procurar texto encostado, cabeçalhos isolados, células cortadas e diagramas ilegíveis. | Conferência visual de todas as páginas renderizadas: hierarquia e espaçamento consistentes; nenhuma dessas falhas remanesceu. |

## Limites que permanecem explícitos

- A grade admite uma data por encontro e duração fixa por disciplina; não há inclusão posterior de reposição.
- Uma atividade é cadastrada e consultada, sem edição ou lembrete automático.
- O executável acadêmico não sincroniza com a universidade e não capta localização. O aplicativo ampliado é apresentado como contexto, sem atribuir essas funções à demo.
- A aceitação do recorte pela professora e a nota final dependem da avaliação dela; a revisão interna confirma os critérios verificáveis do material entregue, não promete uma nota.
