# Regras de frequência

Este documento é o contrato funcional da classificação de frequência. Python,
Dart, persistência e interface devem produzir os mesmos resultados a partir destas
regras.

## Conceitos

- Uma **aula** dura 50 minutos e corresponde a uma unidade inteira de falta.
- Uma **sessão** é um bloco contínuo de 1, 2 ou 4 aulas.
- Cada sessão possui dois momentos de verificação:
  - `P1`: 20 minutos após o início da sessão;
  - `P2`: 20 minutos antes do término da sessão.
- Um ping válido informa apenas se o estudante estava dentro ou fora de algum
  campus configurado. Sala e prédio não participam da decisão.
- Estar no campus no momento do ping conta como presença, mesmo que o estudante
  apenas tenha passado pelo campus.
- Falha técnica, permissão negada ou localização sem qualidade suficiente não
  equivalem a estar fora do campus e seguem as regras de dados indisponíveis.

## Classificação pelos dois pings

| P1 | P2 | Classificação |
|---|---|---|
| No campus | No campus | Presente |
| Fora do campus | No campus | Chegou atrasado |
| No campus | Fora do campus | Saiu mais cedo |
| Fora do campus | Fora do campus | Ausente |

### Dados indisponíveis

| Chamadas | Evidência disponível | Resultado |
|---:|---|---|
| 1 | Pelo menos um ping no campus | Presente, 0 faltas |
| 1 | Nenhum ping no campus e pelo menos um indisponível | Pendente |
| 2 | Pelo menos um ping indisponível | Pendente |

Com uma chamada, uma confirmação no campus basta mesmo se o outro ping falhar. Com
duas chamadas, cada ping representa uma parte diferente do bloco e ambos são
necessários. `Pendente` não consome faltas automaticamente e exige nova coleta
válida ou correção manual.

## Conversão da classificação em faltas

### Uma chamada por sessão

Com uma chamada, basta presença em pelo menos um dos dois momentos para validar o
bloco inteiro. As classificações `Chegou atrasado` e `Saiu mais cedo` continuam
visíveis para controle pessoal, mas não consomem falta.

| Aulas na sessão | Presente | Chegou atrasado | Saiu mais cedo | Ausente |
|---:|---:|---:|---:|---:|
| 1 | 0 | 0 | 0 | 1 |
| 2 | 0 | 0 | 0 | 2 |
| 4 | 0 | 0 | 0 | 4 |

### Duas chamadas por sessão

Com duas chamadas, `P1` representa a primeira metade da sessão e `P2`, a segunda.
Cada metade contém uma quantidade inteira de aulas. Por isso, duas chamadas são
uma configuração válida somente para sessões de 2 ou 4 aulas.

| Aulas na sessão | Presente | Chegou atrasado | Saiu mais cedo | Ausente |
|---:|---:|---:|---:|---:|
| 1 | configuração inválida | configuração inválida | configuração inválida | configuração inválida |
| 2 | 0 | 1 | 1 | 2 |
| 4 | 0 | 2 | 2 | 4 |

Essa restrição evita meia falta: a unidade acadêmica e de exibição permanece uma
aula inteira de 50 minutos.

## Matriz completa de decisão

| Aulas | Chamadas | P1 | P2 | Estado | Faltas |
|---:|---:|---|---|---|---:|
| 1 | 1 | No campus | No campus | Presente | 0 |
| 1 | 1 | Fora | No campus | Chegou atrasado | 0 |
| 1 | 1 | No campus | Fora | Saiu mais cedo | 0 |
| 1 | 1 | Fora | Fora | Ausente | 1 |
| 1 | 2 | qualquer | qualquer | Configuração inválida | — |
| 2 | 1 | No campus | No campus | Presente | 0 |
| 2 | 1 | Fora | No campus | Chegou atrasado | 0 |
| 2 | 1 | No campus | Fora | Saiu mais cedo | 0 |
| 2 | 1 | Fora | Fora | Ausente | 2 |
| 2 | 2 | No campus | No campus | Presente | 0 |
| 2 | 2 | Fora | No campus | Chegou atrasado | 1 |
| 2 | 2 | No campus | Fora | Saiu mais cedo | 1 |
| 2 | 2 | Fora | Fora | Ausente | 2 |
| 4 | 1 | No campus | No campus | Presente | 0 |
| 4 | 1 | Fora | No campus | Chegou atrasado | 0 |
| 4 | 1 | No campus | Fora | Saiu mais cedo | 0 |
| 4 | 1 | Fora | Fora | Ausente | 4 |
| 4 | 2 | No campus | No campus | Presente | 0 |
| 4 | 2 | Fora | No campus | Chegou atrasado | 2 |
| 4 | 2 | No campus | Fora | Saiu mais cedo | 2 |
| 4 | 2 | Fora | Fora | Ausente | 4 |

As combinações com ping indisponível seguem a tabela de dados indisponíveis, pois
uma confirmação no campus já resolve uma sessão de chamada única.

## Correção manual

O estudante pode substituir o estado e a quantidade de faltas de qualquer sessão.
A correção não exige justificativa e não mantém histórico institucional, pois o
sistema é de controle pessoal. O valor corrigido prevalece nos totais e relatórios.

## Invariantes para implementação

- Quantidades de aulas e faltas são números inteiros não negativos.
- Uma sessão nunca consome mais faltas do que sua quantidade de aulas.
- Uma sessão pendente nunca altera o total de faltas.
- O resultado automático depende somente da configuração da sessão e dos dois
  pings válidos; coordenadas exatas não pertencem ao domínio de frequência.
- Reprocessar os mesmos dados produz o mesmo resultado.
- Python e Dart devem validar esta matriz com os mesmos casos compartilhados.

## Fora do escopo desta decisão

As regras de carga horária total, limite percentual, arredondamento das faltas
permitidas, tolerância de execução dos pings e qualidade mínima da localização serão
formalizadas nas etapas próprias. Elas não alteram a matriz acima.
