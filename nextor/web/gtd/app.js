/**
 * Nextor GTD & Framework de Produtividade (Issues #42, #43, #44, #45, #46, #47)
 * Sem emojis, navegacao pelo polegar, metodos intercambiaveis, notificacoes e configuracao completa.
 */

// Estado Central
const estado = {
  token: '',
  abaAtiva: 'aba-inbox',
  metodoAtivo: 'gtd',
  contextoSelecionado: '@qualquer',
  itemSendoProcessado: null,
  dadosHoje: null,
  tema: 'escuro',
  paleta: 'azul',
  configCompleta: null,
  pomodoroTimer: null,
  passoWizard: 1
};

// Inicializacao
document.addEventListener('DOMContentLoaded', () => {
  carregarToken();
  carregarTemaEPaleta();
  configurarEventosNavegacao();
  configurarEventosAcoes();
  configurarEventosPomodoro();
  configurarEventosWizard();
  registrarServiceWorker();

  if (estado.token) {
    inicializarApp();
  } else {
    mudarAba('aba-config');
  }
});

// Autenticacao
function carregarToken() {
  if (window.location.hash.startsWith('#token=')) {
    const tk = window.location.hash.substring(7).trim();
    if (tk) {
      localStorage.setItem('nextor_gtd_token', tk);
      history.replaceState(null, '', window.location.pathname);
    }
  }
  estado.token = localStorage.getItem('nextor_gtd_token') || '';
  const inputTk = document.getElementById('input-token-mestre');
  if (inputTk) inputTk.value = estado.token;
}

function salvarToken(novoToken) {
  estado.token = (novoToken || '').trim();
  localStorage.setItem('nextor_gtd_token', estado.token);
  mostrarToast('Token salvo com sucesso');
  inicializarApp();
}

async function inicializarApp() {
  await carregarConfiguracoesServidor();
  await sincronizarEstadoPomodoro();
  carregarAbaAtual();
}

// Requisicoes com Cabecalho Seguro
async function api(caminho, metodo = 'GET', dados = null) {
  if (!estado.token) {
    mudarAba('aba-config');
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
      mostrarToast('Token invalido ou ausente no header');
      mudarAba('aba-config');
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

// Temas e Paletas (#46)
function carregarTemaEPaleta() {
  estado.tema = localStorage.getItem('nextor_gtd_tema') || 'escuro';
  estado.paleta = localStorage.getItem('nextor_gtd_paleta') || 'azul';
  aplicarTemaEPaleta();
}

function aplicarTemaEPaleta() {
  document.documentElement.setAttribute('data-tema', estado.tema);
  document.documentElement.setAttribute('data-paleta', estado.paleta);
  localStorage.setItem('nextor_gtd_tema', estado.tema);
  localStorage.setItem('nextor_gtd_paleta', estado.paleta);

  // Atualiza controles na tela de ajustes se existirem
  const selTema = document.getElementById('config-select-tema');
  if (selTema) selTema.value = estado.tema;

  document.querySelectorAll('.btn-paleta').forEach((btn) => {
    btn.classList.toggle('ativa', btn.getAttribute('data-paleta') === estado.paleta);
  });
}

function alternarTema() {
  estado.tema = estado.tema === 'claro' ? 'escuro' : 'claro';
  aplicarTemaEPaleta();
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

  // Seletor de Metodo na aba Visao (#45)
  document.querySelectorAll('#seletor-metodos .tab-metodo').forEach((tab) => {
    tab.addEventListener('click', async () => {
      const slug = tab.getAttribute('data-metodo');
      await trocarMetodoAtivo(slug);
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
      carregarVisaoMetodo();
      break;
    case 'aba-contextos':
      carregarContextos();
      break;
    case 'aba-leitura':
      carregarLeituras();
      break;
    case 'aba-config':
      preencherTelaConfig();
      break;
  }
}

// Botoes e Acoes
function configurarEventosAcoes() {
  document.getElementById('btn-tema').addEventListener('click', alternarTema);
  document.getElementById('btn-sync').addEventListener('click', dispararSincronizacao);

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

  // Criar Leitura
  document.getElementById('btn-adicionar-leitura').addEventListener('click', executarAdicionarLeitura);

  // Somar Leitura no Hoje
  document.getElementById('btn-somar-leitura').addEventListener('click', executarSomarLeituraHoje);

  // Tela de Ajustes (#47)
  document.getElementById('config-select-tema').addEventListener('change', (e) => {
    estado.tema = e.target.value;
    aplicarTemaEPaleta();
  });

  document.querySelectorAll('.btn-paleta').forEach((btn) => {
    btn.addEventListener('click', () => {
      estado.paleta = btn.getAttribute('data-paleta');
      aplicarTemaEPaleta();
    });
  });

  document.getElementById('btn-salvar-tudo-config').addEventListener('click', salvarConfiguracoesTela);
  document.getElementById('btn-disparar-teste-notificacao').addEventListener('click', dispararTesteNotificacao);
  document.getElementById('btn-abrir-wizard').addEventListener('click', abrirWizard);
}

// -------------------------------------------------------------
// Configuracoes do Servidor (#47)
// -------------------------------------------------------------
async function carregarConfiguracoesServidor() {
  try {
    const res = await api('/gtd/config');
    estado.configCompleta = res;
    const cfg = res.config || {};
    estado.metodoAtivo = cfg.metodo_ativo || 'gtd';
    if (cfg.tema) estado.tema = cfg.tema;
    if (cfg.paleta) estado.paleta = cfg.paleta;
    aplicarTemaEPaleta();

    // Atualiza tabs do metodo
    document.querySelectorAll('#seletor-metodos .tab-metodo').forEach((tab) => {
      tab.classList.toggle('ativa', tab.getAttribute('data-metodo') === estado.metodoAtivo);
    });

    // Se primeira vez, abre wizard automaticamente
    if (cfg.wizard_concluido === false) {
      abrirWizard();
    }
  } catch (err) {}
}

function preencherTelaConfig() {
  if (!estado.configCompleta) return;
  const cfg = estado.configCompleta.config || {};

  document.getElementById('config-select-metodo').value = cfg.metodo_ativo || 'gtd';
  document.getElementById('config-wip-limite').value = cfg.kanban_wip_limite || 3;

  const sil = cfg.horario_silencio || {};
  document.getElementById('config-silencio-ativo').checked = sil.ativo !== false;
  document.getElementById('config-silencio-inicio').value = sil.inicio || '22:00';
  document.getElementById('config-silencio-fim').value = sil.fim || '07:00';

  // Lista canais de notificacao com badges
  const listaCanais = document.getElementById('lista-canais-config');
  listaCanais.innerHTML = '';
  const canais = estado.configCompleta.canais || [];
  const ativos = new Set(cfg.canais_ativos || []);

  canais.forEach((cn) => {
    const div = document.createElement('div');
    div.className = 'linha-config';
    const marcado = ativos.has(cn.slug);
    div.innerHTML = `
      <div>
        <strong>${escaparHtml(cn.nome)}</strong>
        <span class="badge ${cn.configurado ? '' : 'alerta'}">${cn.configurado ? 'Pronto' : 'Variaveis .env ausentes'}</span>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" class="chk-canal" data-slug="${cn.slug}" ${marcado ? 'checked' : ''}>
        <span class="toggle-slider"></span>
      </label>
    `;
    listaCanais.appendChild(div);
  });

  // Lista integracoes
  const listaInt = document.getElementById('lista-integracoes-config');
  listaInt.innerHTML = '';
  const integracoes = estado.configCompleta.integracoes || {};
  Object.keys(integracoes).forEach((chave) => {
    const itemInt = integracoes[chave];
    const div = document.createElement('div');
    div.className = 'linha-config';
    div.innerHTML = `
      <div>
        <strong>${escaparHtml(chave.toUpperCase())}</strong>
        <p class="linha-config-descricao">${escaparHtml(itemInt.descricao || '')}</p>
        <span class="badge ${itemInt.configurado ? '' : 'alerta'}">${itemInt.configurado ? 'Configurado' : 'Pendente de credencial'}</span>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" class="chk-integracao" data-chave="${chave}" ${itemInt.ativo ? 'checked' : ''}>
        <span class="toggle-slider"></span>
      </label>
    `;
    listaInt.appendChild(div);
  });

  // Lista agentes
  const listaAgentes = document.getElementById('lista-agentes-config');
  listaAgentes.innerHTML = '';
  const agentes = estado.configCompleta.agentes || [];
  agentes.forEach((ag) => {
    const div = document.createElement('div');
    div.className = 'linha-config';
    div.innerHTML = `
      <div>
        <strong>${escaparHtml(ag.nome)}</strong>
        <p class="linha-config-descricao">${escaparHtml(ag.descricao)}</p>
      </div>
      <label class="toggle-switch">
        <input type="checkbox" class="chk-agente" data-id="${ag.id}" ${ag.ativo ? 'checked' : ''}>
        <span class="toggle-slider"></span>
      </label>
    `;
    listaAgentes.appendChild(div);
  });
}

async function salvarConfiguracoesTela() {
  const novoTk = document.getElementById('input-token-mestre').value.trim();
  if (novoTk && novoTk !== estado.token) {
    salvarToken(novoTk);
  }

  const metodo = document.getElementById('config-select-metodo').value;
  const wip = parseInt(document.getElementById('config-wip-limite').value, 10) || 3;
  const silAtivo = document.getElementById('config-silencio-ativo').checked;
  const silInicio = document.getElementById('config-silencio-inicio').value;
  const silFim = document.getElementById('config-silencio-fim').value;

  const canaisAtivos = [];
  document.querySelectorAll('.chk-canal:checked').forEach((chk) => {
    canaisAtivos.push(chk.getAttribute('data-slug'));
  });

  const integracoes = {};
  document.querySelectorAll('.chk-integracao').forEach((chk) => {
    integracoes[chk.getAttribute('data-chave')] = chk.checked;
  });

  const agentes = {};
  document.querySelectorAll('.chk-agente').forEach((chk) => {
    agentes[chk.getAttribute('data-id')] = chk.checked;
  });

  const payload = {
    metodo_ativo: metodo,
    tema: estado.tema,
    paleta: estado.paleta,
    kanban_wip_limite: wip,
    horario_silencio: {
      ativo: silAtivo,
      inicio: silInicio,
      fim: silFim
    },
    canais_ativos: canaisAtivos,
    integracoes: integracoes,
    agentes: agentes
  };

  try {
    await api('/gtd/config', 'PUT', payload);
    estado.metodoAtivo = metodo;
    mostrarToast('Configuracoes salvas');
    await carregarConfiguracoesServidor();
  } catch (err) {}
}

async function dispararTesteNotificacao() {
  try {
    mostrarToast('Enviando notificacao de teste...');
    const res = await api('/gtd/notificacoes/teste', 'POST', {
      titulo: 'Nextor GTD',
      corpo: 'Notificacao de teste enviada com sucesso pelos canais ativos.'
    });
    if (res.silenciado) {
      mostrarToast('Notificacao silenciada pelo horario de silencio');
    } else if (res.despachados && res.despachados.length > 0) {
      mostrarToast(`Enviada para: ${res.despachados.join(', ')}`);
    } else {
      mostrarToast('Nenhum canal ativo ou configurado para envio');
    }
  } catch (err) {}
}

// -------------------------------------------------------------
// Metodos Intercambiaveis (#45)
// -------------------------------------------------------------
async function trocarMetodoAtivo(slug) {
  estado.metodoAtivo = slug;
  document.querySelectorAll('#seletor-metodos .tab-metodo').forEach((tab) => {
    tab.classList.toggle('ativa', tab.getAttribute('data-metodo') === slug);
  });

  try {
    await api('/gtd/config', 'PUT', { metodo_ativo: slug });
  } catch (err) {}
  carregarVisaoMetodo();
}

async function carregarVisaoMetodo() {
  try {
    // 1. Carrega dados do dia gerais (agenda + meta leitura)
    const hojeRes = await api('/gtd/hoje');
    estado.dadosHoje = hojeRes;
    document.getElementById('texto-resumo-dia').textContent = hojeRes.resumo_falado || 'Dia carregado.';

    // Meta Leitura
    const leit = hojeRes.leitura || {};
    const lidas = leit.paginas_lidas_hoje || 0;
    const meta = leit.meta_diaria || 20;
    const pct = Math.min(100, Math.round((lidas / meta) * 100));
    document.getElementById('progresso-leitura-texto').textContent = `${lidas} / ${meta} pag`;
    document.getElementById('barra-leitura-progresso').style.width = `${pct}%`;

    // Compromissos da Agenda
    const listaAgenda = document.getElementById('lista-agenda');
    listaAgenda.innerHTML = '';
    const eventos = hojeRes.eventos_agenda || [];
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

    // 2. Carrega visao especifica do metodo ativo via /gtd/visao
    const visaoRes = await api(`/gtd/visao?metodo=${encodeURIComponent(estado.metodoAtivo)}`);
    renderizarVisaoMetodo(visaoRes);
  } catch (err) {}
}

function renderizarVisaoMetodo(dadosVisao) {
  const container = document.getElementById('container-visao-metodo');
  container.innerHTML = '';

  const colunas = dadosVisao.colunas || [];
  const itensPorCol = dadosVisao.itens_por_coluna || {};
  const metodo = dadosVisao.metodo;

  // Atualiza texto explicativo do metodo
  const descEl = document.getElementById('metodo-descricao-ativa');
  if (descEl) {
    const mapaNomes = {
      gtd: 'Fluxo classico: Caixa de Entrada, Proximas Acoes, Aguardando e Algum Dia.',
      kanban: `Fluxo visual continuo. A Fazer, Fazendo (Limite WIP: ${dadosVisao.limite_wip || 3}) e Feito.`,
      eisenhower: 'Matriz de Urgente vs Importante em 4 quadrantes para priorizacao rapida.',
      para: 'Projetos (metas), Areas (responsabilidades), Recursos (estudos) e Arquivos.'
    };
    descEl.textContent = mapaNomes[metodo] || dadosVisao.metodo_nome || '';
  }

  if (metodo === 'kanban') {
    renderizarKanban(container, colunas, itensPorCol, dadosVisao.limite_wip || 3);
  } else if (metodo === 'eisenhower') {
    renderizarEisenhower(container, colunas, itensPorCol);
  } else if (metodo === 'para') {
    renderizarPARA(container, colunas, itensPorCol);
  } else {
    renderizarGTD(container, colunas, itensPorCol);
  }
}

function renderizarKanban(container, colunas, itensPorCol, limiteWip) {
  const board = document.createElement('div');
  board.className = 'kanban-board';

  colunas.forEach((col) => {
    const itens = itensPorCol[col.id] || [];
    const divCol = document.createElement('div');
    divCol.className = 'kanban-coluna';

    const ehFazendo = col.id === 'fazendo';
    const badgeWip = ehFazendo ? `<span class="badge ${itens.length > limiteWip ? 'alerta' : ''}">${itens.length}/${limiteWip} WIP</span>` : `<span class="badge">${itens.length}</span>`;

    divCol.innerHTML = `
      <div class="kanban-coluna-header">
        <span>${escaparHtml(col.titulo)}</span>
        ${badgeWip}
      </div>
      <div class="itens-container itens-kanban" id="col-kanban-${col.id}"></div>
    `;

    const subContainer = divCol.querySelector('.itens-kanban');
    if (itens.length === 0) {
      subContainer.innerHTML = '<p class="ajuda-texto">Vazio</p>';
    } else {
      itens.forEach((it) => {
        const card = document.createElement('div');
        card.className = 'item-card';
        card.innerHTML = `
          <div class="item-info">
            <div class="item-titulo">${escaparHtml(it.titulo)}</div>
            <div class="item-meta">
              <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
              ${it.prazo ? `<span class="tag-prazo">Prazo: ${it.prazo}</span>` : ''}
            </div>
          </div>
          <div class="item-botoes">
            ${col.id === 'a_fazer' ? `<button class="btn-secundario btn-puxar" data-id="${it.id}">Puxar</button>` : ''}
            ${col.id === 'fazendo' ? `<button class="btn-secundario btn-concluir" data-id="${it.id}">Feito</button>` : ''}
          </div>
        `;
        const btnPuxar = card.querySelector('.btn-puxar');
        if (btnPuxar) {
          btnPuxar.addEventListener('click', () => moverKanban(it.id, 'fazendo'));
        }
        const btnConcluir = card.querySelector('.btn-concluir');
        if (btnConcluir) {
          btnConcluir.addEventListener('click', () => concluirItem(it.id));
        }
        subContainer.appendChild(card);
      });
    }

    board.appendChild(divCol);
  });

  container.appendChild(board);
}

async function moverKanban(id, coluna) {
  try {
    await api('/gtd/processar', 'POST', {
      item_id: id,
      novo_estado: 'proxima'
    });
    // Atualiza metadados
    const res = await api('/gtd/itens');
    const alvo = (res.itens || []).find(i => i.id === id);
    if (alvo) {
      alvo.metadados = alvo.metadados || {};
      alvo.metadados.coluna_kanban = coluna;
      alvo.metadados.em_andamento = (coluna === 'fazendo');
      await api('/gtd/itens', 'POST', alvo);
    }
    carregarVisaoMetodo();
  } catch (err) {}
}

function renderizarEisenhower(container, colunas, itensPorCol) {
  const grid = document.createElement('div');
  grid.className = 'eisenhower-grid';

  const classesQ = { fazer: 'q1', agendar: 'q2', delegar: 'q3', eliminar: 'q4', feito: '' };

  colunas.filter(c => c.id !== 'feito').forEach((col) => {
    const itens = itensPorCol[col.id] || [];
    const divQ = document.createElement('div');
    divQ.className = 'eisenhower-quadrante';
    divQ.innerHTML = `
      <div class="quadrante-cabecalho ${classesQ[col.id] || ''}">
        <span>${escaparHtml(col.titulo)}</span>
        <span class="badge">${itens.length}</span>
      </div>
      <div class="itens-container">
        ${itens.length === 0 ? '<p class="ajuda-texto">Sem acoes neste quadrante</p>' : ''}
      </div>
    `;

    const sub = divQ.querySelector('.itens-container');
    itens.forEach((it) => {
      const card = document.createElement('div');
      card.className = 'item-card';
      card.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(it.titulo)}</div>
          <div class="item-meta">
            <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
          </div>
        </div>
        <div class="item-botoes">
          <button class="btn-secundario btn-concluir" data-id="${it.id}">Feito</button>
        </div>
      `;
      card.querySelector('.btn-concluir').addEventListener('click', () => concluirItem(it.id));
      sub.appendChild(card);
    });

    grid.appendChild(divQ);
  });

  container.appendChild(grid);
}

function renderizarPARA(container, colunas, itensPorCol) {
  const paraDiv = document.createElement('div');
  paraDiv.className = 'para-container';

  colunas.forEach((col) => {
    const itens = itensPorCol[col.id] || [];
    const sec = document.createElement('div');
    sec.className = 'para-secao';
    sec.innerHTML = `
      <div class="lista-cabecalho">
        <h4>${escaparHtml(col.titulo)}</h4>
        <span class="badge">${itens.length}</span>
      </div>
      <p class="ajuda-texto">${escaparHtml(col.descricao)}</p>
      <div class="itens-container" style="margin-top: 6px;">
        ${itens.length === 0 ? '<p class="ajuda-texto">Nenhum item</p>' : ''}
      </div>
    `;
    const sub = sec.querySelector('.itens-container');
    itens.forEach((it) => {
      const card = document.createElement('div');
      card.className = 'item-card';
      card.innerHTML = `
        <div class="item-info">
          <div class="item-titulo">${escaparHtml(it.titulo)}</div>
          <div class="item-meta">
            <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
          </div>
        </div>
        <div class="item-botoes">
          <button class="btn-secundario btn-concluir" data-id="${it.id}">Feito</button>
        </div>
      `;
      card.querySelector('.btn-concluir').addEventListener('click', () => concluirItem(it.id));
      sub.appendChild(card);
    });
    paraDiv.appendChild(sec);
  });

  container.appendChild(paraDiv);
}

function renderizarGTD(container, colunas, itensPorCol) {
  const proximas = itensPorCol['proxima'] || [];
  const div = document.createElement('div');
  div.className = 'bloco-lista';
  div.innerHTML = `
    <div class="lista-cabecalho">
      <h3>Proximas Acoes</h3>
      <span class="badge">${proximas.length}</span>
    </div>
    <div class="itens-container">
      ${proximas.length === 0 ? '<p class="ajuda-texto">Nenhuma proxima acao pendente.</p>' : ''}
    </div>
  `;

  const sub = div.querySelector('.itens-container');
  proximas.forEach((it) => {
    const card = document.createElement('div');
    card.className = 'item-card';
    card.innerHTML = `
      <div class="item-info">
        <div class="item-titulo">${escaparHtml(it.titulo)}</div>
        <div class="item-meta">
          <span class="tag-contexto">${escaparHtml(it.contexto)}</span>
          ${it.prazo ? `<span class="tag-prazo">Prazo: ${it.prazo}</span>` : ''}
        </div>
      </div>
      <div class="item-botoes">
        <button class="btn-secundario btn-concluir" data-id="${it.id}">Feito</button>
      </div>
    `;
    card.querySelector('.btn-concluir').addEventListener('click', () => concluirItem(it.id));
    sub.appendChild(card);
  });

  container.appendChild(div);
}

// -------------------------------------------------------------
// Timer Pomodoro Integrado (#45)
// -------------------------------------------------------------
function configurarEventosPomodoro() {
  document.getElementById('btn-pomo-start').addEventListener('click', async () => {
    try {
      await api('/gtd/pomodoro/iniciar', 'POST', { duracao_min: 25 });
      iniciarContadorLocal(25 * 60);
    } catch (err) {}
  });

  document.getElementById('btn-pomo-pause').addEventListener('click', async () => {
    try {
      const res = await api('/gtd/pomodoro/pausar', 'POST');
      pararContadorLocal();
      atualizarDisplayPomodoro(res);
    } catch (err) {}
  });

  document.getElementById('btn-pomo-stop').addEventListener('click', async () => {
    try {
      const res = await api('/gtd/pomodoro/parar', 'POST');
      pararContadorLocal();
      atualizarDisplayPomodoro(res);
    } catch (err) {}
  });
}

async function sincronizarEstadoPomodoro() {
  try {
    const res = await api('/gtd/pomodoro/estado');
    atualizarDisplayPomodoro(res);
    if (res.ativo && !res.pausado && res.segundos_restantes > 0) {
      iniciarContadorLocal(res.segundos_restantes);
    }
  } catch (err) {}
}

function iniciarContadorLocal(segundos) {
  pararContadorLocal();
  let rest = segundos;
  estado.pomodoroTimer = setInterval(() => {
    rest = Math.max(0, rest - 1);
    const m = Math.floor(rest / 60);
    const s = rest % 60;
    document.getElementById('pomo-tempo').textContent = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    if (rest <= 0) {
      pararContadorLocal();
      api('/gtd/pomodoro/concluir', 'POST').then((res) => {
        mostrarToast('Sessao Pomodoro concluida!');
        sincronizarEstadoPomodoro();
      }).catch(() => {});
    }
  }, 1000);
}

function pararContadorLocal() {
  if (estado.pomodoroTimer) {
    clearInterval(estado.pomodoroTimer);
    estado.pomodoroTimer = null;
  }
}

function atualizarDisplayPomodoro(res) {
  document.getElementById('pomo-tempo').textContent = res.tempo_formatado || '25:00';
  document.getElementById('pomo-modo-label').textContent = res.modo === 'foco' ? 'Foco' : 'Descanso';
  document.getElementById('pomo-ciclos').textContent = `${res.ciclos_concluidos || 0} ciclos`;
}

// -------------------------------------------------------------
// Wizard Passo a Passo (#47)
// -------------------------------------------------------------
function configurarEventosWizard() {
  document.getElementById('btn-pular-wizard').addEventListener('click', fecharWizard);
  document.getElementById('btn-wizard-avancar-1').addEventListener('click', () => mudarPassoWizard(2));
  document.getElementById('btn-wizard-voltar-2').addEventListener('click', () => mudarPassoWizard(1));
  document.getElementById('btn-wizard-avancar-2').addEventListener('click', () => mudarPassoWizard(3));
  document.getElementById('btn-wizard-voltar-3').addEventListener('click', () => mudarPassoWizard(2));
  document.getElementById('btn-wizard-concluir').addEventListener('click', concluirWizard);
}

function abrirWizard() {
  estado.passoWizard = 1;
  mudarPassoWizard(1);
  document.getElementById('modal-wizard').classList.remove('oculto');
}

function fecharWizard() {
  document.getElementById('modal-wizard').classList.add('oculto');
  api('/gtd/config', 'PUT', { wizard_concluido: true }).catch(() => {});
}

function mudarPassoWizard(passo) {
  estado.passoWizard = passo;
  document.querySelectorAll('.wizard-passo').forEach((p, idx) => {
    p.classList.toggle('ativo', idx + 1 === passo);
  });
  document.querySelectorAll('.wizard-ponto').forEach((pt, idx) => {
    pt.classList.toggle('ativo', idx + 1 === passo);
  });
}

async function concluirWizard() {
  const metodo = document.getElementById('wizard-metodo').value;
  const canal = document.getElementById('wizard-canal').value;
  const tema = document.getElementById('wizard-tema').value;
  const paleta = document.getElementById('wizard-paleta').value;

  estado.metodoAtivo = metodo;
  estado.tema = tema;
  estado.paleta = paleta;
  aplicarTemaEPaleta();

  try {
    await api('/gtd/config', 'PUT', {
      metodo_ativo: metodo,
      tema: tema,
      paleta: paleta,
      canais_ativos: [canal],
      wizard_concluido: true
    });
    mostrarToast('Assistente inicial concluido!');
    fecharWizard();
    await carregarConfiguracoesServidor();
    carregarVisaoMetodo();
  } catch (err) {
    fecharWizard();
  }
}

// -------------------------------------------------------------
// Inbox, Contextos e Leituras
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
    carregarVisaoMetodo();
  } catch (err) {}
}

async function concluirItem(id) {
  try {
    await api('/gtd/processar', 'POST', {
      item_id: id,
      novo_estado: 'feito'
    });
    mostrarToast('Acao concluida');
    carregarAbaAtual();
  } catch (err) {}
}

async function dispararSincronizacao() {
  mostrarToast('Sincronizando...');
  try {
    await api('/gtd/sincronizar', 'POST');
    mostrarToast('Sincronizacao concluida');
    carregarAbaAtual();
  } catch (err) {}
}

// -------------------------------------------------------------
// Modal de Processar
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

// Utilitarios
function mostrarToast(mensagem) {
  const toast = document.getElementById('toast');
  if (!toast) return;
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
