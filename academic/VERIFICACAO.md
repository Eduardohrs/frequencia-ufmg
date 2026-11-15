# Frequência UFMG — Verificação do Produto Final

**Versão testada:** produto-final-local-sqlite  
**Integrante:** Eduardo Henrique Rodrigues Silva

| ID | Cenário | Resultado esperado | Resultado observado | Status |
|---|---|---|---|---|
| V01 | Abrir a demo sem banco | Programa inicia e cria SQLite vazio | Menu iniciou e banco foi criado | PASS |
| V02 | Criar disciplina válida | Disciplina e datas pendentes são persistidas | Disciplina apareceu no resumo | PASS |
| V03 | Fechar e reabrir | Disciplina e registros continuam disponíveis | Teste SQLite recuperou o registro presente | PASS |
| V04 | Código duplicado | Rejeitar sem alterar o primeiro cadastro | Exceção e estado preservado | PASS |
| V05 | Data fora da grade | Rejeitar sem alterar totais | Exceção e resumo inalterado | PASS |
| V06 | Situação inválida | Rejeitar sem alterar o registro | Exceção e estado preservado | PASS |
| V07 | Registrar ausência | Somar as aulas do encontro | Faltas e limite recalculados | PASS |
| V08 | Repetir registro sem correção | Rejeitar duplicação | Exceção orienta usar correção | PASS |
| V09 | Corrigir presença | Substituir a situação e recalcular | Faltas diminuíram sem duplicação | PASS |
| V10 | Aula cancelada | Remover da base elegível | Limite e percentual recalculados | PASS |
| V11 | Aula sem chamada | Manter aula e acrescentar zero faltas | Resumo manteve a aula sem falta | PASS |
| V12 | Entrada textual não numérica | Rejeitar conversão | Menu exibiu operação rejeitada | PASS |

## Evidência automatizada

Comandos executados dentro de `demo/`:

```text
python -m unittest discover -v
```

Resultado: 11 testes aprovados, incluindo persistência entre duas aberturas do sistema, validações, cálculo, correção e fluxo do menu.

## Independência dos testes

Os testes de menu usam arquivo SQLite temporário. Os testes de domínio começam com cadastro vazio e não dependem de dados reais, rede, conta ou serviço externo.

## Limitações registradas

Não são testados nesta versão login, sincronização acadêmica, GPS, Moodle, SIGA ou aplicativo Android. Essas partes pertencem ao produto real e são apresentadas como extensão do mesmo núcleo de frequência.
