# Notificacoes multicanal e temas (Issue #46)

O Nextor avisa voce por um ou varios canais ao mesmo tempo. Cada canal e um adaptador em
`nextor/notificacoes/` com a mesma interface, `enviar(titulo, corpo, urgencia)`, e o
roteador (`nextor/notificacoes/roteador_notificacoes.py`) decide para onde vai cada aviso.

| Canal | Slug | Variaveis no `.env` |
| --- | --- | --- |
| Telegram | `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DONO_CHAT_ID` (ou o primeiro de `TELEGRAM_USUARIOS_AUTORIZADOS`) |
| Discord (webhook) | `discord` | `DISCORD_WEBHOOK_URL` |
| Discord (bot) | `discord` | `DISCORD_BOT_TOKEN`, `DISCORD_CANAL_ID` |
| WhatsApp (opcional) | `whatsapp` | `WHATSAPP_API_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_DESTINATARIO`, `WHATSAPP_TEMPLATE` (opcional) |
| Web push no PWA | `webpush` | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBSCRIBER_EMAIL` |
| Voz (Nest ou PC) | `voz` | `NEXTOR_VOZ_SAIDA` (`nenhuma` desliga) |

Regras que valem para todos:

- Tokens, webhooks e chaves ficam so no `.env`. O repositorio tem apenas `.env.example` vazio.
- Canal sem variavel fica como "Variaveis .env ausentes" no painel e e pulado; nada quebra.
- Os logs registram so o tipo do erro, nunca URL de webhook, token, chave ou endpoint de push.
- Urgencia `alta` ou `critica` marca o titulo com `URGENTE:` e fura o horario de silencio.

## O que voce configura no painel

Em `/gtd`, aba Configuracoes, bloco "Notificacoes Multicanal":

- Canais ativos: liga e desliga cada canal.
- Eventos por canal: uma tabela com os eventos (lembretes, agenda do dia, tarefas atrasadas,
  PR para revisar, fim do pomodoro, lembrete e inicio de reuniao) e uma coluna por canal.
- Horario de silencio: inicio e fim no formato `HH:MM` (a janela pode cruzar a meia-noite).
- Tema e paleta: claro ou escuro, com acento azul, esmeralda, violeta ou ambar.

Tudo fica em `~/.nextor/config.json` (ou `NEXTOR_GTD_CONFIG_JSON`), nas chaves
`canais_ativos`, `eventos_notificacao`, `horario_silencio`, `tema` e `paleta`. Valores
invalidos (canal desconhecido, horario fora do formato, tema inexistente) sao descartados.

## Disparar avisos prontos

`POST /gtd/notificacoes/disparar` com o header `X-Nextor-Token` e o corpo
`{"evento": "agenda_do_dia" | "tarefa_atrasada" | "pr_para_revisar"}` monta o texto e envia
pelos canais configurados para aquele evento. Serve para uma tarefa agendada do sistema ou
uma automacao. Tarefas atrasadas sao avisadas uma vez por dia e cada PR uma vez so,
enquanto o servico estiver no ar. PRs para revisar usam a busca `review-requested` do GitHub
com `GITHUB_TOKEN` e `GITHUB_USUARIO`.

`POST /gtd/notificacoes/teste` (botao "Disparar Notificacao de Teste") manda um teste pelos
canais ativos.

## Telegram

Usa o mesmo bot de `nextor/telegram_bot.py`. Basta `TELEGRAM_BOT_TOKEN` e o seu chat em
`TELEGRAM_DONO_CHAT_ID`.

## Discord

Escolha um dos modos. Se os dois estiverem preenchidos, o webhook e usado.

- Webhook: no Discord, Configuracoes do canal > Integracoes > Webhooks > Novo webhook, copie
  a URL para `DISCORD_WEBHOOK_URL`. Precisa comecar com `https://`.
- Bot: crie uma aplicacao no portal de desenvolvedores do Discord, adicione um bot, convide-o
  ao servidor com a permissao de enviar mensagens e preencha `DISCORD_BOT_TOKEN` e
  `DISCORD_CANAL_ID` (ID numerico do canal; ative o modo desenvolvedor no Discord para copiar).

As mensagens nunca mencionam `@everyone` ou `@here`.

## WhatsApp (opcional)

O envio usa a WhatsApp Cloud API oficial da Meta, que exige uma conta WhatsApp Business.
Sem ela, deixe as variaveis vazias e o canal fica desligado. O que voce precisa:

1. Uma conta no Meta for Developers e um app com o produto WhatsApp.
2. No painel do produto, o ID do numero de envio (`WHATSAPP_PHONE_NUMBER_ID`) e um token de
   acesso (`WHATSAPP_API_TOKEN`). O token temporario do painel expira em 24 horas; para uso
   continuo, crie um usuario do sistema no gerenciador de negocios e gere um token permanente.
3. O seu numero em `WHATSAPP_DESTINATARIO`, com DDI e DDD (ex.: `5511999999999`). Com o numero
   de teste da Meta, o destino tambem precisa estar cadastrado na lista de numeros permitidos.
4. Mensagens de texto livre so sao entregues se voce mandou mensagem para o numero do app nas
   ultimas 24 horas. Para avisos a qualquer hora, crie um modelo de mensagem, espere a
   aprovacao e informe o nome em `WHATSAPP_TEMPLATE`. O modelo deve ter dois parametros no
   corpo: `{{1}}` recebe o titulo e `{{2}}` a mensagem. O idioma do modelo vai em
   `WHATSAPP_TEMPLATE_IDIOMA` (padrao `pt_BR`).

A Meta pode cobrar por conversa iniciada pela empresa; confira a tabela de precos da sua conta.

## Web push no PWA

1. Instale a dependencia opcional: `pip install -e ".[push]"` (instala `pywebpush`).
2. Gere um par de chaves VAPID em base64url, por exemplo com `npx web-push generate-vapid-keys`,
   e preencha `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` e
   `VAPID_SUBSCRIBER_EMAIL` (um e-mail de contato seu).
3. Abra `/gtd` no aparelho, va em Configuracoes e toque em "Ativar notificacoes neste
   aparelho". O navegador pede permissao e o aparelho fica registrado em
   `~/.nextor/push_inscricoes.json` (ou `NEXTOR_PUSH_INSCRICOES`).
4. No iPhone, o web push so funciona no iOS 16.4 ou superior e depois de adicionar o PWA a
   Tela de Inicio. O navegador exige HTTPS (ou `localhost`); fora de casa, use a VPN com um
   endereco HTTPS.

Inscricoes que o servico de push recusa como expiradas (HTTP 404 ou 410) sao apagadas.

Rotas usadas pelo PWA (todas exigem `X-Nextor-Token`):

- `GET /gtd/notificacoes/push/chave`: chave publica VAPID.
- `POST /gtd/notificacoes/push/inscrever`: corpo e o `PushSubscription.toJSON()` do navegador.
- `POST /gtd/notificacoes/push/cancelar`: `{"endpoint": "..."}`.

## Voz

Fala o aviso no Nest ou no PC conforme `NEXTOR_VOZ_SAIDA` (`pc`, `nest` ou `ambos`).
`NEXTOR_VOZ_SAIDA=nenhuma` desliga o canal.

## Testes

`tests/test_notificacoes.py` e `tests/test_notificacoes_multicanal.py` rodam sem rede: cada
canal recebe um cliente HTTP falso e `urllib.request.urlopen` e bloqueado. Os testes tambem
conferem que tokens e endpoints nao aparecem nos logs.
