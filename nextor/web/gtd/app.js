/**
 * Nextor GTD - Aplicacao PWA para celular (Issues #42, #43, #44)
 * Sem emojis, navegacao inferior pensada para o polegar, autenticacao via headers.
 */

// Estado da Aplicacao
const estado = {
  token: '',
  abaAtiva: 'aba-inbox',
  contextoSelecionado: '@qualquer',
  itemSendoProcessado: null,
  dadosHoje: null,
  tema: 'escuro'
};

// Inicializacao
document.addEventListener('DOMContentLoaded', () => {
  carregarToken();
  carregarTema();
  configurarEventosNavegacao();
  configurarEventosAcoes();
  registrarServiceWorker();

  if (estado.token) {
    carregarAbaAtual();
  } else {
    abrirModalConfig();
  }
});

// Autenticacao e Token
function carregarToken() {
  // Le fragmento #token= se presente (ex: apos pareamento)
  if (window.location.hash.startsWith('#token=')) {
    const tk = window.location.hash.substring(7).trim();
    if (tk) {
      localStorage.setItem('nextor_gtd_token', tk);
      history.replaceState(null, '', window.location.pathname);
    }
  }
  estado.token = localStorage.getItem('nextor_gtd_token') || '';
}

function salvarToken(novoToken) {
  estado.token = (novoToken || '').trim();
  localStorage.setItem('nextor_gtd_token', estado.token);
  mostrarToast('Configuracoes salvas');
  carregarAbaAtual();
}

// Requisicoes com Cabecalho
async function api(caminho, metodo = 'GET', dados = null) {
  if (!estado.token) {
    abrirModalConfig();
    throw new Error('Token ausente');
  }

  const opcoes = {
    method: metodo,
    headers: {
      'Content-Type': 'application/json',
      'X-Nextor-Token': estado.token
    }
  };

  if (dados && (metodo === 'POST' || metodo === 'PUT' || metodo === 'PATCH')) {
    opcoes.body = JSON.stringify(dados);
  }

  try {
    const res = await fetch(caminho, opcoes);
    if (res.status === 401 || res.status === 403) {
      mostrarToast('Token invalido ou expirado');
      abrirModalConfig();
      throw new Error('Nao autorizado');
    }
    const json = await res.json();
    return json;
  } catch (err) {
    if (err.message !== 'Nao autorizado') {
      mostrarToast('Erro de conexao com o servidor');
    }
    throw err;
  }
}

// Service Worker
function registrarServiceWorker() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/gtd/sw.js').catch(() => {});
  }
}

// Tema Claro / Escuro
function carregarTema() {
  const salvo = localStorage.getItem('nextor_gtd_tema');
  if (salvo) {
    estado.tema = salvo;
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    estado.tema = 'claro';
  } else {
    estado.tema = 'escuro';
  }
  document.documentElement.setAttribute('data-tema', estado.tema);
}

function alternarTema() {
  estado.tema = estado.tema === 'claro' ? 'escuro' : 'claro';
  document.documentElement.setAttribute('data-tema', estado.tema);
  localStorage.setItem('nextor_gtd_tema', estado.tema);
}

// Navegacao
function configurarEventosNavegacao() {
  document.querySelectorAll('.nav-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const alvo = tab.getAttribute('data-alvo');
      mudarAba(alvo);
    });
  });

  document.querySelectorAll('#filtro-contextos .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('#filtro-contextos .chip').forEach(c => c.classList.remove('ativo'));
      chip.classList.add('ativo');
      estado.contextoSelecionado = chip.getAttribute('data-ctx');
      carregarContextos();
    });
  });
}

function mudarAba(idAba) {
  estado.abaAtiva = idAba;
  document.querySelectorAll('.tela-secao').forEach(sec => sec.classList.remove('ativa'));
  document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('ativa'));

  const secAlvo = document.getElementById(idAba);
  const tabAlvo = document.querySelector(`.nav-tab[data-alvo="${idAba}"]`);
  if (secAlvo) secAlvo.classList.add('ativa');
  if (tabAlvo) tabAlvo.classList.add('ativa');

  carregarAbaAtual();
}

function carregarAbaAtual() {
  switch (estado.abaAtiva) {
    case 'aba-inbox':
      carregarInbox();
      break;
    case 'aba-hoje':
      carregarHoje();
      break;
    case 'aba-contextos':
      carregarContextos();
      break;
    case 'aba-projetos':
      carregarProjetos();
      break;
    case 'aba-leitura':
      carregarLeituras();
      break;
  }
}

// Configuracao de Botoes e Acoes
function configurarEventosAcoes() {
  // Topo
  document.getElementById('btn-tema').addEventListener('click', alternarTema);
  document.getElementById('btn-config').addEventListener('click', abrirModalConfig);
  document.getElementById('btn-sync').addEventListener('click', dispararSincronizacao);

  // Modal Config
  document.getElementById('btn-fechar-config').addEventListener('click', fecharModalConfig);
  document.getElementById('btn-salvar-config').addEventListener('click', () => {
    const val = document.getElementById('input-token-mestre').value;
    salvarToken(val);
    fecharModalConfig();
  });

  // Modal Processar
  document.getElementById('btn-fechar-modal').addEventListener('click', fecharModalProcessar);
  document.querySelectorAll('.btn-acao-modal').forEach((btn) => {
    btn.addEventListener('click', () => {
      const destino = btn.getAttribute('data-destino');
      tratarEscolhaProcessamento(destino);
    });
  });
  document.getElementById('btn-confirmar-processar').addEventListener('click', confirmarAcaoComAjustes);

  // Captura no Inbox
  document.getElementById('btn-capturar').addEventListener('click', executarCaptura);

  // Criar Projeto
  document.getElementById('btn-criar-projeto').addEventListener('click', executarCriarProjeto);

  // Criar Leitura
  document.getElementById('btn-adicionar-leitura').addEventListener('click', executarAdicionarLeitura);

  // Somar Leitura no Hoje
  document.getElementById('btn-somar-leitura').addEventListener('click', executarSomarLeituraHoje);
}

// -------------------------------------------------------------
// Tela 1: Inbox
// -------------------------------------------------------------
async function carregarInbox() {
  try {
    const res = await api('/gtd/itens?estado=inbox');
    const itens = res.itens || [];
    document.getElementById('badge-inbox-total').textContent = itens.length;

    const lista = document.getElementById('lista-inbox');
    lista.innerHTML = '';

    if (itens.length === 0) {
      lista.innerHTML = '<p class="ajuda-texto">Caixa de entrada limpa. Nada para processar agora.</p>';
      return;
    }

    itens.forEach((it) => {
      const card = document.createElement('div');
      card.className = 'item-card';
      card.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(it.titulo)}</div>
          <div class="item-meta">
            <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
            ${it.nota ? `<span>${escaparHtml(it.nota)}</span>` : ''}
          </div>
        </div>
        <div class="item-botoes">
          <button class="btn-secundario btn-processar" data-id="${it.id}">Esclarecer</button>
        </div>
      `;
      card.querySelector('.btn-processar').addEventListener('click', () => abrirModalProcessar(it));
      lista.appendChild(card);
    });
  } catch (err) {}
}

async function executarCaptura() {
  const input = document.getElementById('input-captura');
  const selectCtx = document.getElementById('select-contexto-captura');
  const texto = input.value.trim();
  if (!texto) {
    mostrarToast('Digite algo para capturar');
    return;
  }

  try {
    await api('/gtd/capturar', 'POST', {
      titulo: texto,
      contexto: selectCtx.value
    });
    input.value = '';
    mostrarToast('Capturado no Inbox');
    carregarInbox();
  } catch (err) {}
}

// -------------------------------------------------------------
// Tela 2: Hoje
// -------------------------------------------------------------
async function carregarHoje() {
  try {
    const res = await api('/gtd/hoje');
    estado.dadosHoje = res;

    // Resumo Falado
    document.getElementById('texto-resumo-dia').textContent = res.resumo_falado || 'Dia carregado.';

    // Meta Leitura
    const leit = res.leitura || {};
    const lidas = leit.paginas_lidas_hoje || 0;
    const meta = leit.meta_diaria || 20;
    const pct = Math.min(100, Math.round((lidas / meta) * 100));
    document.getElementById('progresso-leitura-texto').textContent = `${lidas} / ${meta} pag`;
    document.getElementById('barra-leitura-progresso').style.width = `${pct}%`;

    // Compromissos da Agenda
    const listaAgenda = document.getElementById('lista-agenda');
    listaAgenda.innerHTML = '';
    const eventos = res.eventos_agenda || [];
    if (eventos.length === 0) {
      listaAgenda.innerHTML = '<p class="ajuda-texto">Nenhum compromisso marcado para hoje.</p>';
    } else {
      eventos.forEach((ev) => {
        const div = document.createElement('div');
        div.className = 'item-card';
        div.innerHTML = `
          <div class="item-info">
            <div class="item-titulo">${escaparHtml(ev.titulo)}</div>
            <div class="item-meta">
              <span class="tag-prazo">${escaparHtml(ev.horario)}</span>
            </div>
          </div>
        `;
        listaAgenda.appendChild(div);
      });
    }

    // Proximas Acoes
    const listaAcoes = document.getElementById('lista-hoje-acoes');
    listaAcoes.innerHTML = '';
    const acoes = res.proximas_acoes || [];
    if (acoes.length === 0) {
      listaAcoes.innerHTML = '<p class="ajuda-texto">Nenhuma proxima acao pendente.</p>';
    } else {
      acoes.forEach((ac) => {
        const div = document.createElement('div');
        div.className = 'item-card';
        div.innerHTML = `
          <div class="item-info">
            <div class="item-titulo">${escaparHtml(ac.titulo)}</div>
            <div class="item-meta">
              <span class="tag-contexto">${escaparHtml(ac.contexto)}</span>
              ${ac.prazo ? `<span class="tag-prazo">Prazo: ${ac.prazo}</span>` : ''}
            </div>
          </div>
          <div class="item-botoes">
            <button class="btn-secundario btn-concluir" data-id="${ac.id}">Feito</button>
          </div>
        `;
        div.querySelector('.btn-concluir').addEventListener('click', () => concluirItem(ac.id));
        listaAcoes.appendChild(div);
      });
    }
  } catch (err) {}
}

async function concluirItem(id) {
  try {
    await api('/gtd/processar', 'POST', {
      item_id: id,
      novo_estado: 'feito'
    });
    mostrarToast('Acao concluida');
    carregarHoje();
  } catch (err) {}
}

async function executarSomarLeituraHoje() {
  const input = document.getElementById('input-paginas-hoje');
  const paginas = parseInt(input.value, 10);
  if (!paginas || paginas <= 0) {
    mostrarToast('Informe o numero de paginas lidas');
    return;
  }

  try {
    const leiturasRes = await api('/gtd/leituras?estado=lendo');
    const leituras = leiturasRes.leituras || [];
    if (leituras.length > 0) {
      await api(`/gtd/leituras/${leituras[0].id}/progresso`, 'POST', { paginas });
    } else {
      // Se nao ha livro especifico lendo, busca quero_ler ou registra em geral
      const qlRes = await api('/gtd/leituras?estado=quero_ler');
      const ql = qlRes.leituras || [];
      if (ql.length > 0) {
        await api(`/gtd/leituras/${ql[0].id}/progresso`, 'POST', { paginas });
      } else {
        const nova = await api('/gtd/leituras', 'POST', { titulo: 'Leitura Geral', estado: 'lendo' });
        await api(`/gtd/leituras/${nova.leitura.id}/progresso`, 'POST', { paginas });
      }
    }
    input.value = '';
    mostrarToast(`Registradas ${paginas} paginas`);
    carregarHoje();
  } catch (err) {}
}

// -------------------------------------------------------------
// Tela 3: Contextos
// -------------------------------------------------------------
async function carregarContextos() {
  try {
    let url = '/gtd/itens?estado=proxima';
    if (estado.contextoSelecionado && estado.contextoSelecionado !== '@qualquer') {
      url += `&contexto=${encodeURIComponent(estado.contextoSelecionado)}`;
    }
    const res = await api(url);
    const itens = res.itens || [];

    const lista = document.getElementById('lista-contextos');
    lista.innerHTML = '';
    if (itens.length === 0) {
      lista.innerHTML = `<p class="ajuda-texto">Nenhuma acao pendente em ${estado.contextoSelecionado}.</p>`;
      return;
    }

    itens.forEach((it) => {
      const div = document.createElement('div');
      div.className = 'item-card';
      div.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(it.titulo)}</div>
          <div class="item-meta">
            <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
            ${it.prazo ? `<span class="tag-prazo">Prazo: ${it.prazo}</span>` : ''}
            ${it.nota ? `<span>${escaparHtml(it.nota)}</span>` : ''}
          </div>
        </div>
        <div class="item-botoes">
          <button class="btn-secundario btn-concluir" data-id="${it.id}">Feito</button>
        </div>
      `;
      div.querySelector('.btn-concluir').addEventListener('click', async () => {
        await concluirItem(it.id);
        carregarContextos();
      });
      lista.appendChild(div);
    });
  } catch (err) {}
}

// -------------------------------------------------------------
// Tela 4: Projetos
// -------------------------------------------------------------
async function carregarProjetos() {
  try {
    const res = await api('/gtd/projetos?estado=ativo');
    const projetos = res.projetos || [];
    document.getElementById('badge-projetos-total').textContent = projetos.length;

    const lista = document.getElementById('lista-projetos');
    lista.innerHTML = '';
    if (projetos.length === 0) {
      lista.innerHTML = '<p class="ajuda-texto">Nenhum projeto ativo cadastrado.</p>';
      return;
    }

    projetos.forEach((proj) => {
      const div = document.createElement('div');
      div.className = 'item-card';
      div.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(proj.nome)}</div>
          <div class="item-meta">
            ${proj.descricao ? `<span>${escaparHtml(proj.descricao)}</span>` : ''}
          </div>
        </div>
      `;
      lista.appendChild(div);
    });
  } catch (err) {}
}

async function executarCriarProjeto() {
  const nomeInput = document.getElementById('input-novo-projeto');
  const descInput = document.getElementById('input-desc-projeto');
  const nome = nomeInput.value.trim();
  if (!nome) {
    mostrarToast('Digite o nome do projeto');
    return;
  }

  try {
    await api('/gtd/projetos', 'POST', {
      nome: nome,
      descricao: descInput.value.trim()
    });
    nomeInput.value = '';
    descInput.value = '';
    mostrarToast('Projeto criado');
    carregarProjetos();
  } catch (err) {}
}

// -------------------------------------------------------------
// Tela 5: Leitura
// -------------------------------------------------------------
async function carregarLeituras() {
  try {
    const res = await api('/gtd/leituras');
    const leituras = res.leituras || [];

    const lista = document.getElementById('lista-leituras');
    lista.innerHTML = '';
    if (leituras.length === 0) {
      lista.innerHTML = '<p class="ajuda-texto">Fila de leitura vazia.</p>';
      return;
    }

    leituras.forEach((l) => {
      const div = document.createElement('div');
      div.className = 'item-card';
      const pct = l.paginas_total > 0 ? Math.round((l.paginas_lidas / l.paginas_total) * 100) : 0;
      div.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(l.titulo)}</div>
          <div class="item-meta">
            <span class="tag-contexto">${escaparHtml(l.tipo)}</span>
            <span>${escaparHtml(l.estado)}</span>
            <span>${l.paginas_lidas} / ${l.paginas_total || '?'} pag (${pct}%)</span>
            ${l.autor ? `<span>por ${escaparHtml(l.autor)}</span>` : ''}
          </div>
        </div>
        <div class="item-botoes">
          <button class="btn-secundario btn-add-pag" data-id="${l.id}">+ Lidas</button>
        </div>
      `;
      div.querySelector('.btn-add-pag').addEventListener('click', () => registrarPaginasItem(l.id));
      lista.appendChild(div);
    });
  } catch (err) {}
}

async function registrarPaginasItem(id) {
  const pagStr = prompt('Quantas paginas voce leu agora?');
  if (!pagStr) return;
  const pag = parseInt(pagStr, 10);
  if (!pag || pag <= 0) return;

  try {
    await api(`/gtd/leituras/${id}/progresso`, 'POST', { paginas: pag });
    mostrarToast(`Registradas ${pag} paginas`);
    carregarLeituras();
  } catch (err) {}
}

async function executarAdicionarLeitura() {
  const titInput = document.getElementById('input-titulo-livro');
  const autInput = document.getElementById('input-autor-livro');
  const pagInput = document.getElementById('input-total-paginas');
  const tipoSelect = document.getElementById('select-tipo-leitura');

  const titulo = titInput.value.trim();
  if (!titulo) {
    mostrarToast('Informe o titulo');
    return;
  }

  try {
    await api('/gtd/leituras', 'POST', {
      titulo: titulo,
      autor: autInput.value.trim(),
      paginas_total: parseInt(pagInput.value, 10) || 0,
      tipo: tipoSelect.value,
      estado: 'quero_ler'
    });
    titInput.value = '';
    autInput.value = '';
    pagInput.value = '';
    mostrarToast('Adicionado a fila de leitura');
    carregarLeituras();
  } catch (err) {}
}

// -------------------------------------------------------------
// Sincronizacao
// -------------------------------------------------------------
async function dispararSincronizacao() {
  mostrarToast('Sincronizando...');
  try {
    const res = await api('/gtd/sincronizar', 'POST');
    mostrarToast('Sincronizacao concluida');
    carregarAbaAtual();
  } catch (err) {}
}

// -------------------------------------------------------------
// Modal de Processamento
// -------------------------------------------------------------
function abrirModalProcessar(item) {
  estado.itemSendoProcessado = item;
  document.getElementById('modal-item-titulo').textContent = item.titulo;
  document.getElementById('form-ajuste-acao').classList.add('oculto');
  document.getElementById('modal-processar').classList.remove('oculto');
}

function fecharModalProcessar() {
  estado.itemSendoProcessado = null;
  document.getElementById('modal-processar').classList.add('oculto');
}

async function tratarEscolhaProcessamento(destino) {
  if (!estado.itemSendoProcessado) return;
  const id = estado.itemSendoProcessado.id;

  if (destino === 'proxima') {
    // Abre formulário para definir contexto e prazo da proxima acao
    document.getElementById('form-ajuste-acao').classList.remove('oculto');
    return;
  }

  try {
    await api('/gtd/processar', 'POST', {
      item_id: id,
      novo_estado: destino
    });
    fecharModalProcessar();
    mostrarToast(`Item movido para ${destino}`);
    carregarInbox();
  } catch (err) {}
}

async function confirmarAcaoComAjustes() {
  if (!estado.itemSendoProcessado) return;
  const id = estado.itemSendoProcessado.id;
  const ctx = document.getElementById('modal-select-contexto').value;
  const prazo = document.getElementById('modal-input-prazo').value;

  try {
    await api('/gtd/processar', 'POST', {
      item_id: id,
      novo_estado: 'proxima',
      novo_contexto: ctx,
      prazo: prazo || null
    });
    fecharModalProcessar();
    mostrarToast('Movido para Proximas Acoes');
    carregarInbox();
  } catch (err) {}
}

// -------------------------------------------------------------
// Modal de Configuracao
// -------------------------------------------------------------
function abrirModalConfig() {
  document.getElementById('input-token-mestre').value = estado.token;
  document.getElementById('modal-config').classList.remove('oculto');
}

function fecharModalConfig() {
  document.getElementById('modal-config').classList.add('oculto');
}

// -------------------------------------------------------------
// Utilitarios
// -------------------------------------------------------------
function mostrarToast(mensagem) {
  const toast = document.getElementById('toast');
  toast.textContent = mensagem;
  toast.classList.remove('oculto');
  setTimeout(() => {
    toast.classList.add('oculto');
  }, 2400);
}

function escaparHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
