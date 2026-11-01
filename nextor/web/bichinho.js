/* Bichinho do Nextor: um rosto em painel de LEDs (pixel art) desenhado em SVG.
 * Usado pela pagina /rosto do Nextor e pelo NexDeck (mesmo arquivo nos dois projetos).
 * Estado: { identidade, modo, acessorio, expressao, atividade }.
 *   identidade: nextor (rosto) | claude | agy (simbolo proprio em pixels)
 *   acessorio: null | "mochila" | "gravata" | "relaxado" | "oculos"
 *   expressao: neutro | feliz | carinho | calmo | sonolento
 *   atividade: ocioso | ouvindo | pensando | falando | gravando
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var W = 24;
  var H = 20;

  // Cada desenho e uma lista de linhas; "#" acende o LED.
  var OLHO = {
    aberto: ['.##.', '####', '####', '####', '.##.'],
    fechado: ['....', '....', '####', '....', '....'],
    feliz: ['.###.', '#...#', '.....'],
    relaxado: ['#...#', '.###.'],
    sonolento: ['####', '.##.'],
  };
  var BOCA = {
    neutro: ['#....#', '.####.'],
    feliz: ['########', '.######.', '..####..'],
    carinho: ['#..#', '.##.'],
    calmo: ['####'],
    sonolento: ['.##.', '#..#', '.##.'],
    pensando: ['..##', '##..'],
    aberta: ['.####.', '#....#', '#....#', '.####.'],
    fechada: ['......', '.####.'],
  };
  var MOCHILA = ['.##.', '#..#', '####', '#..#', '####'];
  var GRAVATA = ['##....##', '###..###', '########', '###..###', '##....##'];  // gravata borboleta

  // Simbolos de outras identidades (desenhos originais em pixels).
  var SIMBOLO = {
    claude: ['.....#.....', '.#...#...#.', '..#..#..#..', '...#.#.#...', '....###....', '###########',
             '....###....', '...#.#.#...', '..#..#..#..', '.#...#...#.', '.....#.....'],
    agy: ['.....#.....', '....###....', '...##.##...', '..##...##..', '.##.....##.', '...........',
          '.....#.....', '....###....', '...##.##...', '..##...##..', '.##.....##.'],
  };

  function el(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  // Acende os pixels de um desenho na posicao (x, y), dentro de um grupo com classe propria.
  function desenho(grupo, linhas, x, y) {
    linhas.forEach(function (linha, dy) {
      for (var dx = 0; dx < linha.length; dx++) {
        if (linha[dx] === '#') el('circle', { cx: x + dx + 0.5, cy: y + dy + 0.5, r: 0.42 }, grupo);
      }
    });
  }

  function camada(svg, classe) {
    return el('g', { class: 'px ' + classe }, svg);
  }

  function centrado(linhas, cx) {
    return Math.round(cx - linhas[0].length / 2);
  }

  function olhos(svg, expressao, acessorio, atividade) {
    var olhar = atividade === 'pensando' ? { x: 1, y: -1 } : { x: 0, y: 0 };
    var centros = [7, 17];
    var relaxado = acessorio === 'relaxado' || expressao === 'calmo';

    if (expressao === 'feliz' || relaxado || expressao === 'sonolento') {
      var forma = expressao === 'feliz' ? OLHO.feliz : relaxado ? OLHO.relaxado : OLHO.sonolento;
      var g = camada(svg, 'px-on');
      centros.forEach(function (cx) { desenho(g, forma, centrado(forma, cx), expressao === 'sonolento' ? 8 : 6); });
      return;
    }
    // Olhos abertos piscam: duas camadas que se alternam pelo CSS.
    var abertos = camada(svg, 'px-on px-olho-aberto');
    var fechados = camada(svg, 'px-on px-olho-fechado');
    centros.forEach(function (cx) {
      var x = centrado(OLHO.aberto, cx) + olhar.x;
      desenho(abertos, OLHO.aberto, x, 4 + olhar.y);
      desenho(fechados, OLHO.fechado, x, 4 + olhar.y);
    });
    if (expressao === 'carinho') {
      var sobrancelha = camada(svg, 'px-on');
      // inclinadas para dentro: empatia
      desenho(sobrancelha, ['##..', '..##'], 5, 1);
      desenho(sobrancelha, ['..##', '##..'], 15, 1);
    }
  }

  function boca(svg, expressao, atividade) {
    if (atividade === 'falando') {
      desenho(camada(svg, 'px-on px-boca-a'), BOCA.aberta, centrado(BOCA.aberta, 12), 11);
      desenho(camada(svg, 'px-on px-boca-b'), BOCA.fechada, centrado(BOCA.fechada, 12), 11);
      return;
    }
    var forma = atividade === 'pensando' ? BOCA.pensando : (BOCA[expressao] || BOCA.neutro);
    desenho(camada(svg, 'px-on'), forma, centrado(forma, 12), expressao === 'feliz' ? 11 : 12);
  }

  function acessorios(svg, acessorio) {
    if (acessorio === 'oculos') {
      var g = camada(svg, 'px-on px-acento');
      [[3, 3], [13, 3]].forEach(function (p) {
        desenho(g, ['########', '#......#', '#......#', '#......#', '#......#', '#......#', '.######.'], p[0], p[1]);
      });
      desenho(g, ['##'], 11, 4);
    }
    if (acessorio === 'gravata') desenho(camada(svg, 'px-on px-acento'), GRAVATA, 8, 15);
    if (acessorio === 'mochila') desenho(camada(svg, 'px-on px-acento'), MOCHILA, 19, 14);
    if (acessorio === 'relaxado') desenho(camada(svg, 'px-on px-suave px-flutua'), ['###', '..#', '.#.', '###'], 20, 0);
  }

  function atividades(svg, atividade) {
    if (atividade === 'pensando') {
      var g = camada(svg, 'px-on px-suave px-pensa');
      desenho(g, ['#'], 20, 3);
      desenho(g, ['##', '##'], 21, 0);
    }
    if (atividade === 'ouvindo') {
      desenho(camada(svg, 'px-on px-onda px-onda-1'), ['#', '#', '#'], 0, 7);
      desenho(camada(svg, 'px-on px-onda px-onda-2'), ['#', '#', '#', '#', '#'], 1, 6);
      desenho(camada(svg, 'px-on px-onda px-onda-2'), ['#', '#', '#', '#', '#'], 22, 6);
      desenho(camada(svg, 'px-on px-onda px-onda-1'), ['#', '#', '#'], 23, 7);
    }
    if (atividade === 'gravando') desenho(camada(svg, 'px-on px-rec'), ['##', '##'], 0, 0);
  }

  function render(container, estado) {
    estado = estado || {};
    var expressao = estado.expressao || 'neutro';
    var acessorio = estado.acessorio || null;
    var atividade = estado.atividade || 'ocioso';

    var identidade = SIMBOLO[estado.identidade] ? estado.identidade : 'nextor';
    var svg = el('svg', {
      viewBox: '-1 -1 ' + (W + 2) + ' ' + (H + 2),
      class: 'bichinho modo-' + (estado.modo || 'normal') + ' atividade-' + atividade + ' ident-' + identidade,
      role: 'img',
      'aria-label': descrever(estado),
    });
    el('rect', { x: -1, y: -1, width: W + 2, height: H + 2, rx: 3.2, class: 'px-painel' }, svg);

    // LEDs apagados formam a grade do painel.
    var apagados = camada(svg, 'px-off');
    for (var y = 0; y < H; y++) {
      for (var x = 0; x < W; x++) el('circle', { cx: x + 0.5, cy: y + 0.5, r: 0.42 }, apagados);
    }

    if (identidade === 'nextor') {
      olhos(svg, expressao, acessorio, atividade);
      boca(svg, expressao, atividade);
      acessorios(svg, acessorio);
    } else {
      var classe = 'px-on px-simbolo' + (atividade === 'falando' ? ' px-falando' : '');
      desenho(camada(svg, classe), SIMBOLO[identidade], 7, 4);
    }
    atividades(svg, atividade);

    container.replaceChildren(svg);
    return svg;
  }

  var NOMES = {
    expressao: { neutro: 'tranquilo', feliz: 'feliz', carinho: 'carinhoso', calmo: 'calmo', sonolento: 'sonolento' },
    atividade: { ocioso: '', ouvindo: ', ouvindo', pensando: ', pensando', falando: ', falando', gravando: ', gravando' },
  };

  function descrever(estado) {
    var e = NOMES.expressao[estado.expressao] || 'tranquilo';
    var a = NOMES.atividade[estado.atividade] || '';
    var m = estado.modo && estado.modo !== 'normal' ? ' no modo ' + estado.modo : '';
    var nomes = { claude: 'Claude', agy: 'agy' };
    if (nomes[estado.identidade]) return nomes[estado.identidade] + ' respondendo pelo Nextor' + a;
    return 'Nextor ' + e + a + m;
  }

  global.Bichinho = { render: render, descrever: descrever };
})(typeof window !== 'undefined' ? window : this);
