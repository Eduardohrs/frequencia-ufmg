# Frequência UFMG — Produto Final

**Versão:** produto-final-local-sqlite  
**Integrante:** Eduardo Henrique Rodrigues Silva

## 1. Escopo

Este produto final é uma versão acadêmica reduzida do sistema Frequência UFMG. Ele demonstra, em Python no terminal, o núcleo do problema: cadastrar uma disciplina, registrar a situação de cada aula e acompanhar o saldo de faltas. O aplicativo completo, com autenticação, integrações acadêmicas, localização e interface web/Android, é uma extensão prática e não é necessário para executar esta demonstração.

## 2. Funcionalidades entregues

### F01 — Cadastrar disciplina e grade

Entrada: código, nome, uma ou duas chamadas, uma/duas/quatro aulas de 50 minutos por encontro e datas válidas.

Sucesso: a disciplina é criada a partir de um cadastro vazio e suas datas ficam pendentes.

Rejeições: campos vazios, tipos inválidos, chamadas incompatíveis com uma aula, datas repetidas ou código já cadastrado. A rejeição não altera o cadastro.

### F02 — Registrar e corrigir frequência

Entrada: uma data da grade e uma situação (`presente`, `ausente`, `atrasado`, `saiu mais cedo`, `cancelada` ou `sem chamada`).

Sucesso: o registro é salvo e o resumo é recalculado. Uma correção exige uma ação explícita e substitui o registro, sem somar faltas duplicadas.

## 3. Regras do domínio

- Cada aula equivale a 50 minutos.
- O limite de faltas é o piso de 25% das aulas elegíveis.
- Registro pendente não é contado como presença nem como falta.
- Aula cancelada deixa de compor a base elegível.
- Aula sem chamada permanece na grade, mas acrescenta zero faltas.
- Com uma chamada, atraso e saída antecipada não geram falta neste recorte.
- Com duas chamadas, atraso e saída antecipada geram metade das aulas do encontro, arredondada para baixo.
- O percentual só aparece quando não existem pendências.

## 4. Organização do código

- `demo/models.py`: entidades, regras, encapsulamento, classe abstrata e especializações de chamada.
- `demo/database.py`: persistência SQLite local, sem dependências externas.
- `demo/main.py`: interação de terminal e conversão de entradas.
- `demo/test_models.py` e `demo/test_main.py`: testes unitários e de fluxo.

O banco `demo/frequencia.db` é criado automaticamente. Removê-lo reinicia a demonstração.

## 5. Arquitetura e limitações

A apresentação chama o serviço de domínio; o domínio valida e calcula; a camada SQLite persiste. As integrações externas e a autenticação ficam fora do recorte e são simuladas pelo cadastro manual. A versão real do aplicativo usa outras fontes e interfaces, mas preserva estas regras centrais.

## 6. Execução

Requer Python 3.11 ou superior. Não requer instalação de pacotes nem internet:

```text
cd demo
python main.py
python -m unittest discover -v
```
