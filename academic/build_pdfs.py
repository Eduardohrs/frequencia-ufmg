"""Gera os dois relatórios da mesma versão executável da demo acadêmica."""

# ruff: noqa: E501

from pathlib import Path

from pdf_layout import (
    VERSION,
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
from reportlab.platypus import Preformatted, Spacer


def contrato(story, titulo, entrada, sucesso, rejeicao):
    section(story, titulo)
    story.append(
        table(
            [
                "Condição inicial e entrada",
                "Sucesso: resultado e alteração",
                "Rejeição: motivo e estado",
            ],
            [(entrada, sucesso, rejeicao)],
            [5.6 * cm, 5.7 * cm, 5.7 * cm],
        )
    )
    story.append(Spacer(1, 0.18 * cm))


def cenarios(story, titulo, preparo, linhas):
    section(story, titulo, preparo)
    story.append(
        table(
            [
                "ID",
                "Regra e entrada",
                "Esperado",
                "Observado",
                "Situação",
                "Evidência unittest",
            ],
            linhas,
            [1.6 * cm, 4 * cm, 5.8 * cm, 5.8 * cm, 1.9 * cm, 6.4 * cm],
            dense="tight",
        )
    )
    story.append(Spacer(1, 0.15 * cm))


def produto():
    s = []
    page(s, "Quarta etapa · Produto final", "Frequência UFMG")
    s.append(
        P(
            "Produto acadêmico executável · interface local e regras em Python",
            "SubtitleX",
        )
    )
    s.append(
        table(
            ["Identificação", "Dados"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Disciplina", "APPOO · 2026/2 · Prof.ª Luiza Bernardes Real"),
                ("Versão", VERSION),
                ("Pacote", "Frequencia_UFMG_Entrega_Final.zip"),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    section(
        s,
        "Problema e público",
        "O estudante precisa acompanhar suas faltas antes da consolidação oficial. A aplicação registra o que ocorreu em cada encontro, calcula o saldo permitido e permite corrigir um lançamento. Provas e trabalhos ficam numa agenda curta ligada às disciplinas para ajudar no planejamento pessoal. O resultado não é um comprovante institucional de presença.",
    )
    section(
        s,
        "Funcionalidades entregues",
        "O programa começa com banco vazio e funciona sem conta, internet, Moodle, SIGA ou GPS. O estudante pode usar um botão para inserir dados inteiramente fictícios. A página local é a única interface: as regras e os cálculos permanecem nas classes Python.",
    )
    s.append(
        table(
            ["ID", "Ação", "Resultado visível"],
            [
                (
                    "F01",
                    "Cadastrar disciplina",
                    "Grade inicial de encontros pendentes.",
                ),
                (
                    "F02",
                    "Registrar frequência",
                    "Situação e faltas de uma data pendente.",
                ),
                (
                    "F03",
                    "Corrigir frequência",
                    "Novo registro da mesma data e totais recalculados.",
                ),
                (
                    "F04",
                    "Consultar frequência",
                    "Grade, limite, faltas, saldo e percentual quando definido.",
                ),
                (
                    "F05",
                    "Adicionar atividade",
                    "Prova ou trabalho associado à disciplina.",
                ),
                (
                    "F06",
                    "Consultar agenda",
                    "Atividades em ordem cronológica, inclusive após reabrir.",
                ),
                (
                    "F07",
                    "Renomear disciplina",
                    "Nome corrigido, sem alterar código ou histórico.",
                ),
                (
                    "F08",
                    "Apagar dados da demo",
                    "Reinício confirmado pelo próprio aplicativo.",
                ),
            ],
            [1.35 * cm, 5.25 * cm, 10.4 * cm],
            dense=True,
        )
    )

    page(s, "01 · Escopo", "Do produto real à demonstração acadêmica")
    section(
        s,
        "Dois artefatos do mesmo projeto",
        "A proposta inicial descreveu um produto de uso real: aplicativo Android, painel web, conta, importação acadêmica, localização programada e sincronização. Esse produto já é usado e implementa autenticação, importação e estimativas por localização, recursos que continuam em expansão e otimização no repositório https://github.com/Eduardohrs/frequencia-ufmg. A entrega deste ZIP é outra aplicação: uma demonstração independente, feita em Python e SQLite para expor o núcleo de orientação a objetos. O código do produto real não é usado como evidência dos contratos F01–F08 nem é exigido para executar a demo.",
    )
    section(
        s,
        "Por que o recorte mudou",
        "Durante o desenvolvimento, importação, autenticação e localização exigiram serviços externos, permissões do Android, infraestrutura remota e tratamento de indisponibilidade. A disciplina avalia programação orientada a objetos em Python; demonstrar essas camadas consumiria a apresentação sem esclarecer as classes e suas regras. O recorte acadêmico concentra o comportamento que continua útil quando essas integrações falham: cadastrar uma grade, registrar e corrigir frequência, calcular faltas e consultar provas e trabalhos. A agenda manual ajuda a planejar aulas próximas de avaliações; ela não altera os cálculos.",
    )
    s.append(
        table(
            ["Função prevista", "Protótipo anterior → demo final", "Produto real"],
            [
                (
                    "Conta e acesso",
                    "Não fazia parte da demo; segue fora do ZIP.",
                    "Login e serviços de conta.",
                ),
                (
                    "Disciplinas",
                    "Cadastro manual já existia; agora a grade persiste em SQLite.",
                    "Importação acadêmica com revisão manual.",
                ),
                (
                    "Frequência",
                    "Registro, consulta e correção já existiam; agora há seis situações, regras e persistência verificadas.",
                    "Estimativas de localização e correção do estudante.",
                ),
                (
                    "Agenda",
                    "Não existia; agora recebe provas e trabalhos manuais.",
                    "Integração com atividades acadêmicas.",
                ),
                (
                    "Plataforma",
                    "Antes terminal; agora página local, classes Python e SQLite.",
                    "Android/web, sincronização e serviços remotos.",
                ),
                (
                    "Parâmetros",
                    "Agora 1, 2 ou 4 aulas de 50 min por encontro; mínimo fixo de 75%.",
                    "Configuração mais ampla em evolução.",
                ),
            ],
            [3.1 * cm, 7.5 * cm, 6.4 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Limites assumidos nesta versão",
        "O protótipo anterior já permitia cadastro, registro, consulta e correção manual. Esta versão mantém essas ações e acrescenta persistência SQLite, agenda e contratos explícitos de erro e rollback. O limite inicial configurável da proposta foi fixado em 75% nesta demo para tornar verificável a regra de cálculo. Remarcação e edição individual de atividades não estão aqui. Se uma data foi cadastrada errada, o usuário reinicia a demo e cadastra a grade novamente. Nenhuma automação excluída deste ZIP é apresentada como testada no relatório de verificação.",
    )

    page(s, "02 · Contratos", "Cadastro e registro")
    contrato(
        s,
        "F01 · Cadastrar disciplina",
        "Banco vazio ou com outras disciplinas. Informar código e nome não vazios, uma ou duas chamadas, duração inteira de 1, 2 ou 4 aulas de 50 minutos por encontro e ao menos uma data válida sem repetição. Uma aula não aceita duas chamadas.",
        "Normaliza o código em maiúsculas; cria uma disciplina e um Registro pendente por data na mesma transação SQLite. Mostra a matéria pelo nome; código é referência secundária.",
        "Código já existente, data inválida/repetida, duração fora do conjunto ou combinação incompatível mostram erro específico. Nem disciplina nem grade parcial entram no banco ou na memória.",
    )
    contrato(
        s,
        "F02 · Registrar frequência",
        "Disciplina existente e data da grade com situação pendente. Escolher presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
        "Cria um novo Registro para a data. A política de uma ou duas chamadas calcula faltas em aulas de 50 minutos. Depois do commit, a interface mostra situação e totais recalculados.",
        "Disciplina/data inexistente, situação inválida, data já resolvida sem modo de correção ou registro alterado em outra janela: rejeita e conserva registro, faltas e banco. Para o último caso, a página deve ser atualizada antes de nova tentativa. Erro de escrita também conserva o estado anterior.",
    )
    section(
        s,
        "Unidade da duração",
        "Aulas e faltas são contadas em blocos de 50 minutos. Um encontro com duas aulas corresponde a 100 minutos. Carga horária em horas não é digitada nesta demo: a grade é formada diretamente por datas e aulas por encontro, evitando conversão ambígua de horas acadêmicas.",
    )

    page(s, "03 · Contratos", "Correção e consulta")
    contrato(
        s,
        "F03 · Corrigir frequência",
        "Uma data da grade já tem situação resolvida. Escolher nova situação entre as seis opções e acionar Corrigir. A data e a quantidade de aulas não mudam.",
        "Um novo Registro imutável substitui o valor daquela data; não acrescenta outra linha nem soma faltas duas vezes. O SQLite confirma a troca antes da atualização em memória. Todos os totais são recalculados a partir da grade.",
        "Correção de data ainda pendente, situação inválida, data fora da grade, registro alterado em outra janela ou falha SQLite: resposta clara e registro anterior intacto. A correção não altera atividades nem nome da matéria.",
    )
    contrato(
        s,
        "F04 · Consultar frequência",
        "Disciplina cadastrada. A página lista nomes; em tela estreita há seletor por nome. Não é preciso memorizar o código. Pode consultar mesmo com encontros pendentes.",
        "Mostra datas, situações e faltas, aulas elegíveis, pendências, limite inteiro, faltas usadas e saldo. O percentual só aparece quando não resta pendência elegível. Ler ou atualizar a página não grava dados.",
        "Código inexistente na camada Python é rejeitado. A interface conserva a seleção válida e pode tentar novamente se o banco não estiver disponível; nenhuma consulta altera registros.",
    )
    section(
        s,
        "Por que Registro é imutável",
        "A classe usa @dataclass(frozen=True). Uma correção não muda o objeto anterior: Disciplina cria outro Registro e substitui, no dicionário interno, o valor associado à mesma data. A versão do registro aumenta a cada troca; o navegador envia a versão que viu e o SQLite rejeita uma gravação baseada em versão antiga, mesmo se a situação voltar ao valor anterior. O dicionário é protegido; a propriedade registros devolve uma tupla.",
    )

    page(s, "04 · Contratos", "Agenda")
    contrato(
        s,
        "F05 · Adicionar atividade",
        "Disciplina cadastrada. Informar uma data válida, tipo prova ou trabalho e título não vazio. A data pode ser diferente das datas de aula; uma prova não é automaticamente uma chamada.",
        "Salva uma Atividade ligada ao código da disciplina. O SQLite gera identificador; agenda em memória só recebe o objeto depois do commit. Grade, faltas e percentual ficam iguais.",
        "Disciplina inexistente, data/tipo/título inválidos ou falha de escrita: erro específico e agenda intacta. Nenhuma aula é criada e nenhum registro de frequência é alterado.",
    )
    contrato(
        s,
        "F06 · Consultar agenda",
        "Banco vazio ou com atividades de várias disciplinas. Abrir Agenda ou ver o cartão de uma disciplina.",
        "Mostra título, tipo, data com ano e nome da disciplina. Ordena por data e, no empate, pela ordem de inserção. Depois de fechar e reabrir, lê os mesmos itens do SQLite.",
        "Agenda vazia mostra um estado vazio compreensível. Falha de leitura é informada; consultar não grava nem elimina atividade.",
    )
    section(
        s,
        "Contribuição da agenda para o objetivo",
        "Uma avaliação próxima pode influenciar a decisão do estudante de acompanhar uma aula e conferir sua frequência. Nesta entrega, a agenda é curta e manual; ela não altera o cálculo de faltas nem tenta substituir um calendário acadêmico completo.",
    )

    page(s, "05 · Contratos", "Nome e reinício")
    contrato(
        s,
        "F07 · Renomear disciplina",
        "Disciplina existente; informar novo nome não vazio. O código permanece a chave estável do cadastro e das atividades.",
        "Valida e salva o nome no SQLite; só depois o setter atualiza o nome do objeto. Os cartões e as atividades passam a exibir o novo nome, preservando datas, situações e totais.",
        "Nome vazio, disciplina inexistente ou falha SQL: resposta específica e nome anterior preservado no banco e na memória. Código, registros e agenda permanecem iguais.",
    )
    contrato(
        s,
        "F08 · Apagar dados da demo",
        "Abrir Ajustes e digitar exatamente APAGAR. A ação alcança apenas o banco local da demo, não o aplicativo real.",
        "Uma transação remove atividades, registros e disciplinas; após o commit as coleções em memória ficam vazias. O mesmo código pode ser cadastrado novamente.",
        "Cancelar ou digitar outra palavra não apaga nada. Se qualquer DELETE falhar, o SQLite desfaz a transação e as coleções mantêm os valores anteriores.",
    )
    section(
        s,
        "Dados de exemplo",
        "O botão Usar dados de exemplo chama uma função separada em exemplo.py. Ela constrói os objetos com as mesmas regras do cadastro, prepara duas presenças e uma prova fictícia e grava tudo numa transação. Só aceita banco vazio; repetir o pedido não duplica registros. O botão é conveniência de demonstração, não método da classe Disciplina.",
    )

    page(s, "06 · Regras", "Cálculo de frequência")
    section(
        s,
        "Definições explícitas",
        "Base E = soma das aulas dos encontros não cancelados. P = aulas de encontros pendentes dentro de E. A = faltas já resolvidas, em aulas de 50 minutos. Limite L = piso(E × 0,25), isto é, divisão inteira E // 4. Restantes R = máximo(0, L − A). Excesso = máximo(0, A − L). Quando P = 0 e E > 0, frequência = 100 × (E − A) / E. Caso contrário, o percentual fica indefinido; pendência não é presumida presente nem ausente.",
    )
    s.append(
        table(
            ["Situação", "Uma chamada", "Duas chamadas"],
            [
                ("Presente", "0 falta", "0 falta"),
                ("Ausente", "Todas as aulas do encontro", "Todas as aulas do encontro"),
                (
                    "Atrasado / saiu mais cedo",
                    "0 falta",
                    "Metade das aulas do encontro",
                ),
                (
                    "Sem chamada",
                    "0 falta; permanece na base",
                    "0 falta; permanece na base",
                ),
                ("Cancelada", "Sai da base", "Sai da base"),
            ],
            [5.6 * cm, 5.7 * cm, 5.7 * cm],
        )
    )
    section(
        s,
        "Exemplo conferível",
        "Quatro encontros de duas aulas geram E = 8 e L = 2. Depois de uma presença e uma ausência: A = 2, P = 4, R = 0 e percentual ainda indefinido. Ao resolver os dois pendentes como presentes: P = 0 e frequência = 100 × (8 − 2) / 8 = 75%. Corrigir a ausência para presente gera A = 0, R = 2 e frequência = 100%. Cancelar um encontro reduz E em 2 e recalcula L; reposição não é criada automaticamente nesta demo.",
    )
    section(
        s,
        "Regra de um ping ou dois",
        "Localização e pings não integram este executável acadêmico. Os nomes ChamadaUnica e ChamadaDupla designam apenas regras para converter o registro manual de atraso/saída em faltas; não são prova de presença física nem representam uma captura automática de GPS.",
    )

    page(s, "07 · Modelo", "Classes e responsabilidades")
    s.append(class_diagram())
    section(
        s,
        "Leitura do diagrama",
        "ControleAcademico coordena as operações e guarda as coleções. Disciplina protege código, nome, política e o dicionário data → Registro. Atividade referencia a matéria pelo código, sem guardar outro objeto Disciplina. PoliticaChamada é abstrata; ChamadaUnica e ChamadaDupla implementam calcular_faltas(). As multiplicidades abaixo descrevem a estrutura persistida, não contas de usuários do aplicativo real.",
    )
    s.append(
        table(
            ["Relação", "Multiplicidade e implementação"],
            [
                (
                    "Controle → Disciplina",
                    "Um controle guarda 0..* disciplinas; cada uma tem um código único.",
                ),
                (
                    "Disciplina → Registro",
                    "Uma disciplina tem 1..* datas; cada data aponta para exatamente um Registro.",
                ),
                (
                    "Controle → Atividade",
                    "Um controle guarda 0..* atividades; cada uma referencia uma disciplina por codigo_disciplina.",
                ),
                (
                    "Disciplina → Política",
                    "Cada disciplina escolhe exatamente uma política; as subclasses especializam a mesma operação.",
                ),
            ],
            [5.3 * cm, 11.7 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Conceitos de POO demonstrados",
        "Encapsulamento: a grade fica em _registros e o getter devolve tupla; o nome tem setter que valida. Herança por especialização: as duas políticas implementam a classe abstrata PoliticaChamada. Polimorfismo: Disciplina chama calcular_faltas sem saber qual implementação foi escolhida. Registro imutável não impede corrigir a frequência: o agregado substitui o valor do dia por outro objeto.",
    )

    page(s, "08 · Interações", "Sequências do núcleo")
    section(
        s,
        "Cadastro F01",
        "A página envia datas ISO a web.py. O controle constrói Disciplina e valida toda a grade antes de chamar database.py. Dados representa database.py e sua transação SQLite. Só após o commit a disciplina entra na memória e a página recebe o estado.",
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
        "Presença e correção F02–F03",
        "O controle encontra a disciplina. Ela valida data, situação e modo de correção; a política calcula faltas. Disciplina chama a gravação vinculada pelo controle. O Registro anterior só é substituído após o commit; o resumo é calculado do novo estado.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "situação"),
                (1, 2, "POST"),
                (2, 3, "registrar"),
                (3, 4, "localizar"),
                (4, 5, "salvar"),
                (5, 4, "commit"),
                (4, 3, "novo Registro"),
                (3, 2, "resumo"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Controle", "Disciplina", "Dados"],
        )
    )

    page(s, "09 · Interações", "Agenda, reset e rejeições")
    section(
        s,
        "Adicionar atividade F05",
        "O controle verifica se a disciplina existe e cria Atividade com data, tipo e título válidos. A gravação devolve um ID; somente então a agenda em memória recebe o objeto. Não há alteração de Registro nem de faltas.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "atividade"),
                (1, 2, "POST"),
                (2, 3, "adicionar"),
                (3, 4, "validar"),
                (3, 5, "INSERT"),
                (5, 3, "ID + commit"),
                (3, 2, "agenda"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Controle", "Atividade", "Dados"],
        )
    )
    section(
        s,
        "Apagar a demo F08",
        "web.py exige a confirmação APAGAR. O controle manda excluir atividades, registros e disciplinas na mesma transação. Só após o commit ele esvazia as coleções em memória e devolve o estado vazio.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "APAGAR"),
                (1, 2, "POST"),
                (2, 3, "apagar_tudo"),
                (3, 4, "DELETEs"),
                (4, 3, "commit"),
                (3, 2, "vazio"),
                (2, 1, "200"),
            ],
            ["Estudante", "Página", "web.py", "Controle", "Dados"],
        )
    )
    section(
        s,
        "Ramos alternativos, sem mudança parcial",
        "Entrada inválida em F01, F02/F03 ou F05 interrompe antes da gravação e web.py devolve erro 400. Se uma operação SQL falha, a transação é desfeita; o controle não publica objeto novo nem apaga memória e web.py informa erro 503. Em F08, confirmação diferente de APAGAR termina antes dos DELETEs. As tabelas C03–C07, C09–C10, C15–C16 e C23–C24 da verificação mostram os estados preservados.",
    )

    page(s, "10 · Implementação", "Camadas, dados e reprodução")
    section(
        s,
        "Separação de responsabilidades",
        "Apresentação: web/index.html, app.css e app.js recebem ações e mostram o estado; web.py converte JSON/datas e serve a página em 127.0.0.1. Negócio: models.py valida e calcula com classes de domínio; exemplo.py cria apenas a amostra fictícia. Dados: database.py cria tabelas, grava e recupera SQLite. A interface não calcula faltas e a camada de dados não escolhe política de chamada.",
    )
    section(
        s,
        "Persistência e integridade",
        "disciplinas usa código normalizado como chave; registros usa código + data e uma versão crescente; atividades usa ID do SQLite e referência ao código. Bancos criados antes desta versão ganham a coluna de versão sem perder registros. Cada mudança que envolve várias linhas usa transação. Totais não são gravados: são recalculados da grade. O arquivo frequencia.db entregue está vazio; o botão de exemplo o preenche com dados fictícios.",
    )
    section(
        s,
        "Como executar",
        "Requer Python 3.11 ou superior, sem dependências externas. Extraia Frequencia_UFMG_Entrega_Final.zip, entre na pasta demo e execute <b>python web.py</b>. Abra http://127.0.0.1:8878 se o navegador não abrir automaticamente. Clique Usar dados de exemplo ou cadastre manualmente uma disciplina. Em Ajustes, Executar testes roda unittest em bancos temporários; alternativamente, dentro de demo execute <b>python -m unittest discover -v</b>. Para sair, pressione Ctrl+C no terminal.",
    )
    section(
        s,
        "Limitações conhecidas e pacote",
        "Não há remarcação, edição/exclusão individual de atividades, importação universitária, autenticação ou comprovação de presença. Essas ações não são apresentadas como prontas. O ZIP inclui código, banco vazio, testes, README, evidência da última execução e os dois PDFs. A versão testada no relatório de verificação é a mesma indicada na capa.",
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verificacao():
    s = []
    page(s, "Quinta etapa · Verificação", "Frequência UFMG · Verificação")
    s.append(
        P(
            "Contratos, cenários e resultado observado da mesma versão do produto",
            "SubtitleX",
        )
    )
    s.append(
        table(
            ["Identificação", "Dados"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Versão testada", VERSION),
                ("Pacote", "Frequencia_UFMG_Entrega_Final.zip"),
                ("Execução", "python -m unittest discover -v, dentro de demo/"),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    section(
        s,
        "Método",
        "Cada teste constrói seus próprios objetos ou usa um arquivo SQLite temporário. Os dados da demo e do aplicativo real não entram nos testes. Para cada função F01–F08, as tabelas seguintes registram condição inicial, entrada, resultado previsto, resultado observado, situação e nome do teste. A evidência integral da última execução está em evidencias/unittest.txt no ZIP. A interface web possui testes HTTP com banco isolado; o botão Executar testes chama o mesmo conjunto.",
    )
    section(
        s,
        "Interpretação dos resultados",
        "Aprovado significa que a execução obteve o resultado esperado e conferiu o estado final; falhou significa divergência; não executado significa ausência de evidência. Um erro esperado em cenário de rejeição conta como aprovado quando o estado anterior permanece intacto. Os IDs C01–C24 e seus subcasos identificam condições verificadas; alguns subcasos pertencem ao mesmo teste automatizado.",
    )
    section(
        s,
        "Cobertura",
        "F01–F04: cadastro e frequência. F05–F06: agenda. F07–F08: nome e reinício. Cada grupo inclui sucesso e rejeição ou limite relevante.",
    )

    page(s, "Matriz · F01", "Cadastrar disciplina")
    cenarios(
        s,
        "F01 · Cadastrar disciplina",
        "Cada teste começa com controle vazio. C01–C03 usam objetos em memória; C04 usa banco SQLite temporário e simula falha durante a transação. As datas são de novembro de 2026.",
        [
            (
                "C01",
                "DEMO01, duas chamadas, duas aulas, quatro datas únicas.",
                "Uma disciplina e quatro registros pendentes; E=8.",
                "Objeto em memória com quatro registros pendentes; E=8 e P=8.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C02",
                "Repetir código demo01 com caixa diferente.",
                "Rejeitar; cadastro e frequência iniciais iguais.",
                "ValueError; um único cadastro preservado.",
                "Aprovado",
                "test_codigo_duplicado_preserva_cadastro_e_frequencia",
            ),
            (
                "C03a",
                "Data repetida na grade.",
                "Rejeitar cadastro; grade vazia.",
                "ValueError; controle continua vazio.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C03b",
                "Duração de 3 aulas por encontro.",
                "Rejeitar valor fora de 1/2/4.",
                "ValueError; controle continua vazio.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C03c",
                "Duas chamadas em encontro de 1 aula.",
                "Rejeitar combinação incompatível.",
                "ValueError; controle continua vazio.",
                "Aprovado",
                "test_entrada_invalida_nao_cria_disciplina",
            ),
            (
                "C04",
                "Falha SQL no segundo INSERT da grade.",
                "Rollback de disciplina e registros.",
                "Tabelas e memória sem cadastro parcial.",
                "Aprovado",
                "test_falha_no_segundo_insert_desfaz_cadastro_e_grade",
            ),
        ],
    )
    page(s, "Matriz · F02", "Registrar frequência")
    cenarios(
        s,
        "F02 · Registrar frequência",
        "C05 parte de DEMO01 com presença em 02/11 e três datas pendentes; C06 usa grade nova de quatro datas; C07 usa banco temporário com uma data pendente.",
        [
            (
                "C05",
                "Após presença em 02/11, registrar ausência em 04/11.",
                "E=8, A=2, P=4, L=2; percentual indefinido.",
                "Resumo igual a E=8, A=2, P=4, L=2, F=None.",
                "Aprovado",
                "test_criar_e_registrar_do_zero",
            ),
            (
                "C06a",
                "Registrar situação desconhecida.",
                "Rejeitar; registros e totais iguais.",
                "ValueError; grade e resumo iguais.",
                "Aprovado",
                "test_registro_invalido_nao_muda_grade_nem_totais",
            ),
            (
                "C06b",
                "Registrar data fora da grade.",
                "Rejeitar; registros e totais iguais.",
                "ValueError; grade e resumo iguais.",
                "Aprovado",
                "test_registro_invalido_nao_muda_grade_nem_totais",
            ),
            (
                "C07",
                "Falha de gravação antes de resolver 02/11.",
                "Pendente em memória e SQLite.",
                "OSError; ambos continuam pendentes.",
                "Aprovado",
                "test_falha_na_gravacao_preserva_memoria_e_banco",
            ),
            (
                "C07b",
                "Duas janelas carregam a mesma pendência; a primeira registra ausência.",
                "A segunda não pode sobrescrever sem recarregar.",
                "ValueError; ausência preservada no SQLite.",
                "Aprovado",
                "test_registro_desatualizado_nao_sobrescreve_outra_janela",
            ),
        ],
    )

    page(s, "Matriz · F03", "Corrigir frequência")
    cenarios(
        s,
        "F03 · Corrigir frequência",
        "Cada teste começa com quatro encontros de duas aulas. C08 cria duas ausências; C09 parte de uma grade pendente e depois resolve uma data; C10 corrige as duas ausências para presença antes de testar sem chamada e cancelamento.",
        [
            (
                "C08",
                "Após duas ausências, corrigir 02/11 para presente.",
                "Trocar Registro; A de 4 para 2, sem linha extra.",
                "A=2 após correção; a mesma data recebe outro Registro.",
                "Aprovado",
                "test_correcao_substitui_e_recalcula",
            ),
            (
                "C09a",
                "Corrigir um encontro ainda pendente.",
                "Rejeitar; grade e resumo iguais.",
                "ValueError; estado inicial preservado.",
                "Aprovado",
                "test_correcao_invalida_preserva_registro_e_resumo",
            ),
            (
                "C09b",
                "Após uma ausência, corrigir para situação desconhecida.",
                "Rejeitar; ausência e totais iguais.",
                "ValueError; grade e resumo anteriores preservados.",
                "Aprovado",
                "test_correcao_invalida_preserva_registro_e_resumo",
            ),
            (
                "C09c",
                "Outra janela viu ausente; depois mudou para presente e voltou a ausente.",
                "Rejeitar correção antiga mesmo com situação igual à inicial.",
                "Versão antiga rejeitada pela API; ausente preservada no SQLite.",
                "Aprovado",
                "test_aba_antiga_nao_sobrescreve_correcao_pela_api",
            ),
            (
                "C10a",
                "Corrigir 09/11 para sem chamada; 11/11 cancelada.",
                "Sem chamada fica na base; cancelada sai dela.",
                "E=6, P=0, A=0, L=1, R=1, F=100%.",
                "Aprovado",
                "test_correcao_substitui_e_recalcula",
            ),
            (
                "C10b",
                "Corrigir as três datas restantes para cancelada.",
                "Base E=0; percentual indefinido.",
                "F=None após todas as datas canceladas.",
                "Aprovado",
                "test_correcao_substitui_e_recalcula",
            ),
        ],
    )
    page(s, "Matriz · F04", "Consultar frequência")
    cenarios(
        s,
        "F04 · Consultar frequência",
        "Estado inicial: disciplina com quatro encontros de duas aulas; consultas não devem gravar.",
        [
            (
                "C11",
                "Consultar com pelo menos uma data pendente.",
                "Mostrar E, A, P, L, R; percentual indefinido.",
                "E=8, P=8, A=0, L=2, R=2, F=None.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
            (
                "C12",
                "Resolver todas: uma ausência, três presenças.",
                "E=8, A=2, L=2, frequência 75%.",
                "E=8, P=0, A=2, L=2, F=75%.",
                "Aprovado",
                "test_percentual_apos_todas_as_datas_resolvidas",
            ),
            (
                "C13",
                "Consultar código inexistente.",
                "Erro; nenhuma alteração na grade.",
                "ValueError e grade anterior igual.",
                "Aprovado",
                "test_consulta_nao_altera_registros",
            ),
        ],
    )

    page(s, "Matriz · F05–F06", "Agenda")
    cenarios(
        s,
        "F05 · Adicionar atividade",
        "Estado inicial: DEMO01 cadastrada e agenda vazia; grade com quatro registros pendentes.",
        [
            (
                "C14",
                "Prova P1 em 03/11, fora da grade.",
                "Atividade vinculada; frequência inalterada.",
                "ID persistido; grade e resumo iguais.",
                "Aprovado",
                "test_atividade_valida_persiste_sem_alterar_frequencia",
            ),
            (
                "C15a",
                "Tipo de atividade não permitido.",
                "Rejeitar; agenda vazia e grade igual.",
                "ValueError; agenda e frequência intactas.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C15b",
                "Título somente com espaços.",
                "Rejeitar; agenda vazia e grade igual.",
                "ValueError; agenda e frequência intactas.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C15c",
                "Data em texto, não objeto date.",
                "Rejeitar; agenda vazia e grade igual.",
                "ValueError; agenda e frequência intactas.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
            (
                "C16",
                "Falha de gravação simulada ao inserir P1.",
                "Nada acrescentado à agenda.",
                "OSError; agenda vazia no banco reaberto.",
                "Aprovado",
                "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
            ),
        ],
    )
    cenarios(
        s,
        "F06 · Consultar agenda",
        "Estado inicial: disciplinas com atividades fictícias; cada teste prepara seu banco.",
        [
            (
                "C17",
                "Abrir agenda vazia.",
                "Lista vazia; nenhum dado criado.",
                "Lista vazia retornada sem gravação.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C18",
                "Criar P2, T1 e P1; reabrir o controle.",
                "Três atividades recuperadas em ordem.",
                "Tupla reaberta igual à agenda persistida.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C19",
                "Atividades em datas diferentes.",
                "Ordem por data e ID no empate.",
                "Consulta ordenada sem mudar frequência.",
                "Aprovado",
                "test_agenda_vazia_e_ordenada_apos_reabrir",
            ),
            (
                "C19b",
                "Falha SQLite ao abrir o estado da agenda.",
                "Avisar falha de leitura sem apagar atividades.",
                "HTTP 503 com erro visível; estado não alterado.",
                "Aprovado",
                "test_falhas_de_leitura_e_gravacao_sao_visiveis",
            ),
        ],
    )

    page(s, "Matriz · F07–F08", "Nome e reset")
    cenarios(
        s,
        "F07 · Renomear disciplina",
        "Estado inicial: DEMO01, uma ausência e prova P1 em banco temporário.",
        [
            (
                "C20",
                "Renomear para Nome novo.",
                "Novo nome após reabrir; código, grade e P1 preservados.",
                "Nome novo no SQLite; dados associados iguais.",
                "Aprovado",
                "test_renomear_disciplina_valida_e_persiste",
            ),
            (
                "C21a",
                "Nome vazio ou só espaços.",
                "Rejeitar; nome antigo em memória e SQLite.",
                "ValueError; Original preservado em ambos.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
            (
                "C21b",
                "Falha simulada na gravação do nome.",
                "Rejeitar; nome antigo em memória e SQLite.",
                "OSError; Original preservado em ambos.",
                "Aprovado",
                "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
            ),
        ],
    )
    cenarios(
        s,
        "F08 · Apagar dados da demo",
        "Estado inicial: uma disciplina com presença e atividade; banco temporário.",
        [
            (
                "C22",
                "Confirmar APAGAR em Ajustes.",
                "As três tabelas vazias; pode recriar código.",
                "Banco e memória vazios; novo cadastro aceito.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
            (
                "C23",
                "Digitar apagar em minúsculas.",
                "Rejeitar; todos os dados anteriores iguais.",
                "HTTP 400; estado antes/depois igual.",
                "Aprovado",
                "test_entradas_invalidas_preservam_estado",
            ),
            (
                "C24",
                "Falha SQL durante o reset.",
                "Rollback integral; nada apagado.",
                "Disciplina, registro e atividade recuperados.",
                "Aprovado",
                "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
            ),
        ],
    )

    page(s, "Integração", "Caminho HTTP e estado persistente")
    section(
        s,
        "Fluxo completo pela API local",
        "O teste HTTP começa com banco temporário vazio, cria disciplina, registra ausência, corrige para presença, adiciona prova, renomeia, consulta de novo e apaga com APAGAR. O resultado observado após cada POST é comparado com a resposta esperada; uma nova requisição GET reconstrói os objetos do SQLite. Este teste chama a API diretamente e não executa o JavaScript da página.",
    )
    s.append(
        table(
            ["Condição", "Esperado", "Observado / evidência"],
            [
                (
                    "Cadastro e correção",
                    "Uma linha por data; totais após correção.",
                    "Resposta HTTP e GET reaberto iguais · test_fluxo_completo_e_reabertura",
                ),
                (
                    "Entrada inválida",
                    "Resposta compreensível e estado anterior igual.",
                    "HTTP 400 e comparação do JSON · test_entradas_invalidas_preservam_estado",
                ),
                (
                    "Falha de leitura/gravação",
                    "HTTP 503 e mensagem que identifica a falha.",
                    "HTTP 503 com mensagem 'disco' · test_falhas_de_leitura_e_gravacao_sao_visiveis; rollback: test_falha_na_gravacao_preserva_memoria_e_banco",
                ),
                (
                    "Banco de versão anterior",
                    "Adicionar a coluna de versão sem perder frequência.",
                    "Ausência anterior preservada e correção gravada · test_banco_antigo_migra_sem_perder_frequencia",
                ),
                (
                    "Exemplo fictício",
                    "Aceita só banco vazio; transação completa.",
                    "Segunda tentativa 400 · test_exemplo_persiste_ou_faz_rollback_completo",
                ),
                (
                    "Testes pelo botão",
                    "API devolve quantidade e OK da execução recebida.",
                    "Execução simulada na API · test_botoes_exemplo_e_testes_nao_exigem_preparo; execução real: página de evidência deste PDF",
                ),
            ],
            [4.1 * cm, 5.7 * cm, 15.3 * cm],
        )
    )
    section(
        s,
        "Limites calculados",
        "Os cenários de unidade e porcentagem verificam quatro encontros de duas aulas, piso de 25%, cancelamento fora da base e pendência sem frequência presumida. Atraso e saída usam políticas diferentes sem duplicar o algoritmo no controle. Uma falha de SQLite é testada com injeção temporária de erro; o banco da demonstração não é alterado.",
    )

    page(s, "Evidências", "Rastreabilidade dos testes")
    section(
        s,
        "Onde estão as provas",
        "O ZIP contém demo/test_models.py e demo/test_web.py. Cada linha de unittest inclui o nome do teste, seguido de ok. O arquivo evidencias/unittest.txt guarda a saída integral da última execução. A tabela resume os pontos de decisão mais sensíveis; as matrizes anteriores citam o teste de cada cenário pelo nome completo, sem depender da ordem de execução.",
    )
    s.append(
        table(
            ["Contrato", "Teste principal", "Estado conferido"],
            [
                (
                    "F01",
                    "test_entrada_invalida_nao_cria_disciplina",
                    "Cadastro e grade vazios após rejeição",
                ),
                (
                    "F02",
                    "test_falha_na_gravacao_preserva_memoria_e_banco",
                    "Registro pendente nos dois lados",
                ),
                (
                    "F03",
                    "test_correcao_substitui_e_recalcula",
                    "A e L recalculados, sem duplicação",
                ),
                ("F04", "test_consulta_nao_altera_registros", "Consultas sem mutação"),
                (
                    "F05",
                    "test_atividade_invalida_e_falha_de_escrita_preservam_agenda",
                    "Agenda e frequência intactas",
                ),
                (
                    "F06",
                    "test_atividade_valida_persiste_sem_alterar_frequencia",
                    "Agenda recuperada após reabertura",
                ),
                (
                    "F07",
                    "test_renomear_invalido_ou_falha_de_banco_preserva_nome",
                    "Nome anterior preservado",
                ),
                (
                    "F08",
                    "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
                    "Transação e rollback",
                ),
            ],
            [3 * cm, 11 * cm, 10 * cm],
            dense=True,
        )
    )
    section(
        s,
        "Independência",
        "Os testes de domínio puro criam classes novas; os de persistência usam TemporaryDirectory; os de HTTP iniciam servidor local em porta temporária. Nenhum cenário precisa de conta, rede, localização ou ordem especial. A verificação do pacote extrai o ZIP e repete unittest sobre os arquivos realmente enviados.",
    )

    page(s, "Defeitos e regressão", "O que foi corrigido")
    section(
        s,
        "Registro de ajustes verificáveis",
        "Na revisão do produto, a remarcação de data e o menu alternativo foram retirados para reduzir o escopo e manter um caminho único de uso. A criação do exemplo foi movida para exemplo.py, separada da classe de domínio. A fachada _DisciplinaPersistente foi eliminada; o controle liga a gravação a cada disciplina para que lista, busca e cadastro tenham o mesmo comportamento persistente. Esses itens eram caminhos adicionais que confundiam o recorte acadêmico e sua explicação oral.",
    )
    s.append(
        table(
            ["Risco observado", "Mudança", "Regressão executada"],
            [
                (
                    "Exemplo podia deixar dados parciais numa falha",
                    "Validação antes da gravação e uma única transação SQLite.",
                    "test_exemplo_persiste_ou_faz_rollback_completo",
                ),
                (
                    "Correção podia divergir do banco se a escrita falhasse",
                    "Salvar antes de substituir o Registro do dia.",
                    "test_falha_na_gravacao_preserva_memoria_e_banco",
                ),
                (
                    "Janela antiga podia sobrescrever um registro recente",
                    "Enviar a versão vista pela interface e atualizar SQLite só se coincidir.",
                    "test_aba_antiga_nao_sobrescreve_correcao_pela_api",
                ),
                (
                    "Reset com exclusão parcial",
                    "DELETEs na mesma transação; memória limpa após commit.",
                    "test_reset_apaga_tudo_e_preserva_estado_se_sql_falhar",
                ),
            ],
            [4.5 * cm, 6 * cm, 6.5 * cm],
        )
    )
    section(
        s,
        "Resultado e pendências",
        "A última execução de unittest foi aprovada; o número exato de testes e a saída completa constam em evidencias/unittest.txt. Não há falha conhecida nos contratos F01–F08 desta versão. Importação universitária, localização automática e remarcação de grade estão fora do recorte e não foram marcadas como verificadas neste relatório.",
    )

    page(s, "Reprodução", "Como conferir esta versão")
    section(
        s,
        "Preparação em poucos passos",
        "1. Extraia Frequencia_UFMG_Entrega_Final.zip. 2. Entre na pasta demo/. 3. Execute python web.py. 4. Abra http://127.0.0.1:8878 se necessário. 5. Clique Usar dados de exemplo e consulte a disciplina e a agenda. 6. Em Ajustes, clique Executar testes; o resultado aparece na página. O mesmo conjunto pode ser executado com python -m unittest discover -v, dentro de demo/. Não existe outro front nem script de configuração prévia.",
    )
    section(
        s,
        "Conferência manual a partir do zero",
        "Em Ajustes, apague os dados da demo com APAGAR. Cadastre DEMO01, duas chamadas e dois blocos de 50 minutos por encontro nas datas 02, 04, 09 e 11/11/2026. Marque 02/11 como ausente: faltas usadas 2, limite 2 e frequência ainda indefinida. Corrija 02/11 para presente: faltas usadas 0. Cadastre uma prova em 10/11/2026 e reabra a página: prova e frequência devem permanecer. Uma data fora da grade deve ser rejeitada sem mudar esses dados.",
    )
    section(
        s,
        "Como conferir a última execução",
        "Abra evidencias/unittest.txt no ZIP. O final do arquivo informa o total de testes e OK; as linhas anteriores listam cada nome usado nas matrizes. O verificador do pacote também extrai os arquivos e executa o conjunto sobre uma base temporária. O arquivo demo/frequencia.db fornecido é uma base inicial vazia, sem dados reais; o botão de exemplo monta dados fictícios quando solicitado.",
    )
    section(
        s,
        "Estado final",
        "Produto e verificação exibem o identificador de versão "
        + VERSION
        + ". Os resultados observados nas tabelas correspondem ao código e aos testes incluídos no mesmo ZIP. Se a universidade ou o navegador estiverem indisponíveis, o executável local continua demonstrável porque não consulta serviços externos.",
    )

    page(s, "Última execução", "Resumo legível de unittest")
    section(
        s,
        "Evidência no próprio relatório",
        "Este resumo preserva os nomes e resultados da execução usada para montar o ZIP. O arquivo evidencias/unittest.txt contém a saída integral, inclusive nomes de classes, duração e mensagens, para repetição e busca.",
    )
    evidencia = (Path(__file__).parent / "package/evidencias/unittest.txt").read_text(
        encoding="utf-8"
    )
    linhas_resumo = [
        linha.split(" (", 1)[0] + " ... ok"
        if " (" in linha and linha.endswith(" ... ok")
        else linha
        for linha in evidencia.strip().splitlines()
    ]
    s.append(
        Preformatted(
            "\n".join(linhas_resumo),
            ParagraphStyle(
                "SaidaUnittest", fontName="Courier", fontSize=9.2, leading=11.2
            ),
        )
    )
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    produto()
    verificacao()
    print("Relatórios gerados:", VERSION, Path(__file__).parent)
