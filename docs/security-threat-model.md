# Threat model do MVP

Este modelo cobre o Flutter web/Android, Firebase Authentication, App Check,
Firestore, o backend Python no Appwrite e o CI/CD. Integrações UFMG/Moodle entram
no modelo somente quando forem implementadas.

## Ativos e fronteiras

Os ativos protegidos são disciplinas, grades, sessões, frequências, avaliações,
identidade Google, futura sessão UFMG, integridade dos cálculos, chave de assinatura
Android e credenciais de implantação. O cliente e toda entrada recebida dele são
não confiáveis. Firebase, Appwrite, GitHub e futuros sistemas UFMG são fronteiras
externas distintas; CORS é apenas uma proteção de navegador e nunca autorização.

## Ameaças e controles

| Categoria | Cenário relevante | Controle atual | Risco residual / decisão |
| --- | --- | --- | --- |
| Spoofing | Token Firebase falso, expirado ou destinado a outro projeto | Assinatura, emissor, audiência, prazo e UID são verificados; App Check é obrigatório nas rotas Python | Uma sessão válida roubada vale até expirar; o código não copia credenciais, mas o Firebase SDK mantém a sessão local necessária ao login |
| Tampering | Um usuário altera documentos de outro ou envia estado acadêmico inválido | Caminho por UID, Security Rules default-deny, esquemas estritos e validação Python autoritativa | Leituras diretas dependem das Rules; os testes com emulador cobrem dono, terceiro e anônimo |
| Repudiation | Uma operação falha ou é negada sem ser diagnosticável | Logs imutáveis e sanitizados, IDs de correlação, resultado e duração | Correções manuais não formam trilha disciplinar por decisão de produto: é controle pessoal |
| Information disclosure | PII, localização ou credenciais aparecem em logs, Git ou respostas | Redação mínima, Gitleaks, push protection, respostas sem detalhes internos e nenhuma credencial administrativa no cliente | O cache acadêmico local é legível por quem controla o aparelho/perfil; ele não contém senha ou token UFMG |
| Denial of service | Payload grande, repetição, cold start ou estouro de cota | Limite de corpo, rate limit compartilhado, anti-replay, timeouts, cache local-first e quotas medidas | Appwrite gratuito pode ter cold start; leitura continua disponível sem ele |
| Elevation of privilege | Cliente chama rota administrativa ou backend contorna as Rules | Não há rota administrativa pública; backend reutiliza o bearer do usuário no Firestore; Appwrite API key serve apenas ao guard técnico | Configuração indevida de Rules/Appwrite continua sendo risco operacional coberto por CI e smoke |

## Privacidade e retenção

Dados acadêmicos permanecem sob `users/{uid}`. Logs operacionais aceitam apenas um
esquema sanitizado, recebem vencimento de 30 dias e são limpos oportunisticamente
pelo cliente. O TablesDB técnico guarda hashes de controle e o instante após o qual
deixam de ter valor; a remoção física periódica dessas linhas ainda integra o gate
de escala/privacidade. A réplica local é separada por UID e removível com os dados
do aplicativo/perfil. Exportar, restaurar e excluir integralmente a conta são gates
obrigatórios antes do beta, junto do ensaio de incidente da sessão 57.

## Integração UFMG futura

Senha UFMG nunca será armazenada. Se uma sessão reutilizável for tecnicamente
viável, ela deverá ser cifrada no backend, vinculada ao UID, ter expiração e
revogação, nunca entrar em logs e falhar pedindo nova autenticação quando expirar.
Conteúdo Moodle, HTML, calendários e PDFs será tratado como entrada hostil, com
limites de tamanho/tipo e parsing isolado. A funcionalidade manual de frequência
deve continuar funcionando quando qualquer integração estiver indisponível.

## Critério de revisão

Revisar este documento quando uma nova fonte externa, credencial, tipo de dado,
rota pública ou plataforma de persistência for adicionada e no gate pré-beta.
