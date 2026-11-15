"""Conteúdo dos relatórios; rode ``py academic/build_pdfs.py`` na raiz.

Cada bloco principal começa em página própria. A matriz da verificação usa A4
horizontal para preservar as seis colunas exigidas pelo enunciado.
"""

# Os parágrafos do relatório ficam em frases inteiras para revisão editorial.
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
from reportlab.lib.units import cm
from reportlab.platypus import Spacer


def contract(story, title, initial, success, rejection):
    section(story, title)
    story.append(
        table(
            [
                "Condição inicial e entrada",
                "Sucesso e estado final",
                "Rejeição e estado preservado",
            ],
            [(initial, success, rejection)],
            [5.5 * cm, 5.7 * cm, 5.8 * cm],
        )
    )
    story.append(Spacer(1, 0.19 * cm))


def product():
    s = []
    page(s, "Quarta etapa · Produto final", "Frequência UFMG")
    s.append(P("Relatório do produto acadêmico", "SubtitleX"))
    s.append(
        table(
            ["Identificação", "Informação"],
            [
                ("Integrante", "Eduardo Henrique Rodrigues Silva"),
                ("Disciplina e período", "APPOO · 2026/2"),
                ("Versão entregue", VERSION),
                ("Executável", "ZIP com demo/, banco SQLite, dados fictícios e testes"),
            ],
            [4.2 * cm, 12.8 * cm],
        )
    )
    s.append(Spacer(1, 0.25 * cm))
    section(
        s,
        "Problema e público",
        "O estudante da UFMG precisa saber quantas faltas ainda pode ter antes da consolidação oficial. O produto registra cada encontro, calcula o saldo em aulas de 50 minutos e permite corrigir um lançamento. Uma agenda pequena de provas e trabalhos ajuda a planejar a presença em semanas importantes. O resultado é pessoal; não substitui o diário da universidade.",
    )
    section(
        s,
        "O que está pronto",
        "A aplicação de terminal começa com um banco vazio, cadastra disciplinas e datas, registra e corrige frequência, consulta os cálculos e adiciona atividades. O SQLite conserva tudo entre aberturas. Há um script que cria dados fictícios em arquivo separado e testes automatizados que não dependem de conta, internet ou dados reais.",
    )
    s.append(
        table(
            ["ID e função", "Resultado que o estudante obtém"],
            [
                (
                    "F01 · Cadastrar disciplina",
                    "Cria disciplina e grade de encontros pendentes.",
                ),
                (
                    "F02 · Registrar frequência",
                    "Resolve uma data com situação e faltas.",
                ),
                (
                    "F03 · Corrigir frequência",
                    "Substitui um registro e recalcula os totais.",
                ),
                (
                    "F04 · Consultar frequência",
                    "Mostra grade, faltas, limite, saldo e percentual definido.",
                ),
                (
                    "F05 · Agendar atividade",
                    "Guarda prova ou trabalho vinculado à disciplina.",
                ),
                (
                    "F06 · Consultar agenda",
                    "Lista as atividades por data, inclusive depois de reiniciar.",
                ),
                (
                    "F07 · Renomear disciplina",
                    "Corrige o nome sem alterar código, grade ou frequência.",
                ),
            ],
            [5.3 * cm, 11.7 * cm],
        )
    )

    page(s, "01 · Escopo", "Continuidade do projeto e recorte")
    section(
        s,
        "Das entregas anteriores ao produto",
        "A proposta inicial combinou controle de frequência, dados acadêmicos e estimativa de presença por localização. O protótipo funcional mostrou cadastro e registro manuais. A versão final acadêmica conserva esse núcleo e integra persistência SQLite, consulta e correção completas e uma agenda local de avaliações. O percurso é executável desde o banco vazio: criar, registrar, corrigir, consultar, fechar e recuperar.",
    )
    section(
        s,
        "Ajuste de escopo explícito",
        "Autenticação, importação da UFMG e localização não integram este executável. Exigem serviços, credenciais e permissões externas; falhar neles não pode impedir o controle pessoal. Essas capacidades pertencem ao aplicativo ampliado e não são descritas como prontas na entrega acadêmica. Esta redução torna verificáveis as regras centrais sem depender de infraestrutura da universidade.",
    )
    s.append(
        table(
            ["Necessidade", "Nesta entrega", "Consequência e alternativa"],
            [
                (
                    "Frequência pessoal",
                    "Cadastro, registro, correção e consulta manuais.",
                    "Funciona sem internet; conferir o diário oficial separadamente.",
                ),
                (
                    "Planejar avaliações",
                    "Prova e trabalho locais, ligados à disciplina.",
                    "A agenda não altera as faltas; preenchimento manual.",
                ),
                (
                    "Dados oficiais/GPS",
                    "Não presentes no executável acadêmico.",
                    "Sem integração, o estudante ainda cadastra e corrige; GPS seria estimativa, nunca prova institucional.",
                ),
            ],
            [3.8 * cm, 6.1 * cm, 7.1 * cm],
        )
    )
    section(
        s,
        "Premissas visíveis ao usuário",
        "Cada data informada representa um encontro. A duração, em aulas de 50 minutos, é igual para todos os encontros da disciplina. A configuração de uma ou duas chamadas também é fixa por disciplina. A base vem dessas datas, não de carga oficial importada; o estudante deve comparar a grade com o plano de ensino. Uma prova pode ocorrer em data diferente das aulas cadastradas.",
    )
    section(
        s,
        "Regra de localização da proposta ampliada",
        "Na modelagem original, localização no campus é apenas uma estimativa. Uma chamada aceitaria um dos dois checkpoints positivo; duas chamadas distinguiriam dois positivos, somente o primeiro, somente o segundo ou nenhum. Falha de permissão ou GPS deixaria a aula pendente, nunca automaticamente ausente. O executável acadêmico não captura checkpoints: o próprio estudante informa a situação e pode corrigi-la.",
    )
    section(
        s,
        "Por que a agenda está no produto",
        "Ver uma prova ou trabalho na mesma disciplina contextualiza o saldo de faltas e ajuda a planejar presença. A função tem somente título, tipo e data. Ela não calcula notas, não dispara lembretes e não modifica presenças; apoia o objetivo central sem virar um gerenciador geral de tarefas.",
    )

    page(s, "02 · Contratos", "Cadastro e registro de frequência")
    contract(
        s,
        "F01 · Cadastrar disciplina",
        "Banco iniciado; código ainda ausente. Entradas: código e nome não vazios; 1 ou 2 chamadas; 1, 2 ou 4 aulas de <b>50 min</b> por encontro; ao menos uma data real DD/MM/AAAA, sem repetição.",
        "Normaliza código para maiúsculas; cria disciplina e datas pendentes em uma transação. Retorna a disciplina com resumo inicial. A memória só recebe o cadastro após o commit.",
        "Código duplicado, vazio, data inválida/repetida, número fora do conjunto ou duas chamadas em uma aula: informa motivo. Não cria disciplina nem parte da grade; falha de SQLite também não publica cadastro parcial.",
    )
    contract(
        s,
        "F02 · Registrar frequência",
        "Disciplina existente e data da grade ainda pendente. Entradas: código, data, situação presente, ausente, atrasado, saiu mais cedo, cancelada ou sem chamada.",
        "Política da disciplina calcula faltas em unidades de 50 min. Confirma a escrita no SQLite, substitui o pendente e recalcula base, faltas, pendências, limite, saldo, excesso e percentual.",
        "Data fora da grade, situação desconhecida ou repetição sem usar Corrigir: rejeita. Registro, banco e totais anteriores permanecem; falha de escrita também preserva a memória.",
    )
    section(
        s,
        "Sentido de cada situação",
        "<b>Presente:</b> zero faltas. <b>Ausente:</b> todas as aulas do encontro são faltas. <b>Atrasado</b> e <b>saiu mais cedo:</b> com duas chamadas perdem metade das aulas; com uma chamada não perdem. <b>Sem chamada:</b> encontro conta na base com zero faltas. <b>Cancelada:</b> encontro sai da base. <b>Pendente:</b> estado inicial, sem presença ou falta presumida.",
    )

    page(s, "03 · Contratos", "Correção, consultas e agenda")
    contract(
        s,
        "F03 · Corrigir frequência",
        "Disciplina e data existentes. O usuário escolhe Corrigir e informa uma das seis situações, inclusive para substituir cancelada ou sem chamada.",
        "Substitui apenas o registro daquela data; não acumula uma segunda falta. Recalcula os mesmos totais de F02 depois do commit.",
        "Situação ou data inválida: registro antigo e totais ficam iguais. Não cria nem remove outras datas da grade.",
    )
    contract(
        s,
        "F04 · Consultar frequência",
        "Disciplina cadastrada; entrada é o código, aceito em minúsculas ou maiúsculas.",
        "Exibe grade, situação e faltas por data, base elegível E, pendências, faltas A, limite L, saldo, excesso e frequência quando definida. Não grava dados.",
        "Código ausente: mensagem de não encontrada; nenhum dado é criado ou alterado.",
    )
    contract(
        s,
        "F05 · Agendar atividade",
        "Disciplina existente; código, data real DD/MM/AAAA, tipo prova ou trabalho e título não vazio. A data não precisa coincidir com aula.",
        "Grava atividade com identificador local e vínculo com disciplina. F06 a mostra mesmo após reabrir; não muda encontros ou faltas.",
        "Código inexistente, data inválida, tipo desconhecido, título vazio ou falha de escrita: agenda e frequência anteriores intactas.",
    )
    contract(
        s,
        "F06 · Consultar agenda",
        "Basta abrir o programa; não recebe filtro. Pode estar vazia.",
        "Lista atividades por data e ordem de inserção; se não houver itens, mostra Agenda vazia. Não grava dados.",
        "Como não há entrada a validar, não existe rejeição prevista nesta consulta.",
    )
    contract(
        s,
        "F07 · Renomear disciplina",
        "Disciplina existente. Entradas: código e novo nome com ao menos um caractere não branco.",
        "O setter valida o nome; o controle grava primeiro no SQLite e depois atualiza o objeto. Código, grade, atividades, presenças e totais ficam iguais.",
        "Código inexistente, nome vazio ou erro de escrita: rejeita; nome anterior permanece na memória e no banco.",
    )

    page(s, "04 · Regras", "Cálculo com unidades e exemplos")
    section(
        s,
        "Definições que o código aplica",
        "Uma aula equivale a <b>50 minutos</b>. E é a soma das aulas dos encontros cadastrados, exceto os cancelados. L = piso(0,25 × E), no código E // 4. A é a soma das faltas de registros resolvidos. Saldo R = máximo(0, L − A) e excesso X = máximo(0, A − L). F = 100 × (E − A) / E só aparece se E &gt; 0 e não há aulas pendentes. Antes disso, o programa informa frequência pendente; pendência não vira presença nem ausência.",
    )
    s.append(
        table(
            ["Caso", "Conta feita", "O que se vê"],
            [
                (
                    "4 encontros de 2 aulas",
                    "E=8; L=2. Uma ausência de 2 aulas: A=2.",
                    "R=0; F segue pendente se outras datas ainda não foram resolvidas.",
                ),
                (
                    "1 encontro cancelado",
                    "E cai de 8 para 6; L=piso(1,5)=1. Se A=2, X=1.",
                    "O limite cai; cancelamento não adiciona falta.",
                ),
                (
                    "4 aulas com atraso",
                    "1 chamada: 0 faltas. 2 chamadas: 4 // 2 = 2.",
                    "A mesma operação usa políticas concretas diferentes.",
                ),
                (
                    "Sem chamada",
                    "O encontro permanece em E e contribui 0 para A.",
                    "Não é confundido com cancelamento ou pendência.",
                ),
                (
                    "Base hipotética E=61",
                    "L=piso(15,25)=15; A=16 produz X=1.",
                    "Mostra o arredondamento; a demo calcula E pela grade.",
                ),
                (
                    "Base hipotética E=60",
                    "L=15; com A=8, R=7 e F final=86,67%.",
                    "F depende de todas as aulas estarem resolvidas.",
                ),
            ],
            [4.0 * cm, 7.0 * cm, 6.0 * cm],
        )
    )
    section(
        s,
        "Reposições e carga horária",
        "Uma reposição conhecida no cadastro pode entrar como data adicional e aumenta E. Não existe comando de adicionar datas depois. Também não há campo de carga horária oficial para converter: o usuário informa diretamente o número de aulas de 50 min por encontro. Essa limitação precisa estar clara porque evita tratar um valor acadêmico não conferido como autoritativo.",
    )

    page(s, "05 · Modelo", "Classes e suas relações")
    s.append(
        P(
            "Figura 1 · Diagrama vetorial. Ligações superiores: associação; triângulo inferior: especialização.",
            "SmallX",
        )
    )
    s.append(class_diagram())
    s.append(
        table(
            ["Elemento", "Responsabilidade e estado", "Relação"],
            [
                (
                    "ControleAcademico",
                    "Coordena cadastro, agenda e recuperação. Guarda coleções privadas.",
                    "Contém disciplinas e atividades.",
                ),
                (
                    "Disciplina",
                    "Valida grade e registro; mantém política e calcula resumo.",
                    "Contém registros; usa política.",
                ),
                (
                    "Registro",
                    "Valor imutável: data, aulas, situação e faltas. None indica pendência.",
                    "Um por data da grade.",
                ),
                (
                    "Atividade",
                    "Valor imutável: disciplina, data, tipo, título e ID local.",
                    "Vinculada à disciplina.",
                ),
                (
                    "PoliticaChamada",
                    "Classe abstrata com calcular_faltas(situação, aulas).",
                    "Contrato comum.",
                ),
                (
                    "ChamadaUnica e ChamadaDupla",
                    "Especializações que implementam regras diferentes para atraso/saída.",
                    "Herança e polimorfismo.",
                ),
            ],
            [4.1 * cm, 8.8 * cm, 4.1 * cm],
        )
    )
    section(
        s,
        "Encapsulamento e alteração controlada",
        "Código, chamadas e registros são expostos por propriedades de leitura. A coleção sai como tupla; Registro e Atividade são imutáveis. <b>Nome</b> tem getter e setter com validação; no fluxo persistente, F07 grava antes de usar o setter. Não há setter para faltas, data, código ou título, pois uma alteração direta contornaria as regras ou a chave no banco. Presenças e atividades passam por operações próprias que validam e persistem antes de publicar a mudança.",
    )

    page(s, "06 · Interações", "Sequências do fluxo central")
    section(
        s,
        "F01 · Cadastro desde um banco vazio",
        "O menu converte as datas. ControleAcademico constrói Disciplina, que valida todos os campos antes da gravação. O banco insere disciplina e registros pendentes na mesma transação. O controle só inclui o objeto na memória após o commit. Por isso uma falha não deixa uma grade pela metade.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "dados da disciplina"),
                (1, 2, "criar_disciplina"),
                (2, 3, "validar + montar grade"),
                (2, 4, "INSERT + COMMIT"),
                (2, 1, "disciplina criada"),
                (1, 0, "resumo inicial"),
            ]
        )
    )
    section(
        s,
        "F02/F03 · Registrar ou corrigir",
        "O controle localiza a disciplina; ela valida data e situação. F02 exige pendência; F03 usa corrigir=True para substituir um valor resolvido. A política calcula faltas; o novo Registro é salvo antes de trocar o valor em memória. O resumo é derivado dos registros vigentes. Se o SQLite falhar, grade e resumo ficam iguais.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "data + situação"),
                (1, 2, "obter_disciplina"),
                (2, 1, "fachada persistente"),
                (1, 3, "registrar_presenca"),
                (3, 4, "calcular_faltas"),
                (3, 5, "UPSERT + COMMIT"),
                (3, 1, "novo registro"),
                (1, 0, "resumo"),
            ],
            ["Estudante", "Menu", "Controle", "Disciplina", "Política", "SQLite"],
        )
    )

    page(s, "07 · Implementação", "Camadas, banco e reprodução")
    section(
        s,
        "F05 · Salvar atividade sem mexer na frequência",
        "O menu converte a data; o controle verifica a disciplina e constrói uma Atividade válida. A escrita no SQLite termina antes de adicionar o objeto à agenda em memória. F06 ordena o que foi salvo. Um erro em qualquer validação ou na escrita não altera a agenda nem a grade de frequência.",
    )
    s.append(
        sequence_diagram(
            [
                (0, 1, "data + tipo + título"),
                (1, 2, "adicionar_atividade"),
                (2, 3, "validar objeto"),
                (2, 4, "INSERT + COMMIT"),
                (2, 1, "atividade salva"),
                (1, 0, "confirmação"),
            ],
            ["Estudante", "Menu", "Controle", "Atividade", "SQLite"],
        )
    )
    s.append(
        table(
            ["Camada", "Arquivo", "Papel"],
            [
                (
                    "Apresentação",
                    "demo/main.py",
                    "Lê teclado, converte entradas e mostra resultado ou erro compreensível.",
                ),
                (
                    "Negócio",
                    "demo/models.py",
                    "Valida regras, mantém objetos e calcula faltas pela política de chamada.",
                ),
                (
                    "Dados",
                    "demo/database.py",
                    "Cria tabelas e executa SQL parametrizado em transações.",
                ),
            ],
            [3.1 * cm, 4.3 * cm, 9.6 * cm],
        )
    )
    section(
        s,
        "Estrutura persistida",
        "<b>disciplinas:</b> código como chave, nome, chamadas e aulas por encontro. <b>registros:</b> chave composta código/data ISO, situação e faltas; chave estrangeira aponta para disciplina. <b>atividades:</b> ID gerado pelo banco, código, data ISO, tipo e título. A transação salva disciplina e grade juntas. Um registro ou atividade só chega à memória após o commit. Totais não são gravados: vêm da grade atual, evitando divergências.",
    )
    page(s, "08 · Execução", "Demonstração, testes e limites")
    section(
        s,
        "Como reproduzir",
        "Requer Python 3.11+; só biblioteca padrão. Extraia o ZIP, entre em demo/ e rode <b>python main.py</b>. Crie DEMO01 com duas chamadas, duas aulas por encontro e datas 02, 04, 09 e 11/11/2026. Marque 02/11 ausente, 04/11 presente, consulte e corrija 02/11. Feche e reabra: a correção permanece. Para uma base fictícia pronta em arquivo separado, rode <b>python dados_exemplo.py</b> e aponte FREQUENCIA_DB_PATH para exemplo.db, conforme README.",
    )
    s.append(
        table(
            ["Passo", "Ação no menu", "Resultado esperado"],
            [
                (
                    "1",
                    "Criar DEMO01 e quatro datas, duas aulas cada.",
                    "E=8; quatro datas pendentes; L=2.",
                ),
                (
                    "2",
                    "Registrar ausência em 02/11 e presença em 04/11.",
                    "A=2; R=0; ainda há quatro aulas pendentes.",
                ),
                ("3", "Consultar DEMO01.", "Mostra as duas situações e F pendente."),
                ("4", "Corrigir 02/11 para presente.", "A=0; R=2; não duplica a data."),
                (
                    "5",
                    "Adicionar prova P1 em 10/11 e ver agenda.",
                    "P1 aparece; faltas continuam iguais.",
                ),
                (
                    "6",
                    "Renomear para Disciplina de exemplo.",
                    "Só o nome muda; código, grade e faltas seguem iguais.",
                ),
                (
                    "7",
                    "Sair e iniciar novamente.",
                    "Nome, correção e prova recuperados do SQLite.",
                ),
            ],
            [1.6 * cm, 7.0 * cm, 8.4 * cm],
        )
    )
    section(
        s,
        "Teste e limitações",
        "Em demo/, execute <b>python -m unittest discover -v</b>. Cada teste constrói objetos próprios ou SQLite temporário; o banco de demonstração não é alterado. A grade tem um encontro por data, duração fixa e nenhuma inclusão posterior de datas. Não há edição de atividades nem conexão oficial. Este pacote é independente do aplicativo ampliado e não precisa de conta ou internet.",
    )
    section(
        s,
        "Mapa entre funções e código",
        "F01, F04, F05 e F07 passam por ControleAcademico em models.py; F02 e F03 passam por Disciplina.registrar_presenca e pela política de chamada selecionada; F06 lê ControleAcademico.atividades. O setter de nome fica em Disciplina. Todas as entradas e saídas do usuário ficam em main.py. A gravação e a recuperação usam database.py. O PDF de verificação relaciona cada função aos testes executados.",
    )
    build("Frequencia_UFMG_Produto_Final.pdf", s)


def verification():
    s = []
    page(s, "Quinta etapa · Verificação", "Frequência UFMG · Verificação")
    s.append(
        P(
            "Eduardo Henrique Rodrigues Silva  |  APPOO 2026/2  |  " + VERSION,
            "SubtitleX",
        )
    )
    section(
        s,
        "Método",
        "As tabelas verificam F01–F07 do relatório do produto. Cada linha fixa uma entrada concreta, estado esperado, estado observado e evidência. Os testes são independentes: criam objetos novos ou um SQLite temporário, sem tocar no banco da demonstração. Rode <b>cd demo</b> e <b>python -m unittest discover -v</b>. A transcrição integral da última execução fica em <b>evidencias/unittest.txt</b> no ZIP.",
    )
    s.append(
        table(
            ["Critério", "Como foi verificado"],
            [
                (
                    "Rastreabilidade",
                    "O mesmo identificador de versão aparece nos dois PDFs, no README e no ZIP.",
                ),
                (
                    "Rejeições",
                    "Testes comparam cadastro, grade, agenda ou resumo antes e depois.",
                ),
                (
                    "Persistência",
                    "Um novo ControleAcademico reabre o mesmo banco temporário.",
                ),
                (
                    "Falha de escrita",
                    "Mock produz OSError antes de publicar em memória; o banco é reaberto.",
                ),
                ("Menu", "Entradas simuladas percorrem o sistema desde o banco vazio."),
            ],
            [5 * cm, 21.1 * cm],
        )
    )
    section(
        s,
        "Convenções",
        "E = aulas elegíveis; A = faltas usadas; L = limite; R = saldo. Pendente é um encontro não resolvido. Aprovado significa que o teste citado passou na última execução e confirmou o estado da linha. Os IDs T01–T19 da coluna Evidência são ligados aos nomes completos dos métodos na página final.",
    )

    def matrix(title, initial, rows, *, new_page=True):
        if new_page:
            page(s, "Matriz de cenários", title, initial)
        else:
            s.append(Spacer(1, 0.45 * cm))
            section(s, title, initial)
        s.append(
            table(
                [
                    "ID",
                    "Regra e entrada",
                    "Resultado e estado esperados",
                    "Resultado e estado observados",
                    "Situação",
                    "Evidência",
                ],
                rows,
                [1.4 * cm, 6.1 * cm, 6.1 * cm, 6.1 * cm, 2 * cm, 4.4 * cm],
            )
        )

    matrix(
        "F01 · Cadastrar disciplina",
        "Estado inicial: controle e banco vazios. Datas fictícias 02, 04, 09 e 11/11/2026; cada cenário recria esse estado, salvo preparação indicada na linha.",
        [
            (
                "C01",
                "DEMO01, duas chamadas, duas aulas de 50 min e quatro datas válidas.",
                "Cria uma disciplina; quatro pendências; E=8, A=0, L=2.",
                "Código normalizado para DEMO01; quatro pendências; E=8, A=0, L=2.",
                "Aprovado",
                "T01",
            ),
            (
                "C02",
                "Após C01, tenta cadastrar demo01 de novo com outro nome.",
                "Rejeita duplicado; nome, grade, presenças e totais intactos.",
                "ValueError; disciplina, registros e resumo iguais ao anterior.",
                "Aprovado",
                "T02",
            ),
            (
                "C03",
                "Código vazio, número inválido, duas chamadas em uma aula, data repetida ou inválida.",
                "Rejeita cada entrada; zero disciplinas e zero datas.",
                "ValueError em cada subcaso; controle continuou vazio; menu rejeitou 31/02.",
                "Aprovado",
                "T03 / T16",
            ),
            (
                "C04",
                "Cria disciplina e presença em SQLite temporário; fecha e reabre.",
                "Nome, grade e presença recuperados sem duplicação.",
                "Novo controle recuperou nome e registro presente na data.",
                "Aprovado",
                "T04",
            ),
            (
                "C04A",
                "Gatilho SQL falha no segundo INSERT da grade, após inserir disciplina.",
                "Rollback de cadastro e datas; controle e SQLite vazios.",
                "IntegrityError; memória e banco reaberto sem disciplina.",
                "Aprovado",
                "T15",
            ),
        ],
    )

    matrix(
        "F02 · Registrar frequência",
        "Estado inicial: DEMO01 com quatro datas pendentes e duas aulas por encontro. C08 troca a duração para quatro aulas, conforme a linha.",
        [
            (
                "C05",
                "Marca 02/11 presente e 04/11 ausente.",
                "Faltas 0 e 2; A=2, E=8, L=2, R=0; quatro aulas pendentes.",
                "Registros 0 e 2; resumo confirmou A=2, E=8, L=2, R=0, pendências=4.",
                "Aprovado",
                "T01",
            ),
            (
                "C06",
                "Data fora da grade, data em texto no domínio ou situação desconhecida.",
                "Rejeita; todos os registros e totais permanecem iguais.",
                "ValueError nos subcasos; registros e resumo iguais ao antes.",
                "Aprovado",
                "T05",
            ),
            (
                "C07",
                "Após registrar ausência, tenta registrar presença na mesma data sem Corrigir.",
                "Rejeita; ausência original e resumo permanecem.",
                "ValueError; registro original e resumo iguais ao antes.",
                "Aprovado",
                "T05",
            ),
            (
                "C08",
                "Quatro aulas; atraso ou saída em uma e duas chamadas.",
                "Uma chamada: 0 faltas. Duas: 2 faltas.",
                "Ambas as situações deram 0 na política única e 2 na dupla.",
                "Aprovado",
                "T06",
            ),
            (
                "C09",
                "Simula OSError ao gravar ausência no SQLite.",
                "Registro pendente na memória e no arquivo; A permanece 0.",
                "OSError; memória e banco reaberto conservaram pendente; menu informou a falha.",
                "Aprovado",
                "T07 / T19",
            ),
        ],
    )

    matrix(
        "F03 · Corrigir frequência",
        "Estado inicial: DEMO01 com duas ausências de duas aulas nas primeiras datas; quatro encontros no total e política de duas chamadas.",
        [
            (
                "C10",
                "Corrige 02/11 de ausente para presente.",
                "Só esse registro muda; A cai de 4 para 2; excesso cai de 2 para 0.",
                "A caiu para 2; primeiro registro foi substituído sem duplicação.",
                "Aprovado",
                "T08",
            ),
            (
                "C11",
                "Corrige segunda ausência; marca 09/11 sem chamada e 11/11 cancelada.",
                "E=6, A=0, L=1, R=1, pendências=0, F=100%.",
                "Resumo confirmou E=6, A=0, L=1, R=1 e F=100%.",
                "Aprovado",
                "T08",
            ),
            (
                "C12",
                "Após registrar ausência, corrige com situação desconhecida.",
                "Rejeita; situação e todos os totais anteriores iguais.",
                "ValueError; registros e resumo comparados e iguais.",
                "Aprovado",
                "T09",
            ),
        ],
    )

    matrix(
        "F04 · Consultar frequência",
        "Estado inicial: C13 cria DEMO01; C14 consulta OUTRA, ainda não cadastrada. A consulta não deve gravar nada.",
        [
            (
                "C13",
                "Consulta código existente em minúsculas.",
                "Mesma disciplina, grade e resumo; nenhum registro muda.",
                "Resumo, registros e cadastro iguais ao anterior.",
                "Aprovado",
                "T10",
            ),
            (
                "C14",
                "Consulta OUTRA, não cadastrada.",
                "Mensagem de não encontrada; cadastro, registros e resumo preservados.",
                "ValueError; todas as coleções e totais permaneceram iguais.",
                "Aprovado",
                "T10",
            ),
            (
                "C15",
                "No menu, cadastra, registra, consulta e corrige desde banco vazio.",
                "Mostra saldo, excesso e percentual conforme cada etapa.",
                "Saída incluiu excesso, F pendente, 50% e depois 100%.",
                "Aprovado",
                "T11",
            ),
        ],
        new_page=False,
    )

    matrix(
        "F05 · Agendar atividade",
        "Estado inicial: DEMO01 cadastrada, agenda vazia e quatro registros pendentes. A data da atividade pode diferir da data de aula.",
        [
            (
                "C16",
                "Adiciona prova P1 em 04/11 e reabre SQLite temporário.",
                "Atividade ligada a DEMO01 persiste; grade e resumo iguais.",
                "Novo controle recuperou atividade; registros e resumo iguais ao antes.",
                "Aprovado",
                "T12",
            ),
            (
                "C17",
                "Código inexistente, data inválida, tipo seminário ou título vazio.",
                "Rejeita cada entrada; agenda continua vazia.",
                "ValueError em cada subcaso; agenda vazia.",
                "Aprovado",
                "T13",
            ),
            (
                "C18",
                "Simula OSError ao salvar prova válida.",
                "Agenda vazia na memória e banco reaberto; frequência intocada.",
                "OSError; memória e banco reaberto continuaram vazios.",
                "Aprovado",
                "T13",
            ),
        ],
    )

    matrix(
        "F06 · Consultar agenda",
        "Estado inicial: C19 começa com agenda vazia; C20 cria DEMO01 e uma prova fictícia. O teste de menu usa banco temporário próprio.",
        [
            (
                "C19",
                "Escolhe Ver agenda sem criar atividade.",
                "Informa Agenda vazia; não cria item.",
                "Saída do menu contém Agenda vazia; cadastro prosseguiu.",
                "Aprovado",
                "T14",
            ),
            (
                "C20",
                "Cria prova Avaliação 1 em 03/11 e escolhe Ver agenda.",
                "Lista data, DEMO01, prova e título; frequência não muda.",
                "Linha com os quatro campos encontrada; T12 confirmou frequência intacta.",
                "Aprovado",
                "T14 / T12",
            ),
        ],
        new_page=False,
    )

    matrix(
        "F07 · Renomear disciplina",
        "Estado inicial: DEMO01 cadastrada com nome Original, quatro encontros e agenda opcional. Cada teste usa arquivo SQLite temporário próprio.",
        [
            (
                "C21",
                "Troca o nome para Nome novo e reabre o banco.",
                "Novo nome persiste; código, grade e faltas não mudam.",
                "Memória e novo controle mostram Nome novo; grade igual.",
                "Aprovado",
                "T17",
            ),
            (
                "C22",
                "Tenta nome vazio, só espaços ou valor não textual.",
                "Rejeita cada entrada; nome Original continua.",
                "ValueError nos subcasos; nome Original preservado.",
                "Aprovado",
                "T18",
            ),
            (
                "C23",
                "Simula OSError ao gravar um nome válido.",
                "Nome Original na memória e no banco reaberto.",
                "OSError; ambos conservaram Original.",
                "Aprovado",
                "T18",
            ),
        ],
    )
    section(
        s,
        "Por que o nome muda sem afetar frequência",
        "O controle verifica o nome antes de gravar. Se o banco confirmar, usa o setter da Disciplina; em falha, o setter não é chamado. Código e registros não entram na operação. A tabela abaixo representa a ordem testada em T17 e T18.",
    )
    s.append(
        table(
            ["Etapa", "Operação", "Efeito no estado"],
            [
                ("1", "Menu lê código e novo nome.", "Nenhum dado muda."),
                (
                    "2",
                    "Controle valida disciplina e nome.",
                    "Entrada inválida encerra com o nome antigo.",
                ),
                (
                    "3",
                    "SQLite confirma UPDATE.",
                    "Falha faz rollback; memória continua igual.",
                ),
                (
                    "4",
                    "Setter de Disciplina recebe nome validado.",
                    "Só o nome muda; grade e atividades permanecem.",
                ),
            ],
            [1.6 * cm, 10.4 * cm, 14.1 * cm],
        )
    )

    page(s, "Evidências", "Execução, defeitos e reprodução")
    section(
        s,
        "Evidências · IDs da matriz e nomes dos testes",
        "Os IDs T01–T19 apontam para estes métodos de unittest e para evidencias/unittest.txt no ZIP. A situação da matriz descreve a última execução, não apenas uma intenção de teste.",
    )
    tests = [
        ("T01", "test_criar_e_registrar_do_zero"),
        ("T02", "test_codigo_duplicado_preserva_cadastro_e_frequencia"),
        ("T03", "test_entrada_invalida_nao_cria_disciplina"),
        ("T04", "test_sqlite_preserva_disciplina_entre_aberturas"),
        ("T05", "test_registro_invalido_nao_muda_grade_nem_totais"),
        ("T06", "test_mesma_operacao_tem_resultado_conforme_chamada"),
        ("T07", "test_falha_na_gravacao_preserva_memoria_e_banco"),
        ("T08", "test_correcao_substitui_e_recalcula"),
        ("T09", "test_correcao_invalida_preserva_registro_e_resumo"),
        ("T10", "test_consulta_nao_altera_registros"),
        ("T11", "test_fluxo_completo_sem_dados_preparados"),
        ("T12", "test_atividade_valida_persiste_sem_alterar_frequencia"),
        ("T13", "test_atividade_invalida_e_falha_de_escrita_preservam_agenda"),
        ("T14", "test_agenda_pelo_menu_comeca_vazia_e_exibe_atividade"),
        ("T15", "test_falha_no_segundo_insert_desfaz_cadastro_e_grade"),
        ("T16", "test_rejeicoes_e_conversoes_sao_tratadas"),
        ("T17", "test_renomear_disciplina_valida_e_persiste"),
        ("T18", "test_renomear_invalido_ou_falha_de_banco_preserva_nome"),
        ("T19", "test_falha_de_gravacao_mostra_erro_e_mantem_aula_pendente"),
    ]
    middle = (len(tests) + 1) // 2
    s.append(
        table(
            ["ID", "Método unittest", "ID", "Método unittest"],
            [
                (
                    tests[i][0],
                    tests[i][1],
                    tests[i + middle][0] if i + middle < len(tests) else "",
                    tests[i + middle][1] if i + middle < len(tests) else "",
                )
                for i in range(middle)
            ],
            [1.2 * cm, 11.85 * cm, 1.2 * cm, 11.85 * cm],
            dense="tight",
        )
    )
    section(
        s,
        "Defeitos identificados e corrigidos",
        "Os dois casos abaixo surgiram durante a integração. Após corrigir, repetimos os cenários e os demais testes; nenhum cenário da matriz ficou pendente na última execução.",
    )
    s.append(
        table(
            ["Problema", "Como reproduzir e consequência", "Correção e reexecução"],
            [
                (
                    "Retorno sem fachada",
                    "Em banco novo, cadastrar disciplina e registrar presença no objeto devolvido: antes mudava a memória, mas a reabertura mostrava pendente.",
                    "O cadastro agora devolve a fachada persistente. T04 e T11 repetem cadastro, registro e leitura.",
                ),
                (
                    "Memória antes do commit",
                    "Injetar OSError na gravação de um registro: o objeto não pode exibir ausência que o banco não tem.",
                    "Gravar primeiro, substituir depois; T07 e T19 verificam banco, memória e mensagem ao usuário.",
                ),
            ],
            [5.0 * cm, 10.6 * cm, 10.5 * cm],
            dense=True,
        )
    )
    page(s, "Última execução", "Evidência integral dos testes")
    section(
        s,
        "Como repetir sem dados reais",
        "O ZIP inclui demo/test_models.py, demo/test_main.py, demo/README.md e evidencias/unittest.txt. Extraia, entre em demo/ e rode <b>python -m unittest discover -v</b>. Os testes não exigem conta, internet, Moodle ou GPS. Para operar o produto, rode <b>python main.py</b>; para gerar dados fictícios em arquivo separado, rode <b>python dados_exemplo.py</b>.",
    )
    evidence_path = Path(__file__).parent / "package" / "evidencias" / "unittest.txt"
    evidence = evidence_path.read_text(encoding="utf-8-sig")
    lines = [line for line in evidence.splitlines() if line.startswith("test_")]
    if not lines or "OK" not in evidence:
        raise RuntimeError("A evidência de unittest precisa existir e terminar em OK.")
    observed = []
    for line in lines:
        name = line.split(" (")[0]
        status = line.rsplit("...", 1)[-1].strip()
        if status != "ok":
            raise RuntimeError("Há teste sem resultado aprovado: " + line)
        observed.append((name, status))
    paired = []
    middle = (len(observed) + 1) // 2
    for i in range(middle):
        other = observed[i + middle] if i + middle < len(observed) else ("", "")
        paired.append((observed[i][0], observed[i][1], other[0], other[1]))
    s.append(
        table(
            ["Método executado", "Obs.", "Método executado", "Obs."],
            paired,
            [11.1 * cm, 1.95 * cm, 11.1 * cm, 1.95 * cm],
            dense=True,
        )
    )
    summary = next(
        (line for line in evidence.splitlines() if line.startswith("Ran ")), ""
    )
    section(
        s,
        "Resultado final",
        f"{summary}. O processo terminou com <b>OK</b>. A saída textual completa, "
        "incluindo a classe de cada teste, está em evidencias/unittest.txt no ZIP. "
        "Todos os cenários da matriz ficaram aprovados nesta rodada.",
    )
    build("Frequencia_UFMG_Verificacao.pdf", s, wide=True)


if __name__ == "__main__":
    product()
    verification()
