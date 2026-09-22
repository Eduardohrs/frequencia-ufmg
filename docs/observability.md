# Observabilidade

## Perguntas operacionais

1. O aplicativo iniciou e conseguiu autenticar ou sair?
2. Em qual etapa uma operação falhou e qual foi o código sanitizado do provedor?
3. Qual requisição do backend falhou, quanto demorou e qual identificador o usuário
   pode informar?

## Sinais

- Firebase Analytics registra eventos de negócio e seus resultados.
- Firebase Crashlytics registra falhas Android, pilhas e eventos anteriores.
- O backend escreve JSON em `stdout`, compatível com o agregador de logs do ambiente
  onde for hospedado.

Operações do cliente usam `operation_id`; requisições HTTP usam `x-request-id`. Esses
identificadores permitem reconstruir uma execução sem registrar corpo, query string,
token, senha, cookie ou e-mail. Eventos usam os estados `started`, `succeeded` e
`failed`.

## Regra para novas funcionalidades

Toda nova ação relevante deve entrar em `AuditedOperation` e possuir teste dos fluxos
de sucesso e falha. Integrações externas devem registrar duração, resultado e código
de erro sanitizado. Alertas só serão adicionados quando houver serviço em produção e
um limiar baseado em comportamento real; até lá, criar alertas seria ruído sem ação.
