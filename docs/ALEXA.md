# Guia de Integracao: Skill da Alexa no Nextor

Este guia descreve como configurar do zero uma skill personalizada da Amazon Alexa para conversar com o Nextor, mantendo seguranca maxima sem expor portas no roteador.

---

## 1. Arquitetura e Seguranca

```
Dispositivo Echo / Alexa App
            │
            ▼ (HTTPS com assinatura criptografica Amazon)
Cloudflare Tunnel / Tailscale Funnel
            │
            ▼ (HTTPS -> HTTP local seguro)
Nextor Endpoint: /v1/alexa
            │
            ▼
Verificacao de Assinatura Amazon + Token
            │
            ▼
Endpoint /v1/assistente -> Roteador Nextor -> Cerebro / Habilidades
```

### Principios Fundamentais:
1. **Zero Portas Abertas no Roteador**: O trafego e tunelado de fora para dentro exclusivamente via Cloudflare Tunnel ou Tailscale Funnel.
2. **Verificacao Rigorosa de Assinatura Amazon**:
   - URL do certificado validada: esquema `https`, host `s3.amazonaws.com`, porta 443 e caminho iniciando por `/echo.api/`.
   - Certificado X.509 verificado: vigencia temporal e SAN (Subject Alternative Name) contendo `echo-api.amazon.com`.
   - Assinatura RSA com SHA-1 / SHA-256 e padding PKCS1v15 checada contra o corpo bruto da requisicao.
   - Timestamp da requisicao com tolerancia maxima de 150 segundos para evitar ataques de replay.
3. **Autenticacao Adicional por Skill ID e Token**:
   - `ALEXA_SKILL_ID`: valida que a requisicao veio exatamente da sua skill.
   - `ALEXA_ADAPTADOR_TOKEN`: token revogavel do Nextor passado via cabecalho ou query string.

---

## 2. Criacao da Skill no Amazon Developer Console

1. Acesse o [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask).
2. Clique em **Create Skill**.
3. Defina as configuracoes basicas:
   - **Skill name**: `Nextor`
   - **Primary locale**: `Portuguese (BR)`
   - **Experience / Model**: `Other` -> `Custom`
   - **Hosting logic**: `Provision your own` (sua propria infraestrutura via endpoint HTTPS).
4. Clique em **Create Skill** e escolha o template **Start from Scratch**.

---

## 3. Modelo de Interacao (Interaction Model)

No menu lateral esquerdo:
1. Em **Invocation**, configure **Skill Invocation Name**: `nextor`.
2. Em **JSON Editor**, cole o modelo JSON abaixo e clique em **Save Model** e depois **Build Model**:

```json
{
  "interactionModel": {
    "languageModel": {
      "invocationName": "nextor",
      "intents": [
        {
          "name": "AMAZON.CancelIntent",
          "samples": []
        },
        {
          "name": "AMAZON.HelpIntent",
          "samples": []
        },
        {
          "name": "AMAZON.StopIntent",
          "samples": []
        },
        {
          "name": "AMAZON.FallbackIntent",
          "samples": []
        },
        {
          "name": "ComandoLivreIntent",
          "slots": [
            {
              "name": "comando",
              "type": "AMAZON.SearchQuery"
            }
          ],
          "samples": [
            "{comando}",
            "pergunte {comando}",
            "falar {comando}",
            "anotar {comando}",
            "diga {comando}",
            "execute {comando}"
          ]
        }
      ],
      "types": []
    }
  }
}
```

---

## 4. Exposicao do Endpoint HTTPS Seguro

A Alexa exige que o endpoint seja HTTPS publicamente acessivel com certificado SSL valido. Escolha uma das duas opcoes sem abrir portas:

### Opcao A: Cloudflare Tunnel (Recomendado)
1. Instale o utilitario oficial `cloudflared`.
2. Inicie o tunel apontando para a porta do Nextor (padrao: 5005):
   ```bash
   cloudflared tunnel --url http://localhost:5005
   ```
3. O Cloudflare gerara uma URL publica (ex: `https://meu-nextor-tunnel.trycloudflare.com`).
4. Seu endpoint completo sera: `https://meu-nextor-tunnel.trycloudflare.com/v1/alexa`.

### Opcao B: Tailscale Funnel
1. Habilite o Tailscale Funnel no seu node:
   ```bash
   tailscale funnel 5005
   ```
2. Seu endpoint completo sera: `https://seu-node.ts.net/v1/alexa`.

---

## 5. Configuracao do Endpoint no Alexa Developer Console

1. No menu lateral do console, clique em **Endpoint**.
2. Selecione **HTTPS**.
3. Em **Default Region**, insira a URL completa obtida no tunel (ex: `https://meu-nextor-tunnel.trycloudflare.com/v1/alexa`).
4. Em **Select SSL certificate type**, selecione:
   - `My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority` (padrao para Cloudflare e Tailscale).
5. Clique em **Save Endpoints**.

---

## 6. Configuracao do Nextor (.env)

No arquivo `.env` do Nextor na raiz do projeto, adicione:

```env
# Skill ID copiado do console da Alexa (formato: amzn1.ask.skill.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
ALEXA_SKILL_ID=amzn1.ask.skill.seu-id-aqui

# Token revogavel do adaptador Nextor (opcional, cadastrado em /v1/adaptadores)
ALEXA_ADAPTADOR_TOKEN=nx_alexa_token_aqui

# Ativa verificacao criptografica estrita de assinatura da Amazon (padrao: 1)
ALEXA_VERIFICAR_ASSINATURA=1
```

Se desejar que o tunel envie o token do adaptador via query string no endpoint da Alexa, use a URL:
`https://meu-nextor-tunnel.trycloudflare.com/v1/alexa?token=nx_alexa_token_aqui`

---

## 7. Validacao e Teste

### Pelo Simulador no Developer Console
1. Va para a aba **Test** no Alexa Developer Console.
2. Mude o seletor de "Off" para **Development**.
3. Digite ou fale:
   - `abra nextor`
     * Resposta esperada: "Nextor pronto. Como posso ajudar?"
   - `pergunte ao nextor o que tenho hoje`
     * Resposta esperada: Leitura dos seus compromissos e agenda do dia processados pelo Nextor.
   - `ajuda`
     * Resposta esperada: Explicacao das acoes que o Nextor pode executar.
   - `cancelar`
     * Resposta esperada: "Ate logo."

### Pelo Dispositivo Echo Fisico
Com a mesma conta Amazon do desenvolvedor logada no Echo:
- "Alexa, abra Nextor."
- "Alexa, pergunte ao Nextor o que tenho hoje."
- "Alexa, peça ao Nextor para anotar comprar cafe."

### Testes Unitarios Offline
Os testes automatizados validam toda a cadeia de certificados e assinaturas com certificados simulados sem conexao externa:
```bash
.venv/Scripts/python.exe -m unittest tests/test_alexa.py
```
