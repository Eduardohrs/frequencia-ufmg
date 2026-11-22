# Revisão da entrega PF-03-WEB

A revisão comparou os dois relatórios com os enunciados de Produto final e
Verificação, o código enviado e a última execução de unittest. Foram aplicadas
três lentes complementares: revisão acadêmica de afirmações e evidências,
teste de leitura sem contexto prévio e conferência técnica do PDF renderizado.

## Correções feitas nesta rodada

- O relatório distingue o aplicativo Android/web em desenvolvimento e uso da
  demo acadêmica independente. Explica por que a apresentação avalia o núcleo
  de POO em Python, enquanto autenticação, importação e localização exigem
  infraestrutura maior e não são fingidas como verificadas neste ZIP.
- O diagrama de classes explicita a referência de atividade à disciplina, a
  política escolhida e as multiplicidades; os diagramas de sequência agora
  cobrem cadastro, frequência, agenda e reinício, com rejeição e rollback
  descritos junto aos fluxos.
- A matriz de verificação separa entradas inválidas em subcasos e usa números
  observados compatíveis com os próprios testes. A última página resume a
  execução em fonte legível; o log integral segue no arquivo de evidência.
- O produto descreve apenas as oito funções presentes na interface web.
- Remarcação de encontro e menu de terminal saíram do código, dos testes, do
  README, das matrizes e das instruções de reprodução.
- A criação da amostra saiu de `ControleAcademico` e foi para `exemplo.py`.
- A fachada de disciplina persistente foi retirada; o controle liga funções
  de gravação às disciplinas para que cada referência salve antes de mudar.
- O PDF explica que uma correção atualiza a situação da mesma aula após o
  commit, sem guardar histórico nem acrescentar outra linha no banco.
- A verificação usa seis colunas por cenário, com estado inicial, resultado
  esperado, observado, situação e teste identificável no ZIP.

## Conferência final

O verificador extrai o ZIP, abre os dois PDFs e executa os testes nos arquivos
enviados. Cada PDF foi inspecionado em páginas renderizadas; não há página órfã
nem texto sobreposto. O arquivo de evidência registra a contagem da versão
atual. O recorte acadêmico conserva o núcleo de frequência e a agenda manual;
integração universitária e localização automática permanecem fora dele.
