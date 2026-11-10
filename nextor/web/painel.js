'use strict';

const CHAVE_TOKEN = 'nextor.token';
const CHAVE_TOKEN_GTD = 'nextor_gtd_token';
const CHAVE_SERVIDOR = 'nextor.servidor_url';

let promptInstalacao = null;

function obterTokenInicial() {
  const hashParams = new URLSearchParams(window.location.hash.slice(1));
  const queryParams = new URLSearchParams(window.location.search);
  const tokenUrl = (hashParams.get('token') || queryParams.get('token') || '').trim();

  if (tokenUrl) {
    try {
      localStorage.setItem(CHAVE_TOKEN, tokenUrl);
      localStorage.setItem(CHAVE_TOKEN_GTD, tokenUrl);
      if (window.location.hash || queryParams.has('token')) {
        queryParams.delete('token');
        const novaQuery = queryParams.toString();
        const novaUrl = window.location.pathname + (novaQuery ? '?' + novaQuery : '');
        history.replaceState(null, '', novaUrl);
      }
    } catch (e) {
      // Ignora erro em modo privado restrito
    }
    return tokenUrl;
  }

  try {
    return localStorage.getItem(CHAVE_TOKEN) || localStorage.getItem(CHAVE_TOKEN_GTD) || '';
  } catch (e) {
    return '';
  }
}

function obterServidorBase() {
  try {
    const salvo = (localStorage.getItem(CHAVE_SERVIDOR) || '').trim();
    return salvo.replace(/\/+$/, '');
  } catch (e) {
    return '';
  }
}

let tk = obterTokenInicial();

function urlApi(caminho) {
  const base = obterServidorBase();
  if (!base) return caminho;
  return base + caminho;
}

function log(mensagem) {
  const el = document.getElementById('log');
  if (!el) return;
  el.textContent = typeof mensagem === 'string' ? mensagem : JSON.stringify(mensagem, null, 2);
}

function atualizarStatusRede() {
  const pill = document.getElementById('status-conexao');
  const txt = document.getElementById('status-conexao-texto');
  if (!pill || !txt) return;
  const online = navigator.onLine !== false;
  pill.setAttribute('data-online', online ? 'true' : 'false');
  txt.textContent = online ? 'Conectado' : 'Modo offline (shell)';
}

function cabecalhosAuth(extra) {
  const headers = Object.assign({}, extra || {});
  if (tk) {
    headers['X-Nextor-Token'] = tk;
  }
  return headers;
}

async function post(caminho, params) {
  const body = new URLSearchParams(params || {});
  const r = await fetch(urlApi(caminho), {
    method: 'POST',
    headers: cabecalhosAuth({ 'Content-Type': 'application/x-www-form-urlencoded' }),
    body: body
  });
  return r.json();
}

async function cmd(caminho) {
  const campo = document.getElementById('texto');
  const t = campo ? campo.value.trim() : '';
  if (!t) {
    log('Digite um comando ou anotacao antes de enviar.');
    return;
  }
  log('Enviando...');
  try {
    const resp = await post(caminho, { texto: t });
    log(resp);
  } catch (err) {
    log('Sem conexao com o servidor do Nextor. Confira se o servico esta aberto na rede local ou VPN.');
  }
}

async function go(caminho) {
  log('Consultando...');
  try {
    const resp = await post(caminho, {});
    log(resp);
  } catch (err) {
    log('Sem conexao com o servidor do Nextor.');
  }
}

async function addAuto() {
  const hora = document.getElementById('hora')?.value || '';
  const acao = document.getElementById('acao')?.value || 'rotina';
  const texto = document.getElementById('atexto')?.value || '';
  try {
    await post('/automacoes', { hora: hora, acao: acao, texto: texto });
    await carregar();
  } catch (err) {
    log('Nao foi possivel salvar a automacao.');
  }
}

async function del(id) {
  try {
    await fetch(urlApi('/automacoes?id=' + encodeURIComponent(id)), {
      method: 'DELETE',
      headers: cabecalhosAuth()
    });
    await carregar();
  } catch (err) {
    log('Nao foi possivel remover a automacao.');
  }
}

async function carregar() {
  const container = document.getElementById('autos');
  if (!container) return;
  if (!tk) {
    container.innerHTML = '<p class="help-text">Informe o token de acesso em Conexao para carregar as automacoes.</p>';
    return;
  }
  try {
    const r = await fetch(urlApi('/automacoes'), { headers: cabecalhosAuth() });
    if (!r.ok) {
      container.innerHTML = '<p class="help-text">Token invalido ou ausente. Revise os dados de conexao abaixo.</p>';
      return;
    }
    const d = await r.json();
    const lista = d.automacoes || [];
    if (lista.length === 0) {
      container.innerHTML = '<p class="help-text">Nenhuma automacao cadastrada.</p>';
      return;
    }
    container.innerHTML = lista
      .map(
        (a) =>
          `<div class="auto-item"><span><strong>${a.hora}</strong> - ${a.acao} ${a.texto || ''}</span><button class="btn-secondary" onclick="del('${a.id}')">Remover</button></div>`
      )
      .join('');
  } catch (err) {
    container.innerHTML = '<p class="help-text">Shell carregado offline. Sem conexao com o servico no momento.</p>';
  }
}

function salvarConexao() {
  const inputToken = document.getElementById('token-input');
  const inputServidor = document.getElementById('servidor-url');
  if (inputToken) {
    tk = inputToken.value.trim();
    try {
      localStorage.setItem(CHAVE_TOKEN, tk);
      localStorage.setItem(CHAVE_TOKEN_GTD, tk);
    } catch (e) {}
  }
  if (inputServidor) {
    const srv = inputServidor.value.trim().replace(/\/+$/, '');
    try {
      localStorage.setItem(CHAVE_SERVIDOR, srv);
    } catch (e) {}
  }
  log('Configuracao de conexao salva neste aparelho.');
  carregar();
}

function registrarServiceWorkerUniversal() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
  }
}

function configurarInstalacaoPwa() {
  const banner = document.getElementById('banner-instalar');
  const btnInstalar = document.getElementById('btn-instalar-pwa');

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    promptInstalacao = e;
    if (banner) banner.hidden = false;
  });

  if (btnInstalar) {
    btnInstalar.addEventListener('click', async () => {
      if (!promptInstalacao) {
        window.location.href = '/download';
        return;
      }
      promptInstalacao.prompt();
      await promptInstalacao.userChoice;
      promptInstalacao = null;
      if (banner) banner.hidden = true;
    });
  }

  window.addEventListener('appinstalled', () => {
    promptInstalacao = null;
    if (banner) banner.hidden = true;
    log('Aplicativo Nextor instalado neste dispositivo.');
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const inputToken = document.getElementById('token-input');
  if (inputToken) inputToken.value = tk;

  const inputServidor = document.getElementById('servidor-url');
  if (inputServidor) inputServidor.value = obterServidorBase();

  const btnSalvarConexao = document.getElementById('btn-salvar-conexao');
  if (btnSalvarConexao) {
    btnSalvarConexao.addEventListener('click', salvarConexao);
  }

  window.addEventListener('online', atualizarStatusRede);
  window.addEventListener('offline', atualizarStatusRede);

  atualizarStatusRede();
  registrarServiceWorkerUniversal();
  configurarInstalacaoPwa();
  carregar();
});
