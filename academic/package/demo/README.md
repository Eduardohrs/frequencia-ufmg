# Frequência UFMG — produto acadêmico PF-02-AGENDA

Python 3.11 ou superior. Usa somente a biblioteca padrão, incluindo SQLite. Não exige contas ou internet.
Extraia o ZIP e abra o terminal **dentro da pasta `demo/`**. Os comandos abaixo
são executados a partir dessa pasta, não da raiz do ZIP.

```text
python main.py
python -m unittest discover -v
```

Na primeira execução o programa começa vazio. Use **1 Criar disciplina** para informar código,
nome, chamadas, aulas por encontro e datas da grade. Depois use **2 Registrar
presença** para escolher uma data e uma situação. **3 Consultar** mostra a
grade e o saldo de faltas; **4 Corrigir registro** substitui um registro existente.
Ao reabrir, o menu mostra o código e o nome das disciplinas cadastradas; não é
preciso memorizar o código. Use **Corrigir** apenas quando a aula já tiver uma
situação registrada; para uma aula pendente, use **Registrar presença**.
Use **5 Adicionar atividade** para registrar uma prova ou trabalho vinculado a uma
disciplina; **6 Ver agenda** lista as atividades por data. A agenda não altera faltas.
Use **7 Renomear disciplina** para corrigir um nome sem alterar código, aulas ou presenças.
Os dados são salvos no arquivo `frequencia.db` na pasta da demo e continuam disponíveis ao fechar e reabrir o programa. Para começar novamente, remova esse arquivo.

## Base fictícia isolada

Para obter dados de exemplo sem modificar `frequencia.db`, execute `python dados_exemplo.py`.
Isso cria `exemplo.db` com uma disciplina, uma ausência e uma prova fictícia.
Depois execute o menu apontando para essa base:

```powershell
$env:FREQUENCIA_DB_PATH='exemplo.db'; py main.py
```

No Prompt de Comando: `set FREQUENCIA_DB_PATH=exemplo.db` e depois `python main.py`.
Em macOS/Linux: `FREQUENCIA_DB_PATH=exemplo.db python main.py`.

## Exemplo a partir do zero

- Crie `DEMO01`, nome `Disciplina de teste`, duas chamadas e duas aulas por encontro.
- Informe as datas `02/11/2026,04/11/2026,09/11/2026,11/11/2026`.
- Registre `presente` em `02/11/2026`: zero faltas, seis aulas pendentes.
- Registre `ausente` em `04/11/2026`: duas faltas usadas, limite de duas e saldo zero.
- Tente cadastrar `demo01` novamente: o cadastro deve ser rejeitado, sem apagar o primeiro.

Cada aula vale 50 minutos. Cancelamentos saem da base; aula sem chamada entra
com zero faltas. O limite é 25% da grade, arredondado para baixo. O percentual
só aparece quando não há pendências. Uma chamada não desconta atraso/saída
antecipada; duas descontam metade do encontro. Uma aula não admite duas chamadas.

`models.py` contém as regras, `database.py` a persistência SQLite, `main.py` o menu,
`dados_exemplo.py` os dados fictícios e `test_*.py` os testes independentes.
Esta pasta é uma versão independente para avaliação de POO.
O aplicativo completo está em https://github.com/Eduardohrs/frequencia-ufmg.
