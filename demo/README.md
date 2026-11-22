# Frequência UFMG — produto acadêmico PF-02-AGENDA

Python 3.11 ou superior. Usa somente a biblioteca padrão, incluindo SQLite. Não exige contas ou internet.
Extraia o ZIP e abra o terminal **dentro da pasta `demo/`**. Os comandos abaixo
são executados a partir dessa pasta, não da raiz do ZIP.

```text
python web.py
python -m unittest discover -v
```

Abra **http://127.0.0.1:8878** no navegador. O servidor aceita conexões apenas
do próprio computador. Use **Nova disciplina** para informar nome, código,
chamadas, aulas por encontro e adicionar cada data da grade. A matéria aparece
imediatamente na lista pelo nome. Abra uma data e escolha a situação de
frequência; a mesma linha oferece **Corrigir** depois de um registro. O cartão
mostra faltas usadas, limite, saldo e frequência quando todas as aulas tiverem
sido resolvidas. **Agenda** guarda provas e trabalhos vinculados à matéria.
Use **Corrigir data** no encontro se a data da grade estiver errada: a presença,
as faltas e os totais ficam preservados, inclusive após reabrir o navegador.
Essa correção existe na interface visual; o menu de terminal conserva o fluxo
principal de cadastro e frequência.
**Renomear** altera só o nome. Em **Ajustes**, **Apagar dados da demo** requer
digitar `APAGAR`; cancelar preserva tudo.
Se o banco local estiver temporariamente indisponível ao abrir a página, a tela
mostra o erro e **Tentar novamente**; ela não finge que o cadastro está vazio.

O navegador só mostra os dados e envia as ações. `web.py` transforma essas ações
em chamadas às classes de `models.py`, onde ficam validações e cálculos. `database.py`
salva no arquivo `frequencia.db`, que permanece ao fechar e reabrir. Para encerrar
o servidor, volte ao terminal e pressione Ctrl+C.

Também é possível usar a mesma demo pelo terminal com `python main.py`. Nesse
menu, as matérias aparecem por nome e número; o código é só referência. A opção
8 reinicia os dados após `APAGAR`. Terminal e navegador compartilham o mesmo
banco local quando executados na mesma pasta.

## Base fictícia isolada

Para obter dados de exemplo sem modificar `frequencia.db`, execute `python dados_exemplo.py`.
Isso cria `exemplo.db` com uma disciplina, uma ausência e uma prova fictícia.
Depois execute a interface apontando para essa base:

```powershell
$env:FREQUENCIA_DB_PATH='exemplo.db'; py web.py
```

No Prompt de Comando: `set FREQUENCIA_DB_PATH=exemplo.db` e depois `python web.py`.
Em macOS/Linux: `FREQUENCIA_DB_PATH=exemplo.db python web.py`.

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

`models.py` contém as regras, `database.py` a persistência SQLite, `web.py` a
ponte HTTP local, `web/` a interface visual, `main.py` o menu alternativo,
`dados_exemplo.py` os dados fictícios e `test_*.py` os testes independentes.
Esta pasta é uma versão independente para avaliação de POO.
O aplicativo completo está em https://github.com/Eduardohrs/frequencia-ufmg.
