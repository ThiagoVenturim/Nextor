# Assistentes: Ponto de Entrada Unico (`/v1/assistente`)

O Nextor centraliza a comunicacao de todos os assistentes externos atras de um unico endpoint autenticado: `POST /v1/assistente` (e `POST /v1/assistente/<id_adaptador>`).

O texto entra e a resposta sai em JSON, sem o efeito colateral de falar no Google Nest Mini ou nas caixas de som do PC. Assim, cada assistente (Siri, Alexa, Google Assistant via Home Assistant, Telegram ou clientes MCP) usa o mesmo cerebro, a mesma memoria e as mesmas habilidades de estudo e produtividade.

| Assistente | Caminho | Observacao |
|---|---|---|
| Siri | Atalhos do iPhone chamando `POST /v1/assistente` | Guia passo a passo em `docs/ATALHO_IPHONE.md` |
| Alexa | Skill personalizada com endpoint HTTPS (`/v1/alexa` ou `/v1/assistente/alexa`) | Usa Cloudflare Tunnel ou Tailscale Funnel com token, nunca porta aberta no roteador (`docs/ALEXA.md`) |
| Google Assistant / Nest | Gatilho por voz e webhook via Home Assistant | Configuracao pronta em `home_assistant/packages/nextor.yaml` e `home_assistant/HOWTO.md` |
| Claude, ChatGPT e outros | Servidor MCP (`python -m nextor.mcp_server`) e API `/v1/assistente` | Conexao documentada abaixo para cada cliente |
| Telegram | Bot que repassa texto e voz (`/v1/telegram/webhook` ou `/v1/assistente/telegram`) | Filtra por `TELEGRAM_USUARIOS_AUTORIZADOS` e despacha para `/v1/assistente` |

---

## 1. Contrato do Endpoint `/v1/assistente`

- **Metodo e URL**: `POST /v1/assistente` (ou `POST /v1/assistente/<id_adaptador>`)
- **Autenticacao**: token exclusivo do adaptador enviado em:
  - `Authorization: Bearer <token>` (recomendado)
  - `X-Nextor-Token: <token>`
  - `?token=<token>`
- **Corpo da requisicao** (`application/json` ou `application/x-www-form-urlencoded`):
  ```json
  {
    "texto": "o que tenho hoje na agenda?"
  }
  ```
  Tambem aceita os campos equivalentes `pergunta`, `comando`, `frase`, `mensagem`, `query`, alem dos payloads nativos da Alexa (`request.type`) e do Telegram (`message`).
- **Resposta de sucesso (`200 OK`)**:
  ```json
  {
    "ok": true,
    "resposta": "Hoje voce tem 2 compromissos...",
    "intencao": "agenda",
    "adaptador": "siri"
  }
  ```
- **Codigos de erro**:
  - `400`: texto ou payload vazio
  - `401`: token de adaptador ausente ou invalido
  - `403`: adaptador revogado ou token pertencente a outro adaptador
  - `429`: limite de requisicoes por minuto excedido (inclui cabecalho `Retry-After`)

---

## 2. Seguranca: Token por Adaptador, Limite e Log

1. **Tokens individuais e revogaveis**:
   - Cada assistente recebe seu proprio token (`nxt_...`).
   - O token puro nunca e gravado em disco: `adaptadores.json` armazena somente o hash `SHA-256` e um prefixo mascarado.
   - Todas as comparacoes de token e hash usam `hmac.compare_digest` em tempo constante (nunca `==`).
2. **Gerenciamento via API administrativa** (requer `NEXTOR_TOKEN` mestre):
   - Cadastrar adaptador:
     ```bash
     curl -X POST http://localhost:5005/v1/assistente/adaptadores \
       -H "X-Nextor-Token: SEU_NEXTOR_TOKEN_MESTRE" \
       -H "Content-Type: application/json" \
       -d '{"id": "siri", "nome": "Siri iPhone", "limite_por_minuto": 30}'
     ```
   - Listar adaptadores: `GET /v1/assistente/adaptadores`
   - Revogar adaptador imediatamente: `POST /v1/assistente/adaptadores/<id>/revogar`
   - Reativar adaptador: `POST /v1/assistente/adaptadores/<id>/ativar`
   - Consultar log de requisicoes: `GET /v1/assistente/logs?limite=50`
3. **Tokens via `.env` (opcional)**:
   - Voce tambem pode fixar o token de cada adaptador no `.env`: `SIRI_ADAPTADOR_TOKEN`, `ALEXA_ADAPTADOR_TOKEN`, `GOOGLE_ADAPTADOR_TOKEN`, `TELEGRAM_ADAPTADOR_TOKEN` e `MCP_ADAPTADOR_TOKEN`.
4. **Log sanitizado**:
   - Cada chamada grava data/hora, adaptador, status HTTP, intencao e texto truncado em 120 caracteres com quebras de linha e tabulacoes escapadas em `assistentes.log`.
   - Para desligar a gravacao do texto manteniendo metadados: `NEXTOR_LOG_TEXTO=nao`. Para desligar o log: `NEXTOR_LOG_ASSISTENTES=0`.

---

## 3. Configuracao por Assistente

### 3.1 Siri (Atalhos do iPhone / iPad / Apple Watch / CarPlay)
Aponte a acao "Obter conteudo de URL" do app Atalhos para `POST http://<IP>:5005/v1/assistente` com `Authorization: Bearer <SIRI_ADAPTADOR_TOKEN>` e corpo JSON `{"texto": "<Texto Ditado>"}`. Veja o passo a passo completo em `docs/ATALHO_IPHONE.md`.

### 3.2 Amazon Alexa (Echo)
A skill personalizada da Alexa envia requisicoes HTTPS assinadas pela Amazon para `/v1/alexa` ou `/v1/assistente/alexa` atraves de Cloudflare Tunnel ou Tailscale Funnel (sem abrir portas no roteador). O adaptador verifica o certificado X.509 da Amazon (`s3.amazonaws.com/echo.api/`), o timestamp (150s), o `ALEXA_SKILL_ID` e o `ALEXA_ADAPTADOR_TOKEN`, despachando o comando para `/v1/assistente`. Veja `docs/ALEXA.md`.

### 3.3 Google Assistant / Google Nest (via Home Assistant)
Como o Google encerrou as Conversational Actions, a integracao oficial usa o Home Assistant:
- Para resposta apenas em texto (automacoes, notificacoes ou Conversation Agent do HA): use `rest_command.nextor_assistente` em `home_assistant/packages/nextor.yaml`, que chama `POST /v1/assistente` com `GOOGLE_ADAPTADOR_TOKEN`.
- Para resposta falada diretamente no alto-falante do Nest Mini: use `rest_command.nextor_comando`. Veja `home_assistant/HOWTO.md`.

### 3.4 Claude, ChatGPT, Cursor e outros clientes (MCP e HTTP)

#### Via protocolo MCP (transporte stdio local)
Para conectar o Claude Desktop, Claude Code, Cursor ou qualquer cliente MCP ao Nextor:
```json
{
  "mcpServers": {
    "nextor": {
      "command": "C:/caminho/para/Nextor/.venv/Scripts/python.exe",
      "args": ["-m", "nextor.mcp_server"],
      "cwd": "C:/caminho/para/Nextor"
    }
  }
}
```
No Claude Code (CLI):
```bash
claude mcp add nextor -- .venv/Scripts/python.exe -m nextor.mcp_server
```

#### Via HTTP / Custom GPT Actions / Agentes externos
Qualquer assistente que suporte chamadas HTTP / OpenAPI Actions (como ChatGPT Actions, Dify, n8n ou Raycast) pode chamar diretamente:
- Endpoint: `POST /v1/assistente`
- Header: `Authorization: Bearer <MCP_ADAPTADOR_TOKEN>`
- JSON: `{"texto": "sua pergunta ou comando"}`

### 3.5 Telegram
Defina `TELEGRAM_BOT_TOKEN` e `TELEGRAM_USUARIOS_AUTORIZADOS` (lista de IDs numericos permitidos; se vazia, bloqueia tudo em modo fail-closed) no `.env`. O webhook em `/v1/telegram/webhook` (ou `/v1/assistente/telegram`) valida o usuario em tempo constante, transcreve mensagens de voz offline com Vosk quando necessario e encaminha os pedidos para `/v1/assistente`.
