# Backup e recuperação

## Estado do MVP

Código, configuração e artefatos publicados são recuperáveis pelo GitHub. Dados
acadêmicos têm o Firestore como fonte canônica. As cópias em `SharedPreferences` e
no cache nativo servem para abertura offline, mas podem estar antigas e somem com o
perfil/aplicativo; portanto não são backup.

O projeto permanece sem faturamento. Backup agendado, PITR, restore e exportação
gerenciada do Firestore exigem o plano Blaze e geram operações cobradas. Esses
recursos não fazem parte da estratégia gratuita e não devem ser habilitados por uma
automação ou mudança de infraestrutura implícita.

## Proteção temporária

Antes de migrações ou operações potencialmente destrutivas:

1. não executar testes de escrita contra produção;
2. registrar uma cópia privada, ignorada pelo Git, do estado acadêmico relevante;
3. verificar contagem de disciplinas, grades, sessões, frequências e avaliações;
4. ensaiar qualquer transformação apenas no emulador com dados sintéticos;
5. após a mudança, comparar contagens e amostras somente por leitura.

A cópia privada atual é um auxílio de recuperação, não um backup contínuo: seu ponto
conhecido é 05/10/2026 e mudanças posteriores não estão cobertas por ela. Assim, o
MVP ainda não promete RPO ou RTO.

## Gate antes do beta

A sessão de privacidade e recuperação deve entregar uma exportação versionada dos
dados do usuário, sem tokens ou logs; checksum e validação estrita antes de aceitar
o arquivo; prévia das mudanças; restauração idempotente e explícita; teste de
round-trip e de arquivo truncado/adulterado; exclusão integral; e um ensaio de
recuperação em ambiente isolado. A restauração nunca deve misturar UIDs nem substituir
produção silenciosamente.

Se no futuro houver autorização explícita para Blaze, backup gerenciado pode ser
avaliado como camada adicional, não como substituto da exportação portátil do
usuário.
