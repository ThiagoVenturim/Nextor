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

function escaparHtml(valor) {
  return String(valor == null ? '' : valor)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

async function carregarDispositivos() {
  const container = document.getElementById('disp-lista');
  if (!container) return;
  if (!tk) {
    container.innerHTML = '<p class="help-text">Informe o token mestre em Conexao para gerenciar dispositivos.</p>';
    return;
  }
  try {
    const r = await fetch(urlApi('/v1/dispositivos'), { headers: cabecalhosAuth() });
    if (!r.ok) {
      container.innerHTML = '<p class="help-text">Sem acesso a lista de dispositivos com este token.</p>';
      return;
    }
    const d = await r.json();
    const lista = d.dispositivos || [];
    if (lista.length === 0) {
      container.innerHTML = '<p class="help-text">Nenhum dispositivo cadastrado.</p>';
      return;
    }
    container.innerHTML = lista
      .map((item) => {
        const id = escaparHtml(item.id);
        const situacao = item.ativo ? (item.presenca && item.presenca.online ? 'online' : 'ativo') : 'revogado';
        const acao = item.ativo
          ? `<button class="btn-secondary" data-disp-acao="revogar" data-disp-id="${id}">Revogar</button>`
          : `<button class="btn-secondary" data-disp-acao="ativar" data-disp-id="${id}">Reativar</button>`;
        return `<div class="auto-item"><span><strong>${escaparHtml(item.nome)}</strong> - ${escaparHtml(item.tipo)} (${situacao})</span>${acao}</div>`;
      })
      .join('');
  } catch (err) {
    container.innerHTML = '<p class="help-text">Sem conexao com o servico no momento.</p>';
  }
}

async function cadastrarDispositivo() {
  const id = (document.getElementById('disp-id')?.value || '').trim();
  const nome = (document.getElementById('disp-nome')?.value || '').trim();
  const tipo = document.getElementById('disp-tipo')?.value || 'celular';
  const caixa = document.getElementById('disp-pareamento');
  if (!id) {
    log('Informe o identificador do dispositivo.');
    return;
  }
  try {
    const r = await fetch(urlApi('/v1/dispositivos'), {
      method: 'POST',
      headers: cabecalhosAuth({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ id: id, nome: nome, tipo: tipo })
    });
    const d = await r.json();
    if (!r.ok || !d.ok) {
      log(d.erro || 'Nao foi possivel cadastrar o dispositivo.');
      return;
    }
    if (caixa) {
      const link = escaparHtml(d.url_pareamento);
      const qr = d.qr_svg ? `<div class="qr-pareamento">${d.qr_svg}</div>` : '';
      caixa.innerHTML = `${qr}<p class="help-text">Leia o QR code no aparelho ou abra o link nele: <a href="${link}">pareamento</a>. O token nao sera mostrado de novo.</p>`;
      caixa.hidden = false;
    }
    log('Dispositivo cadastrado: ' + d.dispositivo.nome);
    await carregarDispositivos();
  } catch (err) {
    log('Sem conexao com o servidor do Nextor.');
  }
}

async function alterarDispositivo(acao, id) {
  try {
    const r = await fetch(urlApi('/v1/dispositivos/' + encodeURIComponent(id) + '/' + acao), {
      method: 'POST',
      headers: cabecalhosAuth()
    });
    const d = await r.json();
    log(d.ok ? 'Dispositivo ' + (acao === 'revogar' ? 'revogado' : 'reativado') + '.' : d.erro || 'Falha.');
    const caixa = document.getElementById('disp-pareamento');
    if (caixa) {
      caixa.hidden = true;
      caixa.innerHTML = '';
    }
    await carregarDispositivos();
  } catch (err) {
    log('Sem conexao com o servidor do Nextor.');
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
  carregarDispositivos();
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

  const btnCadastrarDisp = document.getElementById('btn-cadastrar-dispositivo');
  if (btnCadastrarDisp) {
    btnCadastrarDisp.addEventListener('click', cadastrarDispositivo);
  }
  const listaDisp = document.getElementById('disp-lista');
  if (listaDisp) {
    listaDisp.addEventListener('click', (ev) => {
      const alvo = ev.target.closest('[data-disp-acao]');
      if (alvo) alterarDispositivo(alvo.getAttribute('data-disp-acao'), alvo.getAttribute('data-disp-id'));
    });
  }

  window.addEventListener('online', atualizarStatusRede);
  window.addEventListener('offline', atualizarStatusRede);

  atualizarStatusRede();
  registrarServiceWorkerUniversal();
  configurarInstalacaoPwa();
  carregar();
  carregarDispositivos();
});
