/* Bichinho do Nextor: desenha o personagem em SVG a partir do estado do companheiro.
 * Usado pela pagina /rosto do Nextor e pelo NexDeck (mesmo arquivo nos dois projetos).
 * Estado: { modo, acessorio, expressao, atividade }.
 *   acessorio: null | "mochila" | "gravata" | "relaxado" | "oculos"
 *   expressao: neutro | feliz | carinho | calmo | sonolento
 *   atividade: ocioso | ouvindo | pensando | falando | gravando
 */
(function (global) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function olhos(g, expressao, acessorio, atividade) {
    var relaxado = acessorio === 'relaxado' || expressao === 'calmo';
    var olhar = atividade === 'pensando' ? 4 : 0;
    var grupo = el('g', { class: 'b-olhos' + (relaxado || expressao === 'feliz' ? '' : ' b-pisca') }, g);
    [78, 122].forEach(function (x) {
      if (expressao === 'feliz') {
        el('path', { d: 'M' + (x - 9) + ' 102 Q' + x + ' 90 ' + (x + 9) + ' 102', class: 'b-traco' }, grupo);
      } else if (relaxado) {
        el('path', { d: 'M' + (x - 9) + ' 98 Q' + x + ' 106 ' + (x + 9) + ' 98', class: 'b-traco' }, grupo);
      } else if (expressao === 'sonolento') {
        // palpebras pesadas: so a metade de baixo do olho aparece
        el('path', { d: 'M' + (x - 8) + ' 100 Q' + x + ' 108 ' + (x + 8) + ' 100 Z', class: 'b-olho' }, grupo);
        el('path', { d: 'M' + (x - 9) + ' 100 L' + (x + 9) + ' 100', class: 'b-traco b-fino' }, grupo);
      } else {
        el('ellipse', { cx: x + olhar, cy: 98 - olhar, rx: 7, ry: 9, class: 'b-olho' }, grupo);
        el('circle', { cx: x + olhar + 2.5, cy: 94 - olhar, r: 2.4, class: 'b-brilho' }, grupo);
      }
      if (expressao === 'carinho') {
        // sobrancelhas inclinadas: empatia
        var dir = x < 100 ? 1 : -1;
        el('path', { d: 'M' + (x - 9) + ' ' + (84 + dir * 3) + ' L' + (x + 9) + ' ' + (84 - dir * 3), class: 'b-traco b-fino' }, grupo);
      }
    });
  }

  function boca(g, expressao, atividade) {
    if (atividade === 'falando') {
      el('ellipse', { cx: 100, cy: 124, rx: 9, ry: 6, class: 'b-boca b-falando' }, g);
      return;
    }
    var formas = {
      feliz: 'M84 118 Q100 136 116 118 Z',
      carinho: 'M90 121 Q100 128 110 121',
      calmo: 'M91 123 Q100 126 109 123',
      sonolento: null,
      neutro: 'M89 120 Q100 128 111 120',
    };
    if (expressao === 'sonolento') {
      el('ellipse', { cx: 100, cy: 123, rx: 4, ry: 4.5, class: 'b-boca' }, g);
    } else if (atividade === 'pensando') {
      el('path', { d: 'M94 124 Q102 121 110 124', class: 'b-traco' }, g);
    } else {
      var d = formas[expressao] || formas.neutro;
      el('path', { d: d, class: expressao === 'feliz' ? 'b-boca' : 'b-traco' }, g);
    }
  }

  function render(container, estado) {
    estado = estado || {};
    var expressao = estado.expressao || 'neutro';
    var acessorio = estado.acessorio || null;
    var atividade = estado.atividade || 'ocioso';

    var svg = el('svg', {
      viewBox: '0 0 200 200',
      class: 'bichinho modo-' + (estado.modo || 'normal') + ' atividade-' + atividade,
      role: 'img',
      'aria-label': descrever(estado),
    });

    el('ellipse', { cx: 100, cy: 178, rx: 46, ry: 7, class: 'b-sombra' }, svg);
    var corpo = el('g', { class: 'b-corpo-grupo' }, svg);

    if (acessorio === 'mochila') {
      el('rect', { x: 26, y: 92, width: 34, height: 52, rx: 10, class: 'b-mochila' }, corpo);
      el('rect', { x: 30, y: 118, width: 26, height: 16, rx: 5, class: 'b-mochila-bolso' }, corpo);
    }

    // antena (o "radio" do Nextor)
    el('path', { d: 'M100 52 L100 36', class: 'b-traco b-antena' }, corpo);
    el('circle', { cx: 100, cy: 32, r: 6, class: 'b-antena-ponta' }, corpo);

    el('ellipse', { cx: 100, cy: 112, rx: 62, ry: 60, class: 'b-corpo' }, corpo);
    el('ellipse', { cx: 100, cy: 138, rx: 34, ry: 26, class: 'b-barriga' }, corpo);

    if (expressao === 'feliz' || expressao === 'carinho') {
      el('ellipse', { cx: 64, cy: 116, rx: 8, ry: 5, class: 'b-bochecha' }, corpo);
      el('ellipse', { cx: 136, cy: 116, rx: 8, ry: 5, class: 'b-bochecha' }, corpo);
    }

    olhos(corpo, expressao, acessorio, atividade);
    boca(corpo, expressao, atividade);

    if (acessorio === 'oculos') {
      el('circle', { cx: 78, cy: 99, r: 15, class: 'b-oculos' }, corpo);
      el('circle', { cx: 122, cy: 99, r: 15, class: 'b-oculos' }, corpo);
      el('path', { d: 'M93 97 Q100 92 107 97', class: 'b-oculos' }, corpo);
    }
    if (acessorio === 'gravata') {
      // camisa em V e gravata descendo pela barriga
      el('path', { d: 'M78 132 L100 158 L122 132 Q100 140 78 132 Z', class: 'b-gola' }, corpo);
      el('path', { d: 'M95 138 L105 138 L103 146 L97 146 Z', class: 'b-gravata' }, corpo);
      el('path', { d: 'M97 146 L103 146 L108 166 L100 174 L92 166 Z', class: 'b-gravata' }, corpo);
    }
    if (acessorio === 'mochila') {
      el('path', { d: 'M46 100 Q50 128 58 160', class: 'b-alca' }, corpo);
    }

    if (atividade === 'pensando') {
      [[150, 50, 4], [162, 38, 6], [178, 22, 9]].forEach(function (c, i) {
        el('circle', { cx: c[0], cy: c[1], r: c[2], class: 'b-pensamento b-pensamento-' + i }, svg);
      });
    }
    if (atividade === 'ouvindo') {
      el('path', { d: 'M112 24 Q120 32 112 40', class: 'b-traco b-onda' }, svg);
      el('path', { d: 'M88 24 Q80 32 88 40', class: 'b-traco b-onda' }, svg);
    }
    if (atividade === 'gravando') {
      el('circle', { cx: 24, cy: 24, r: 8, class: 'b-rec' }, svg);
    }

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
    return 'Nextor ' + e + a + m;
  }

  global.Bichinho = { render: render, descrever: descrever };
})(typeof window !== 'undefined' ? window : this);
