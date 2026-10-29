# Frequência UFMG — protótipo funcional de POO

Esta pasta é uma versão didática, independente e simplificada do
[Frequência UFMG](https://github.com/Eduardohrs/frequencia-ufmg).
O repositório completo contém o aplicativo e suas integrações. Aqui o objetivo é
mostrar, em poucos arquivos, os conceitos de programação orientada a objetos
aplicados ao controle pessoal de frequência. Não é necessário instalar o restante
do repositório para executar esta versão.

## Executar e testar

Python **3.11 ou superior**. Validado localmente com Python 3.11.
Nenhuma biblioteca externa, conta, conexão com a internet ou preparação de banco é necessária.
Dentro desta pasta:

```sh
python main.py
python -m unittest discover -s . -p "test_*.py" -v
```

Se o comando do sistema for `python3`, substitua `python` por `python3`.
Os dados são preparados por `preparar_dados()` em cada execução: duas disciplinas
fictícias, DEMO01 (uma chamada) e DEMO02 (duas chamadas), cada uma com quatro sessões.
**Tudo fica em memória. Sair e abrir novamente descarta as alterações.**
Os códigos, nomes, datas e evidências são dados sintéticos; não há registros reais
nem acesso ao banco do aplicativo. A localização é uma estimativa para controle
pessoal; estar no campus não comprova participação na aula.

## Duas funcionalidades do incremento

| Funcionalidade | Entrada e condições | Resultado | Rejeição e estado preservado |
|---|---|---|---|
| F01 — Registrar evidência e consolidar frequência | Sessão normal existente, momento início+20 min ou término−20 min e evidência no campus/fora/indisponível. Sem correção manual anterior. | Mantém o ping e calcula um único registro atual segundo a política da sessão. | Momento duplicado, sessão inexistente ou valor inválido: mantém todos os pings e o registro anterior. |
| F02 — Corrigir a frequência de uma sessão | Sessão normal existente, situação válida e faltas inteiras de 0 até o número de aulas; pendente exige faltas indefinidas. | Substitui o registro atual, preserva os pings e recalcula o resumo na consulta. | Faltas negativas, fracionárias ou acima do tamanho da sessão: mantém o registro anterior. |

O estudante solicita as operações pelo menu. Consultar sessões e resumo permite
observar os efeitos das duas funcionalidades, sem alterar o domínio.
A coleta de GPS e o disparo do relógio são **simulados** por entradas no terminal;
a classificação, validação, alteração de estado e os cálculos são executados de verdade.
O programa não afirma ter verificado localização real nem controla a hora da entrada.

## Regras e exemplos

- Uma aula é uma unidade de **50 minutos**. Uma sessão reúne 1,2 ou 4 unidades.
  Duas chamadas só são aceitas em sessões de 2 ou 4 unidades.
- Uma chamada: qualquer evidência positiva basta para zero faltas. Com dois pings
  disponíveis, positivo/negativo indica saída antecipada e negativo/positivo,
  atraso; ambos continuam com zero faltas. Dois negativos geram ausência integral.
- Duas chamadas: dois positivos geram presente/0; um negativo gera atraso ou saída
  antecipada e metade das unidades em faltas; dois negativos geram ausência integral.
- Evidência indisponível ou um momento ainda não recebido deixa pendente, salvo
  confirmação positiva suficiente na chamada única. Pendente nunca vira falta automática.
- Correções manuais podem substituir situação e número de faltas independentemente
  do padrão automático, para acomodar exceções. Não há motivo nem histórico; pings
  originais são preservados. Novos pings não sobrescrevem correção manual.
- Cancelada/feriado sai da base e não recebe frequência. Sem chamada entra na base
  com zero faltas. Essas naturezas vêm nos dados de apoio; editar natureza, criar
  reposições e gerar grade não são funcionalidades deste incremento. Uma reposição,
  numa evolução, deverá entrar como outra sessão elegível, sem duplicar a cancelada.

A base `E` é a soma de unidades das sessões elegíveis, não uma carga digitada:

- `limite = E // 4` (piso de 25%).
- `faltas = soma das faltas dos registros resolvidos`.
- `restantes = max(0, limite - faltas)`; excesso gera aviso, nunca saldo negativo.
- `presentes = E - unidades pendentes - faltas`.
- Percentual final `100 × (E - faltas) / E` somente quando `E > 0` e não há pendências.
  Enquanto houver, a tela mostra os segmentos e “frequência final: pendente”.

Cada disciplina fictícia tem 8 unidades elegíveis:4 deS1,2 deS2 e 2 deS3 sem chamada.
S4 é cancelada e não entra. O limite é 2. Com 2 faltas resolvidas e nenhuma pendência,
a frequência é 75% e restam 0 faltas. Com 4 faltas, o limite é excedido.
Para uma base 61, o limite seria 15, não 16. Esses são cálculos do controle pessoal,
não uma confirmação de critérios oficiais ou de uma disciplina real.

## Onde estão os conceitos de POO

| Conceito | Implementação |
|---|---|
| Classe abstrata e contrato | `PoliticaFrequencia.classificar` usa `ABC` e `@abstractmethod`. |
| Herança por especialização | `ChamadaUnica` e `ChamadaDupla` são políticas de frequência. |
| Polimorfismo | `SessaoAula.registrar_ping` chama a mesma operação `classificar` de qualquer política. Com 4 aulas e positivo/negativo, as concretas retornam 0 e 2 faltas. |
| Composição e responsabilidades | Disciplina reúne sessões; sessão mantém evidências e resultado e delega classificação à política. |
| Encapsulamento | Estado interno, propriedades de leitura, tuplas para coleções e registro imutável. Mudanças passam por operações com validação. |
| Exceções e atomicidade | `ValueError` no domínio; menu apresenta o erro. Classificação ocorre antes de efetivar os pings. Rejeições não deixam alterações parciais. |
| Separação de apresentação | `models.py` devolve dados; `main.py` decide como exibir e solicitar entradas. |

`models.py` contém as classes avaliáveis; `main.py`, a interação;
`test_models.py` e `test_main.py`, os cenários automatizados.
O primeiro ping permanece no mesmo objeto de sessão entre duas ações do menu.
O controlador e o repositório separados desenhados na entrega 2 foram simplificados:
a coordenação está no menu e os objetos vivem em memória. Não se simula uma gravação
externa inexistente. A divisão por responsabilidades foi preservada.

## Roteiro de demonstração

1. Consulte DEMO02: S1 está pendente, S3 é sem chamada e S4 está cancelada.
2. Registre emS1 o primeiro ping “fora” e o segundo “no campus”.
   Resultado: atrasado,2 faltas; primeiro ping sozinho ficou pendente.
3. Tente registrar novamente o mesmo momento: rejeição, resultado anterior intacto.
4. Corrija S1 para presente,0 faltas. Consulte: faltas usadas voltam a 0; os pings permanecem.
5. Para mostrar polimorfismo, faça positivo/negativo emS1 deDEMO01 e deDEMO02
   numa execução nova: saída antecipada com 0 e 2 faltas, respectivamente.
6. Teste uma entrada não numérica ou uma correção de 99 faltas: erro compreensível,
   sem encerrar o menu nem alterar o registro. Execute os testes automatizados.

Os testes incluem sucesso, rejeição com preservação de estado, limite, pendência,
correções sucessivas, consultas sem mutação e as entradas da interface.
A cobertura de linhas do domínio e menu é exigida em 100% no CI do repositório;
a professora pode executar todos os testes apenas com `unittest`, sem instalar ferramentas.

## Limites, persistência e entrega

Este protótipo não possui autenticação, GPS real, agendamento em segundo plano,
Moodle/SIGA, notificações, sincronização, interface gráfica ou persistência.
O produto completo pode ser apresentado como evolução separada; sua disponibilidade
não é necessária para avaliar este código. O demonstrador não é chamado pelo aplicativo.

Numa evolução independente, será preciso salvar disciplinas, sessões, evidências e
registro atual e recuperá-los ao reabrir. Uma alternativa local a investigar é SQLite,
com o módulo `sqlite3`: [documentação técnica oficial](https://docs.python.org/3/library/sqlite3.html).
Experimento futuro: salvar os dois pings e a correção numa transação, fechar, reabrir
e conferir a preservação das invariantes. Isso não representa migração do banco do produto real.

Para a entrega acadêmica, envie **esta pasta** num ZIP limpo, com estes cinco arquivos,
e o PDF exigido pela atividade. Não envie o repositório inteiro, ambientes virtuais,
`__pycache__`, arquivos de cobertura ou credenciais. Extraia em outra pasta e execute
os dois comandos acima antes de enviar. O PDF com diagramas, contratos, capturas de
execução e evidências deverá acompanhar o ZIP; este README não o substitui.
