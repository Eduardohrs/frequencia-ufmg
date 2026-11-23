"""Gera os relatórios acadêmicos a partir das regras e testes da demo."""

from pathlib import Path

from pdf_layout import (
    P,
    build,
    class_diagram,
    page,
    section,
    sequence_diagram,
    table,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Preformatted, Spacer


def cenarios(story, titulo, preparo, linhas):
    story.append(
        KeepTogether(
            [
                P(titulo, "H2X"),
                P(preparo),
                table(
                    [
                        "ID",
                        "Regra e entrada",
                        "Esperado",
                        "Observado",
                        "Situação",
                        "Evidência",
                    ],
                    linhas,
                    [1.5 * cm, 4.1 * cm, 5.7 * cm, 5.7 * cm, 1.8 * cm, 6.7 * cm],
                    dense="tight",
                ),
                Spacer(1, 0.12 * cm),
            ]
        )
    )


def produto():
    s = []
    page(s, "Produto final · APPOO 2026/2", "Frequência UFMG")
    s.append(
        P(
            "<b>Integrante:</b> Eduardo Henrique Rodrigues Silva<br/>"
            "<b>Disciplina:</b> APPOO · Prof.ª Luiza Bernardes Real"
        )
    )
    section(
        s,
        "Problema e público",
        "Ao longo do semestre, o estudante precisa saber quantas faltas já registrou em cada disciplina e quantas ainda cabem no limite de frequência. O sistema organiza os encontros da grade, permite registrar e corrigir a situação de cada aula e apresenta o saldo atualizado. Provas e trabalhos vinculados à disciplina aparecem na agenda para apoiar esse acompanhamento.",
    )
    section(
        s,
        "Escopo da entrega",
        "Esta aplicação reúne o núcleo de controle de frequência em Python: cadastro manual da grade, registro e correção, consulta dos cálculos e agenda de atividades. O recorte foi ajustado para apresentar as regras de POO numa aplicação executável em sala. A localização e as importações da proposta integram o aplicativo maior, disponível em https://github.com/Eduardohrs/frequencia-ufmg; na entrega, o estudante informa os dados pela página local. Em relação ao protótipo, o produto integra a agenda, a persistência SQLite e os fluxos de consulta e correção.",
    )
    section(s, "Funcionalidades")
    s.append(
        table(
            ["ID", "Ação do estudante", "Resultado"],
            [
                (
                    "F01",
                    "Cadastrar disciplina",
                    "Cria a grade com um encontro pendente em cada data.",
                ),
                (
                    "F02",
                    "Registrar frequência",
                    "Resolve uma aula e atualiza as faltas.",
                ),
                (
                    "F03",
                    "Corrigir frequência",
                    "Substitui a situação de uma aula já registrada e recalcula os totais.",
                ),
                (
                    "F04",
                    "Consultar frequência",
                    "Mostra grade, limite, faltas, saldo e percentual quando definido.",
                ),
                (
                    "F05",
                    "Adicionar atividade",
                    "Guarda prova ou trabalho ligado à disciplina.",
                ),
                (
                    "F06",
                    "Consultar agenda",
                    "Lista atividades por data e nome da disciplina.",
                ),
                (
                    "F07",
                    "Renomear disciplina",
                    "Atualiza o nome exibido sem mudar seu código.",
                ),
                (
                    "F08",
                    "Apagar dados da demo",
                    "Reinicia a base após confirmação na página.",
                ),
            ],
            [1.3 * cm, 5.1 * cm, 10.6 * cm],
            dense=True,
        )
    )
    section(s, "Contratos das funcionalidades")
    s.append(
        table(
            ["Funcionalidade", "Condição e entrada", "Sucesso", "Rejeição e estado"],
            [
                (
                    "<b>F01</b><br/>Cadastrar disciplina",
                    "Código e nome; 1 ou 2 chamadas; 1, 2 ou 4 aulas de 50 min por encontro; datas distintas. Duas chamadas exigem ao menos 2 aulas.",
                    "Código normalizado; disciplina e um registro pendente por data gravados juntos.",
                    "Código repetido, data ou combinação inválida: nenhuma disciplina ou grade parcial é criada.",
                ),
                (
                    "<b>F02</b><br/>Registrar frequência",
                    "Disciplina e data da grade pendente; situação: presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
                    "A situação e as faltas daquela data são gravadas; o resumo é recalculado.",
                    "Data/situação inválida, data já resolvida ou falha de gravação: registro e totais anteriores permanecem.",
                ),
                (
                    "<b>F03</b><br/>Corrigir frequência",
                    "Data já resolvida; nova situação válida; opção Corrigir.",
                    "Altera o registro da mesma data e recalcula faltas, limite e percentual.",
                    "Data pendente, entrada inválida ou falha de gravação: situação anterior permanece.",
                ),
                (
                    "<b>F04</b><br/>Consultar frequência",
                    "Selecionar uma disciplina pelo nome.",
                    "Mostra encontros, faltas usadas, limite, saldo e frequência quando não há pendências.",
                    "Falha de leitura é informada; a consulta não modifica dados.",
                ),
                (
                    "<b>F05</b><br/>Adicionar atividade",
                    "Disciplina existente; data, tipo prova/trabalho e título.",
                    "Atividade gravada e vinculada à disciplina.",
                    "Disciplina ou dados inválidos, ou falha de escrita: agenda e frequência permanecem iguais.",
                ),
                (
                    "<b>F06</b><br/>Consultar agenda",
                    "Abrir Agenda ou o cartão da disciplina.",
                    "Atividades ordenadas por data e, no empate, por inclusão; persistem após reabrir.",
                    "Falha de leitura é informada; a agenda não é alterada.",
                ),
                (
                    "<b>F07</b><br/>Renomear disciplina",
                    "Disciplina existente; novo nome não vazio.",
                    "Nome salvo e atualizado na lista e na agenda.",
                    "Nome inválido ou falha SQL: nome e demais dados anteriores permanecem.",
                ),
                (
                    "<b>F08</b><br/>Apagar dados da demo",
                    "Em Ajustes, digitar exatamente APAGAR.",
                    "Disciplinas, registros e atividades removidos na mesma transação.",
                    "Outra confirmação ou falha SQL: todos os dados permanecem.",
                ),
            ],
            [3.3 * cm, 4.5 * cm, 4.6 * cm, 4.6 * cm],
            dense="tight",
        )
    )

    section(s, "Regras e exemplo de cálculo")
    section(
        s,
        "Unidade e limite",
        "Uma aula vale 50 minutos. A grade contém datas e quantidade de aulas por encontro; portanto, um encontro de duas aulas vale 100 minutos. A base E soma as aulas dos encontros não cancelados. Pendências entram em E, mas não são presumidas presentes nem ausentes. O limite L é o inteiro inferior de 25% de E: L = E // 4. Faltas usadas A somam apenas registros resolvidos; saldo = máximo(0, L − A). Com todas as aulas resolvidas, frequência = 100 × (E − A) / E. Se E = 0 ou houver pendência, o percentual ainda não é exibido.",
    )
    s.append(
        table(
            ["Situação", "Uma chamada", "Duas chamadas"],
            [
                ("Presente", "0 falta", "0 falta"),
                ("Ausente", "Todas as aulas do encontro", "Todas as aulas do encontro"),
                (
                    "Atrasado ou saiu mais cedo",
                    "0 falta",
                    "Metade das aulas do encontro",
                ),
                ("Sem chamada", "0 falta; conta na base", "0 falta; conta na base"),
                ("Cancelada", "Encontro retirado da base", "Encontro retirado da base"),
            ],
            [5.4 * cm, 5.8 * cm, 5.8 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Exemplo",
        "Quatro encontros de duas aulas formam E = 8 e L = 2. Depois de registrar uma presença e uma ausência, A = 2, restam quatro aulas pendentes e o saldo é zero; ainda não há percentual. Ao marcar os outros dois encontros como presentes, a frequência é 100 × (8 − 2) / 8 = 75%. Corrigir a ausência para presente muda A para zero, o saldo para duas aulas e a frequência para 100%. Marcar um encontro como cancelado retira suas duas aulas da base e recalcula o limite.",
    )
    section(
        s,
        "Correção e datas",
        "Cada data tem um único Registro com a situação atual. A correção valida a nova situação, confirma a escrita no SQLite e então altera esse Registro em memória. A agenda guarda atividades em datas próprias; uma prova não altera a frequência. A grade é definida no cadastro, incluindo reposições conhecidas. A edição posterior dessas datas é uma limitação da entrega: para refazê-las, é preciso reiniciar a demo. A combinação de uma aula com duas chamadas foi restringida a uma chamada, para manter as faltas em unidades inteiras.",
    )

    section(s, "Classes e arquitetura")
    s.append(class_diagram())
    section(
        s,
        "Responsabilidades das classes",
        "ControleAcademico coordena cadastro, busca, agenda e reinício. Disciplina guarda a grade, escolhe uma política de chamada e calcula o resumo. Cada Registro representa a situação atual de uma data; Atividade guarda prova ou trabalho. PoliticaChamada define calcular_faltas(); ChamadaUnica e ChamadaDupla implementam regras diferentes. No diagrama, a seta indica navegabilidade (a classe de origem conhece a classe de destino) e os rótulos nas duas pontas são multiplicidades. Uma disciplina possui 1..* registros e 0..* atividades; cada registro e cada atividade pertencem a uma disciplina. Cada disciplina possui exatamente 1 política de chamada; o controle coordena 0..* disciplinas e 0..* atividades.",
    )
    section(
        s,
        "Orientação a objetos",
        "A grade fica protegida em Disciplina._registros; a propriedade registros devolve cópias. O setter de nome valida antes da alteração; registrar_presenca controla a mudança que envolve regra de domínio. PoliticaChamada e suas subclasses demonstram abstração, herança e polimorfismo: a mesma operação calcular_faltas() aplica a regra escolhida. Concentrar o cálculo nessas classes permite usar a mesma regra na página e nos testes; o SQLite persiste os resultados numa transação antes de atualizar os objetos.",
    )
    s.append(
        table(
            ["Camada", "Arquivos", "Responsabilidade"],
            [
                (
                    "Apresentação",
                    "web/index.html, app.css, app.js; web.py",
                    "Receber ações, enviar JSON e mostrar o estado.",
                ),
                (
                    "Negócio",
                    "models.py; exemplo.py",
                    "Validar dados, aplicar regras e preparar a amostra.",
                ),
                (
                    "Dados",
                    "database.py; frequencia.db",
                    "Gravar e recuperar disciplinas, registros e atividades no SQLite.",
                ),
            ],
            [3.2 * cm, 6.1 * cm, 7.7 * cm],
            dense=True,
        )
    )

    section(s, "Fluxos de sequência")
    section(
        s,
        "Cadastro de disciplina",
        "A página envia a grade a web.py. ControleAcademico constrói Disciplina, que valida código, nome, duração e datas. database.py grava disciplina e registros pendentes numa transação; após o commit, a nova matéria aparece na página.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "preencher"),
                (1, 2, "POST"),
                (2, 3, "criar"),
                (3, 4, "validar"),
                (3, 5, "INSERTs"),
                (5, 3, "commit"),
                (3, 2, "estado"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Controle", "Disciplina", "Dados"],
        )
    )
    section(
        s,
        "Registrar ou corrigir presença",
        "A página envia a data e a situação escolhida. Disciplina valida a operação, calcula as faltas e grava a correção no SQLite. Depois do commit, o mesmo Registro é atualizado em memória; uma nova consulta mostra a situação e os totais recalculados.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "situação"),
                (1, 2, "data + situação"),
                (2, 3, "registrar"),
                (3, 4, "calcular"),
                (3, 5, "UPDATE"),
                (5, 3, "commit"),
                (3, 2, "resumo"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Disciplina", "Política", "Dados"],
        )
    )
    section(
        s,
        "Execução",
        "O código, a base SQLite inicial e os testes estão em <b>Frequencia_UFMG_Entrega_Final.zip</b>. Com Python 3.11 ou superior, abra um terminal na pasta <b>demo</b> e execute <b>python web.py</b>. A página oferece cadastro manual e o botão <b>Usar dados de exemplo</b>.",
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verificacao():
    s = []
    page(s, "Verificação · APPOO 2026/2", "Frequência UFMG")
    s.append(
        P(
            "<b>Integrante:</b> Eduardo Henrique Rodrigues Silva · "
            "<b>Disciplina:</b> APPOO · Prof.ª Luiza Bernardes Real<br/>"
            "<b>Entrega testada:</b> Frequencia_UFMG_Entrega_Final.zip"
        )
    )
    section(
        s,
        "Como a verificação foi feita",
        "Os testes unittest exercitam as oito funcionalidades do Produto Final, na entrega identificada acima. Cada teste prepara objetos novos ou um SQLite temporário. As tabelas citam testes em demo/test_models.py ou demo/test_web.py; o resultado aparece em “Resultado da última execução” ao final deste PDF e em evidencias/unittest.txt no ZIP. E = aulas da base; A = faltas usadas; P = aulas pendentes; L = limite; F = frequência percentual. None indica percentual ainda indefinido.",
    )
    cenarios(
        s,
        "F01 · Cadastrar disciplina",
        "Estado inicial: controle vazio. C02 começa após cadastrar DEMO01 e registrar uma presença; C04 usa banco temporário com falha simulada.",
        [
            (
                "C01",
                "DEMO01, 2 chamadas, 2 aulas, quatro datas.",
                "Disciplina com quatro pendências; E=8.",
                "Quatro registros pendentes; E=8.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C02",
                "Repetir código como demo01.",
                "Rejeitar; primeiro cadastro igual.",
                "ValueError; um cadastro preservado.",
                "Aprovado",
                "test_codigo_duplicado_preserva_cadastro_e_frequencia",
            ),
            (
                "C03",
                "Nome/código vazio; data repetida; duração 3; 3 chamadas; ou 2 chamadas em 1 aula.",
                "Rejeitar; controle vazio.",
                "ValueError; nenhuma disciplina criada.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C04",
                "Falha no segundo INSERT da grade.",
                "Desfazer disciplina e registros.",
                "Banco e memória vazios.",
                "Aprovado",
                "test_falha_no_segundo_insert_desfaz_cadastro_e_grade",
            ),
        ],
    )
    section(s, "Registro e correção")
    cenarios(
        s,
        "F02 · Registrar frequência",
        "Estado inicial: quatro encontros de duas aulas pendentes. C07 usa um encontro e banco temporário; C26 usa um encontro de quatro aulas.",
        [
            (
                "C05",
                "Presente em 02/11; ausente em 04/11.",
                "A=2; P=4; L=2; percentual pendente.",
                "Resumo A=2, P=4, L=2, F=None.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C06",
                "Situação inválida, data fora da grade ou registrar novamente uma data resolvida.",
                "Rejeitar; registros e totais iguais.",
                "ValueError; estado preservado.",
                "Aprovado",
                "test_registro_invalido_nao_muda_grade_nem_totais",
            ),
            (
                "C07",
                "Falha SQL ao registrar a primeira data.",
                "Manter a data pendente.",
                "Pendente na memória e no SQLite.",
                "Aprovado",
                "test_falha_na_gravacao_preserva_memoria_e_banco",
            ),
            (
                "C26",
                "Registrar atraso/saída com uma chamada; repetir com duas chamadas.",
                "Em 4 aulas: uma chamada gera 0 falta; duas geram 2 faltas.",
                "Retornos 0 e 2 conforme a política.",
                "Aprovado",
                "test_mesma_operacao_tem_resultado_conforme_chamada",
            ),
        ],
    )

    cenarios(
        s,
        "F03 · Corrigir frequência",
        "C08: quatro encontros de duas aulas, com duas ausências. C09: grade pendente, depois uma ausência. C10: uma ausência gravada pela API.",
        [
            (
                "C08",
                "Corrigir uma ausência para presente.",
                "A cai de 4 para 2; mesma data.",
                "A=2; sem linha extra.",
                "Aprovado",
                "test_correcao_atualiza_e_recalcula",
            ),
            (
                "C09",
                "Corrigir data pendente ou usar situação inválida.",
                "Rejeitar; situação e totais iguais.",
                "ValueError; estado anterior igual.",
                "Aprovado",
                "test_correcao_invalida_preserva_registro_e_resumo",
            ),
            (
                "C10",
                "Corrigir ausência para presença e consultar novamente.",
                "Mesma data com situação presente após reabrir.",
                "HTTP 200; nova consulta recupera presente.",
                "Aprovado",
                "test_correcao_pela_api_persiste_ao_reabrir",
            ),
        ],
    )
    section(s, "Consulta e agenda")
    cenarios(
        s,
        "F04 · Consultar frequência",
        "Estado inicial: disciplina com quatro encontros de duas aulas; a consulta não grava.",
        [
            (
                "C11",
                "Consultar com quatro datas pendentes.",
                "E=8; P=8; L=2; F indefinida.",
                "E=8, P=8, L=2, F=None.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
            (
                "C12",
                "Resolver uma ausência e três presenças.",
                "A=2; frequência 75%.",
                "A=2; P=0; F=75%.",
                "Aprovado",
                "test_percentual_apos_todas_as_datas_resolvidas",
            ),
            (
                "C13",
                "Consultar código inexistente.",
                "Erro; grade anterior igual.",
                "ValueError; nenhum registro alterado.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
            (
                "C27",
                "Resolver 2 presenças, 1 sem chamada e 1 cancelada; depois cancelar tudo.",
                "Primeiro E=6, L=1, A=0, F=100%; depois E=L=0 e F indefinida.",
                "Resumo com 6 aulas e limite 1; ao cancelar tudo, base zero e F=None.",
                "Aprovado",
                "test_correcao_atualiza_e_recalcula",
            ),
        ],
    )

    cenarios(
        s,
        "F05 · Adicionar atividade",
        "Estado inicial: DEMO01 cadastrada, agenda vazia e grade pendente.",
        [
            (
                "C14",
                "Prova P1 em 03/11, fora da grade.",
                "Atividade vinculada; faltas iguais.",
                "ID salvo; resumo inalterado.",
                "Aprovado",
                "test_atividade_valida_persiste_sem_alterar_frequencia",
            ),
            (
                "C15",
                "Disciplina inexistente, data inválida, tipo inválido ou título vazio.",
                "Rejeitar; agenda vazia.",
                "ValueError; agenda e grade iguais.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C16",
                "Falha SQL ao inserir P1.",
                "Rejeitar; nenhuma atividade nova.",
                "OSError; banco reaberto vazio.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
        ],
    )
    section(s, "Agenda e nome")
    cenarios(
        s,
        "F06 · Consultar agenda",
        "Estado inicial: banco temporário com atividades cadastradas; C17 usa agenda vazia.",
        [
            (
                "C17",
                "Abrir agenda vazia.",
                "Lista vazia; frequência igual.",
                "Lista vazia, sem gravação.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C18",
                "Inserir P2, T1 e P1; reabrir.",
                "Três atividades em ordem de data/ID.",
                "Tupla recuperada e ordenada.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C19",
                "Falha SQLite ao consultar.",
                "Informar falha; dados preservados.",
                "HTTP 503; estado não alterado.",
                "Aprovado",
                "test_falhas_de_leitura_e_gravacao_sao_visiveis",
            ),
        ],
    )

    cenarios(
        s,
        "F07 · Renomear disciplina",
        "C20: DEMO01 com uma ausência e uma prova no SQLite. C21–C22: DEMO01 chamada Original, com grade pendente e agenda vazia.",
        [
            (
                "C20",
                "Renomear para Nome novo.",
                "Novo nome; código, grade e prova iguais.",
                "Nome salvo; vínculos preservados.",
                "Aprovado",
                "test_renomear_disciplina_valida_e_persiste",
            ),
            (
                "C21",
                "Nome vazio.",
                "Rejeitar; nome antigo igual.",
                "ValueError; Original preservado.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
            (
                "C22",
                "Falha SQL ao salvar nome.",
                "Rejeitar; nome antigo igual.",
                "OSError; memória e banco iguais.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
        ],
    )
    section(s, "Reinício da demo")
    cenarios(
        s,
        "F08 · Apagar dados da demo",
        "C23 e C25: disciplina com ausência e prova no SQLite. C24: disciplina com uma data pendente e agenda vazia.",
        [
            (
                "C23",
                "Confirmar APAGAR.",
                "Três tabelas vazias; novo cadastro possível.",
                "Banco e memória vazios; código recriado.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
            (
                "C24",
                "Informar apagar em minúsculas.",
                "Rejeitar; todos os dados iguais.",
                "HTTP 400; JSON antes/depois igual.",
                "Aprovado",
                "test_entradas_invalidas_preservam_estado",
            ),
            (
                "C25",
                "Falha SQL durante o reset.",
                "Desfazer exclusões; dados iguais.",
                "Disciplina, presença e prova recuperadas.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
        ],
    )

    section(
        s,
        "Como reproduzir",
        "No ZIP, entre em demo/ e execute <b>python -m unittest discover -v</b>. Pela interface, execute <b>python web.py</b> e abra <b>Ajustes → Executar testes</b>; os testes preparam seus próprios dados. Os cenários C01–C27 foram aprovados na última execução. As regressões de gravação parcial e reset estão nas respectivas tabelas.",
    )

    evidencia = (Path(__file__).parent / "package/evidencias/unittest.txt").read_text(
        encoding="utf-8"
    )
    testes = [
        linha.split(" (", 1)[0] + " ... ok"
        for linha in evidencia.splitlines()
        if linha.endswith(" ... ok")
    ]
    assert len(testes) == 28 and evidencia.rstrip().endswith("OK")
    meio = len(testes) // 2
    linhas = [f"{testes[i]:<70}{testes[i + meio]}" for i in range(meio)]
    linhas.extend(["", "Ran 28 tests · OK"])
    s.append(
        KeepTogether(
            [
                P("Resultado da última execução", "H2X"),
                P(
                    "Os 28 testes foram aprovados. A saída integral, com duração e nomes das classes, está em evidencias/unittest.txt no ZIP. Os testes usam objetos ou bancos temporários e podem ser executados em qualquer ordem."
                ),
                Preformatted(
                    "\n".join(linhas),
                    ParagraphStyle(
                        "SaidaUnittest", fontName="Courier", fontSize=7.6, leading=9
                    ),
                ),
            ]
        ),
    )
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    produto()
    verificacao()
    print("Relatórios gerados:", Path(__file__).parent)
