# Guia de apresentação — Frequência UFMG acadêmico

Este guia é para ensaio. O material a entregar continua sendo os dois PDFs e o ZIP.

## Demonstração curta

1. Extraia o ZIP, abra o terminal em `demo/` e rode `python web.py`. O navegador abre; se não abrir, acesse `http://127.0.0.1:8878`.
2. Na tela vazia, clique **Usar dados de exemplo**. Mostre a matéria, a ausência de 04/11, as faltas e a prova na Agenda. Esses dados são fictícios e ficam no SQLite local.
3. Corrija a ausência para presença; mostre a atualização do saldo. Atualize a página para provar que a alteração persistiu.
4. Em **Ajustes**, clique **Executar testes**. O conjunto usa bancos temporários e deixa a demonstração intacta. O mesmo conjunto roda no terminal com `python -m unittest discover -v`.
5. Se precisar repetir do zero, use **Apagar dados da demo** e confirme com `APAGAR`. Para mostrar o cadastro manual, crie uma disciplina a partir da tela vazia.

## Código que vale abrir

| Prioridade | Arquivo e trecho | O que explicar |
| --- | --- | --- |
| 1 | `demo/models.py`: `PoliticaChamada`, `ChamadaUnica`, `ChamadaDupla` | A classe abstrata define a operação comum; duas especializações calculam faltas de modo diferente. `Disciplina` chama a mesma operação sem saber qual subclasse recebeu. |
| 2 | `demo/models.py`: `Disciplina`, `registrar_presenca`, `resumo` | A grade e os registros são protegidos; validação precede escrita. Correção substitui o registro. A unidade é a aula de 50 minutos, e o limite é o piso de 25% da base elegível. |
| 3 | `demo/models.py`: `ControleAcademico` | Coordena cadastro, atividades, consultas e persistência. A fachada `_DisciplinaPersistente` impede uma alteração apenas em memória quando o SQLite está ativo. |
| 4 | `demo/database.py`: `conexao`, `salvar_disciplina`, `salvar_exemplo` | SQLite separado das regras. O contexto confirma ou desfaz a transação. Cadastro e amostra não ficam pela metade se a escrita falhar. |
| 5 | `demo/main.py`: `escolher_disciplina`, `executar` | Apresentação alternativa no terminal. Recebe entradas e chama `ControleAcademico`; não calcula faltas. |
| 6 | `demo/web.py`: `executar_acao` | Ponte do HTML para as mesmas operações Python. Vale mostrar se perguntarem como o navegador conversa com o domínio. |

`web/index.html`, `app.css` e `app.js` são a apresentação visual. `test_models.py`, `test_main.py` e `test_web.py` são as provas automatizadas. Não é necessário explicar cada regra de CSS ou cada manipulação de botão para defender a parte de POO.

## Perguntas que a professora pode fazer

**Onde está o encapsulamento?** Em `Disciplina`, `_registros`, `_codigo` e `_politica` não são alterados pelo menu nem pela página. O getter `registros` devolve uma tupla de `Registro` imutáveis; `nome` tem setter que valida. Presença e data exigem métodos próprios porque mudam mais de um aspecto do estado.

**Onde estão abstração, herança e polimorfismo?** `PoliticaChamada` é abstrata e exige `calcular_faltas`. `ChamadaUnica` e `ChamadaDupla` a especializam. `Disciplina.registrar_presenca` usa a interface comum; para o mesmo atraso, uma chamada pode produzir zero falta e duas chamadas metade do encontro.

**Por que não calcular faltas no JavaScript ou no SQL?** Há duas apresentações, navegador e terminal. Centralizar a regra em `Disciplina` faz ambas exibirem o mesmo resultado; SQL guarda registros e o resumo é recalculado a partir deles.

**Por que a fachada persistente não é uma subclasse de `Disciplina`?** Ela adiciona o compromisso de gravar antes de publicar alterações, sem trocar a identidade ou a política da disciplina. A herança do domínio está nas políticas de chamada, onde as subclasses realmente representam regras especializadas.

**O que acontece se uma entrada ou gravação falhar?** O domínio valida antes de substituir o registro. Para operações que tocam mais de uma linha, SQLite usa transação; uma falha desfaz tudo. Os testes com erros simulados reabrem o banco e conferem que o estado anterior permaneceu.

**Como são calculados limite e frequência?** Cada registro tem 1, 2 ou 4 aulas de 50 minutos. Canceladas saem da base; sem chamada permanece com zero faltas. O limite é `total // 4`. Pendências permanecem na base, mas o percentual só aparece quando todas as aulas elegíveis foram resolvidas. Uma correção substitui a situação e o resumo é recalculado.

**O que a demo não faz?** Não acessa Moodle, SIGA ou GPS. O estudante informa a grade, e a aplicação local mantém frequência e atividades em SQLite. O relatório registra esse recorte e identifica a aplicação maior como trabalho ampliado.
