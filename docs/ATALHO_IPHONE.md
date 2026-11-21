# Atalho do iPhone (Siri): Padronizado em `/v1/assistente`

Conecta a Siri e o app Atalhos do iPhone ao cerebro do Nextor usando o endpoint unificado `/v1/assistente` com token individual por adaptador. O texto entra, o Nextor responde em JSON e a propria Siri le a resposta no iPhone, AirPods ou CarPlay (sem efeito colateral de falar no Nest da sala).

## Pre-requisitos

- O servico do Nextor rodando no computador:
  `.venv/Scripts/python.exe -m nextor`
- iPhone e computador na mesma rede Wi-Fi de casa (`<IP_DO_COMPUTADOR>`, porta `5005`) ou conectados via VPN privada (Tailscale).
- Um token de adaptador exclusivo para a Siri (`siri`):
  - Opcao A (no `.env`): defina `SIRI_ADAPTADOR_TOKEN=nxt_seu_token_siri_seguro`
  - Opcao B (via API administrativa com o `NEXTOR_TOKEN` mestre):
    ```bash
    curl -X POST http://localhost:5005/v1/assistente/adaptadores \
      -H "X-Nextor-Token: SEU_NEXTOR_TOKEN_MESTRE" \
      -H "Content-Type: application/json" \
      -d '{"id": "siri", "nome": "Siri iPhone", "limite_por_minuto": 30}'
    ```
    Copie o campo `token` retornado (ele e exibido apenas uma vez; no disco fica somente o hash SHA-256).

## Montar o atalho "Nextor" (recomendado)

Um unico atalho que entende qualquer pedido (anotar, agenda, noticias, tarefas, estudos ou conversar):

1. Abra o app **Atalhos** no iPhone e toque em **+** (novo atalho).
2. Adicione a acao **Ditar texto** (`Dictate Text`). Idioma: `Portugues (Brasil)`.
3. Adicione a acao **Obter conteudo de URL** (`Get Contents of URL`):
   - **URL**: `http://<IP_DO_COMPUTADOR>:5005/v1/assistente`
   - **Metodo**: `POST`
   - **Cabecalhos** (`Headers`):
     - `Authorization`: `Bearer <TOKEN_DO_ADAPTADOR_SIRI>` (ou `X-Nextor-Token`: `<TOKEN_DO_ADAPTADOR_SIRI>`)
     - `Content-Type`: `application/json`
   - **Corpo da solicitacao**: `JSON`
     - Chave: `texto` | Valor: variavel `Texto Ditado`
4. Adicione a acao **Obter valor de dicionario** (`Get Dictionary Value`):
   - **Obter**: `Valor` para a chave `resposta` no `Conteudo do URL`.
5. Adicione a acao **Falar texto** (`Speak Text`) ou **Mostrar resultado** (`Show Result`) usando o `Valor do Dicionario`.
6. Renomeie o atalho para **Nextor**.
7. Para usar por voz: diga *"E ai Siri, Nextor"* e fale o pedido (ex.: *"o que tenho hoje"*, *"anota revisar peticao"*, *"me faz um quiz de constitucional"*).

## Variante: falar em voz alta no Google Nest Mini

Se voce quiser que a confirmacao saia nas caixas do Google Nest Mini da sala em vez de voltar silenciosamente para o iPhone, aponte o atalho para:
- `POST http://<IP_DO_COMPUTADOR>:5005/comando` (qualquer comando com voz no Nest)
- `POST http://<IP_DO_COMPUTADOR>:5005/anotar` (apenas salvar nota e falar no Nest)
- `POST http://<IP_DO_COMPUTADOR>:5005/falar` (apenas falar no Nest o texto ditado)

## Seguranca e revogacao

- Cada adaptador tem seu proprio token revogavel, comparado em tempo constante (`hmac.compare_digest`).
- Se precisar bloquear o atalho do celular sem afetar outros dispositivos:
  ```bash
  curl -X POST http://localhost:5005/v1/assistente/adaptadores/siri/revogar \
    -H "X-Nextor-Token: SEU_NEXTOR_TOKEN_MESTRE"
  ```
- Nunca abra portas no roteador. Para usar o atalho fora de casa no 4G/5G, use Tailscale no computador e no iPhone apontando para o IP Tailscale.
