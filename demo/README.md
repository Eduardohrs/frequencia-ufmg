# Frequência UFMG — protótipo funcional

Python 3.11 ou superior. Sem instalação de bibliotecas, contas ou internet.
Extraia este ZIP em uma pasta e abra o terminal nela.

```text
python main.py
python -m unittest discover -v
```

O programa começa vazio. Use **1 Criar disciplina** para informar código,
nome, chamadas, aulas por encontro e datas da grade. Depois use **2 Registrar
presença** para escolher uma data e uma situação. **3 Consultar** mostra a
grade e o saldo de faltas; **4 Corrigir registro** substitui um registro existente.
Os dados ficam apenas na memória e se perdem ao sair.

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

`models.py` contém as regras, `main.py` o menu e `test_*.py` os testes.
Esta pasta é uma versão independente para avaliação de POO.
O aplicativo completo está em https://github.com/Eduardohrs/frequencia-ufmg.
