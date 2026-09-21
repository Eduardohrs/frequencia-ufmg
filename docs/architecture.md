# Arquitetura inicial

O Frequência UFMG é um único produto com clientes Flutter para Android e web e um backend Python responsável pelas regras de negócio.

## Componentes

- Flutter: interface, autenticação do usuário e captura dos pings no Android.
- Backend Python: domínio, classificação de presença, cálculos, validações e API.
- Firebase Authentication: login Google.
- Cloud Firestore: dados sincronizados por usuário.
- Firebase Hosting: publicação do cliente web.

O backend verifica o token emitido pelo Firebase antes de acessar dados do usuário. Credenciais administrativas nunca ficam no aplicativo ou no repositório.

## Fluxo de presença

1. O cliente recebe o horário da sessão.
2. O Android coleta um ping 20 minutos após o início e outro 20 minutos antes do término.
3. Os registros são enviados ao backend.
4. O domínio Python classifica a sessão e calcula as faltas.
5. O resultado sincronizado é exibido no Android e na web.

Quando a coleta falhar, o registro permanece pendente e pode ser corrigido manualmente.
