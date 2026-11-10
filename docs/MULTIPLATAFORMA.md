# Multiplataforma: PWA, Desktop, Android e iPhone

O cerebro, o banco de dados GTD e as anotacoes do Nextor ficam sempre na maquina do dono. Os aplicativos em cada sistema operacional funcionam como interface e reaproveitam uma unica base: o PWA universal servido em `nextor/web/`.

Nenhum token, endereco privado ou chave de API vai para os arquivos de empacotamento. O usuario informa o endereco do servidor e o token na propria interface (guardados apenas no `localStorage` do aparelho e enviados no cabecalho HTTP `X-Nextor-Token`).

---

## 1. Base universal: PWA instalavel (`/painel` e `/gtd`)

O servico HTTP entrega o manifesto global em `/manifest.webmanifest`, o Service Worker na raiz `/sw.js` (com cabecalho `Service-Worker-Allowed: /`) e a pagina de distribuicao em `/download`.

O Service Worker mantem em cache o shell da aplicacao (`/painel`, `/gtd`, `/rosto`, `/download`, folhas de estilo, scripts e icones `192x192` e `512x512`). Quando o aparelho fica sem rede, o aplicativo abre normalmente e avisa que o servidor local nao esta acessivel, sem exibir tela de erro do navegador. Chamadas de API (`/comando`, `/gtd/itens`, `/v1/*`, etc.) nunca sao gravadas no cache offline.

Como instalar sem gerar pacote nativo:

- **Android (Chrome):** acesse `http://<IP_DO_PC>:5005/painel` (ou `/download`) e toque em **Instalar app** ou no menu do navegador > **Instalar aplicativo**.
- **iPhone e iPad (Safari):** acesse `http://<IP_DO_PC>:5005/painel`, toque no botao **Compartilhar** e escolha **Adicionar a Tela de Inicio**.
- **Windows, Linux e macOS:** abra `http://localhost:5005/painel` no Edge, Chrome ou Safari e clique no icone de instalacao da barra de enderecos (ou rode `python scripts/empacotar_desktop.py --abrir` para abrir em janela dedicada `--app`).

---

## 2. Desktop: Windows, Linux e macOS (Tauri)

No computador onde o Nextor roda, o empacotamento desktop combina o servico local e a janela do PWA num instalador nativo:

- **Windows:** `.msi` e `.exe` (NSIS)
- **Linux:** `.AppImage` e `.deb`
- **macOS:** `.dmg` e `.app`

A configuracao fica em `packaging/desktop/tauri.conf.json` e aponta diretamente para `../../nextor/web`, evitando duplicar HTML, CSS ou JavaScript.

### Passos para gerar os instaladores desktop

1. Valide os ativos do PWA e sincronize a configuracao:
   ```bash
   python scripts/empacotar_desktop.py --plataforma windows
   ```
2. Instale os pre-requisitos do Tauri v2 na maquina de build (Rust via `rustup` e dependencias de WebView2 no Windows, `libwebkit2gtk` no Linux ou Xcode Command Line Tools no macOS).
3. Na pasta `packaging/desktop/`, execute o build para a plataforma atual:
   ```bash
   cargo tauri build
   ```
4. Os instaladores prontos sao gravados em `src-tauri/target/release/bundle/`.

Para uso imediato sem compilar binarios Rust, `nextor/janela.py` oferece `abrir_app("/painel")`, que detecta Chrome, Edge, Brave ou Chromium no Windows, Linux e macOS e abre o painel em janela propria sem barra de abas.

---

## 3. Android: APK via Capacitor ou TWA

No Android, o aplicativo funciona como controle remoto e painel completo conectado ao Nextor da maquina principal (pela rede Wi-Fi de casa ou por VPN privada).

A configuracao base do Capacitor fica em `packaging/android/capacitor.config.json` e usa `../../nextor/web` como `webDir`.

### Passos para gerar o APK Android

1. Valide o PWA e gere o arquivo `packaging/android/capacitor.config.json`:
   ```bash
   python scripts/empacotar_desktop.py --plataforma android
   ```
2. Na pasta `packaging/android/`, inicialize a plataforma Android do Capacitor (requer Node.js 20+ e Android SDK):
   ```bash
   npm install @capacitor/core @capacitor/cli @capacitor/android
   npx cap add android
   npx cap sync android
   ```
3. Gere o APK de instalacao pelo Android Studio (`npx cap open android`) ou via Gradle:
   ```bash
   cd android && ./gradlew assembleDebug
   ```
4. Ao abrir o APK no celular, informe no bloco **Conexao com o Nextor** o IP local do computador (ex.: `http://192.168.1.100:5005`) ou o IP da VPN e o token de acesso.

Alternativa leve (TWA / Bubblewrap): se o Nextor estiver acessivel em um dominio HTTPS dentro da sua VPN privada (ex.: certificados HTTPS do Tailscale), execute `npx @bubblewrap/cli init --manifest https://<seu-host-tailscale>/manifest.webmanifest` e `npx @bubblewrap/cli build` para empacotar o PWA em um APK Trusted Web Activity.

---

## 4. iPhone e iPad (iOS): PWA e limites da plataforma

No iOS, o caminho principal e instalar o PWA pelo Safari (**Compartilhar > Adicionar a Tela de Inicio**) combinado com o app **Atalhos** para comandos de voz na Siri (documentado em `docs/ATALHO_IPHONE.md`).

### Limites reais do iOS

- **Sem servico em segundo plano:** o iOS nao permite rodar o servidor Python/Ollama localmente em segundo plano continuo. O iPhone atua sempre como cliente conectado ao Nextor do computador.
- **Instalacao exclusiva via Safari:** no iOS, apenas o Safari (ou o menu Compartilhar do sistema no iOS 16.4+) cria o atalho em modo `standalone` sem barras de navegacao.
- **Notificacoes Web Push:** exigem iOS 16.4 ou superior e so funcionam depois que o PWA foi adicionado a Tela de Inicio.
- **Empacotamento nativo (Capacitor):** caso seja necessario distribuir um pacote `.ipa` via TestFlight, a mesma pasta `packaging/android/capacitor.config.json` suporta `npx cap add ios` em um Mac com Xcode e conta Apple Developer.

---

## 5. Distribuicao e acesso fora de casa

O endpoint `/download` (ou `/instalar`) exibe uma pagina de download que detecta automaticamente o sistema operacional do visitante pelo `User-Agent`, oferece o botao de instalacao direta do PWA e lista os comandos de cada plataforma. O endpoint `/v1/plataformas` retorna esse catalogo em JSON.

**Regra de rede:** nunca abra portas no roteador (port forwarding) para expor a porta `5005` na internet. Para usar o aplicativo fora de casa no Android, iPhone ou notebook externo, instale uma VPN privada (como Tailscale ou WireGuard) no computador do Nextor e no celular.
