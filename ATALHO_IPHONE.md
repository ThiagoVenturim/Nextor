# Atalho do iPhone: "Anotar no Nextor"

Faz voce ditar uma nota pela Siri; o notebook salva e o Nextor confirma falando no Nest.

Pre-requisitos:
- O servico do Nextor rodando no notebook: na pasta estudo-nest-mini, rodar
  `.venv/Scripts/python.exe nextor_service.py` e deixar a janela aberta.
- iPhone e notebook na mesma rede Wi-Fi de casa (<SUA_REDE_WIFI>).
- Notebook no IP <IP_DO_NOTEBOOK>, porta 5005. (Recomendado reservar esse IP no roteador,
  como foi feito com o Nest, para nao mudar.)

## Montar o atalho (app Atalhos do iPhone)

1. Abra o app Atalhos, toque em + (novo atalho).
2. Adicione a acao "Ditar texto" (Dictate Text). Idioma: Portugues (Brasil).
3. Adicione a acao "Obter conteudo de URL" (Get Contents of URL). Configure:
   - URL: http://<IP_DO_NOTEBOOK>:5005/anotar?token=SEU-TOKEN
   - Metodo: POST
   - Corpo da solicitacao: Formulario (Form)
   - Adicione um campo:
       Chave (Key): texto
       Valor (Value): o resultado de "Ditar texto" (toque e escolha a variavel Texto Ditado)
4. (Opcional) Renomeie o atalho para "Anotar no Nextor".
5. Para usar por voz: "E ai Siri, anotar no Nextor" e fale a nota.

## Variante "Falar no Nextor"

Mesmos passos, mas troque a URL por:
   http://<IP_DO_NOTEBOOK>:5005/falar?token=SEU-TOKEN
Assim o Nextor so fala o que voce ditar, sem salvar como nota.

## Dicas e seguranca

- O token esta no arquivo .env (campo NEXTOR_TOKEN). Use o mesmo valor no atalho no lugar de
  SEU-TOKEN. o .env nao vai para o git.
- So funciona dentro de casa. Nao abra porta no roteador. Para usar na rua, no futuro,
  usar uma VPN privada (Tailscale).
- Se der erro de conexao: confira se a janela do servico esta aberta no notebook e se o
  Firewall do Windows liberou o Python na rede privada (costuma perguntar na primeira vez).

## Atalho unico "Nextor" (recomendado)

Um so atalho que entende qualquer pedido (anotar, agenda, noticias, conversar):
- Acao "Ditar texto" -> acao "Obter conteudo de URL":
  - URL: http://<IP_DO_NOTEBOOK>:5005/comando?token=SEU-TOKEN
  - Metodo POST, corpo Formulario, campo texto = Texto Ditado
- Renomeie para "Nextor". Use com "E ai Siri, Nextor" e fale o pedido.
