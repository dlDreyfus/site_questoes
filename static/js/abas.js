// Abas da Home: os links da barra lateral abrem o app numa aba, dentro de um iframe, em vez de
// trocar de página. Clicar de novo no mesmo app só volta para a aba que já está aberta.
// Sem JavaScript os links funcionam do jeito normal (a página do app abre no lugar da Home).
// As abas e os robôs da barra lateral podem ser arrastados para mudar a ordem, e a ordem nova também
// fica guardada.
//
// As abas abertas, a página em que cada uma está e a aba ativa ficam guardadas no navegador
// (localStorage, uma chave por usuário): ao recarregar a Home ou entrar de novo, elas voltam.
// Se o navegador não deixar guardar (janela anônima, dados bloqueados), as abas só não voltam.
(function () {
    const abas = document.querySelector('[data-abas]');
    const paineis = document.querySelector('[data-paineis]');
    const links = document.querySelectorAll('.home-lateral-link[data-aba]');
    if (!abas || !paineis) return;

    const CHAVE = `home-abas-${abas.dataset.usuario}`;
    let contador = 0;
    // Enquanto as abas guardadas são reabertas, nada é salvo (senão a lista seria regravada pela metade)
    let restaurando = false;

    function salvar() {
        if (restaurando) return;
        const estado = {
            abas: [...abas.querySelectorAll('.home-aba[data-app]')].map((aba) => ({
                nome: aba.dataset.app,
                url: aba.dataset.url,
            })),
            ativa: abas.querySelector('.home-aba.ativa').dataset.app || null,
        };
        try {
            localStorage.setItem(CHAVE, JSON.stringify(estado));
        } catch (erro) {
            // Sem acesso ao localStorage: as abas funcionam, só não são lembradas
        }
    }

    function lerEstado() {
        try {
            const estado = JSON.parse(localStorage.getItem(CHAVE));
            return estado && Array.isArray(estado.abas) ? estado : null;
        } catch (erro) {
            return null;
        }
    }

    // Só reabre endereços do próprio site
    function doSite(url) {
        try {
            return new URL(url, window.location.href).origin === window.location.origin;
        } catch (erro) {
            return false;
        }
    }

    // Mostra a aba e o painel escolhidos e marca, na barra lateral, o link do app dessa aba
    function ativar(aba) {
        abas.querySelectorAll('.home-aba').forEach((outra) => {
            const ativa = outra === aba;
            outra.classList.toggle('ativa', ativa);
            outra.setAttribute('aria-selected', ativa ? 'true' : 'false');
            document.getElementById(outra.getAttribute('aria-controls')).classList.toggle('ativo', ativa);
        });
        links.forEach((link) => {
            link.classList.toggle('ativo', link.dataset.aba === aba.dataset.app);
        });
        salvar();
    }

    // Fecha a aba e volta para a vizinha da esquerda (a Início nunca fecha)
    function fechar(aba) {
        const vizinha = aba.previousElementSibling;
        document.getElementById(aba.getAttribute('aria-controls')).remove();
        aba.remove();
        if (aba.classList.contains('ativa')) {
            ativar(vizinha);
        } else {
            salvar();
        }
    }

    function abrir(nome, url) {
        const aberta = abas.querySelector(`.home-aba[data-app="${CSS.escape(nome)}"]`);
        if (aberta) {
            ativar(aberta);
            return;
        }

        contador += 1;
        const painel = document.createElement('section');
        painel.className = 'home-painel';
        painel.id = `painel-app-${contador}`;
        painel.setAttribute('role', 'tabpanel');
        painel.setAttribute('aria-labelledby', `aba-app-${contador}`);

        const aba = document.createElement('button');
        aba.type = 'button';
        aba.className = 'home-aba';
        aba.id = `aba-app-${contador}`;
        aba.dataset.app = nome;
        aba.dataset.url = url;
        aba.setAttribute('role', 'tab');
        aba.setAttribute('aria-controls', painel.id);
        aba.title = 'Arraste para mudar a ordem (ou Alt + seta para os lados)';
        aba.textContent = nome;

        const iframe = document.createElement('iframe');
        iframe.className = 'home-iframe';
        iframe.src = url;
        iframe.title = nome;
        // A cada página nova dentro da aba, guarda o endereço, para a aba voltar onde estava
        iframe.addEventListener('load', () => {
            try {
                const atual = iframe.contentWindow.location.href;
                if (doSite(atual) && atual !== 'about:blank') {
                    aba.dataset.url = atual;
                    salvar();
                }
            } catch (erro) {
                // Página de outro site: o navegador não deixa ler o endereço
            }
        });
        painel.append(iframe);

        // O "×" fica dentro da aba; o clique nele fecha em vez de ativar
        const fecha = document.createElement('span');
        fecha.className = 'home-aba-fechar';
        fecha.setAttribute('aria-label', `Fechar a aba ${nome}`);
        fecha.setAttribute('role', 'button');
        fecha.textContent = '×';
        aba.append(fecha);

        abas.append(aba);
        paineis.append(painel);
        ativar(aba);
    }

    // Reabre as abas guardadas, na mesma ordem. Só volta app que ainda está na barra lateral.
    function restaurar() {
        const estado = lerEstado();
        if (!estado) return;
        const apps = new Set([...links].map((link) => link.dataset.aba));
        restaurando = true;
        estado.abas.forEach(({ nome, url }) => {
            if (apps.has(nome) && doSite(url)) abrir(nome, url);
        });
        const ativa = estado.ativa && abas.querySelector(`.home-aba[data-app="${CSS.escape(estado.ativa)}"]`);
        ativar(ativa || abas.querySelector('.home-aba'));
        restaurando = false;
    }

    abas.addEventListener('click', (evento) => {
        const aba = evento.target.closest('.home-aba');
        if (!aba) return;
        if (evento.target.closest('.home-aba-fechar')) {
            fechar(aba);
        } else {
            ativar(aba);
        }
    });

    // Arrastar para mudar a ordem, com mouse, caneta ou dedo. Vale para as abas (a Início fica sempre em
    // primeiro, porque só os itens que casam com o seletor se movem) e para os robôs da barra lateral.
    // No toque é preciso segurar o item um instante antes de arrastar; arrastar direto rola a faixa.
    // Pelo teclado: Alt + seta move o item em foco. A lista pode estar na horizontal ou na vertical
    // (a barra lateral é horizontal no celular e vertical a partir do tablet).
    const LIMIAR = 5; // pixels que o mouse anda antes de virar arraste (abaixo disso é só um clique)
    const ESPERA_TOQUE = 300; // milissegundos segurando o dedo até poder arrastar

    function tornarReordenavel(lista, seletor, aoMudar) {
        let arraste = null;
        // Depois de arrastar um link, o clique que o navegador dispara ao soltar não deve abri-lo
        let ignorarClique = false;

        const vertical = () => getComputedStyle(lista).flexDirection.startsWith('column');

        function comecar() {
            arraste.ativo = true;
            arraste.item.classList.add('arrastando');
            try {
                arraste.item.setPointerCapture(arraste.id);
            } catch (erro) {
                // O dedo já saiu da tela: o pointerup encerra o arraste
            }
        }

        function encerrar() {
            if (!arraste) return;
            clearTimeout(arraste.espera);
            if (arraste.ativo) {
                arraste.item.classList.remove('arrastando');
                ignorarClique = true;
                setTimeout(() => { ignorarClique = false; }, 0);
                aoMudar();
            }
            arraste = null;
        }

        lista.addEventListener('pointerdown', (evento) => {
            const item = evento.target.closest(seletor);
            if (!item || evento.button !== 0 || evento.target.closest('.home-aba-fechar')) return;
            arraste = { item, id: evento.pointerId, x: evento.clientX, y: evento.clientY, ativo: false };
            if (evento.pointerType === 'touch') arraste.espera = setTimeout(comecar, ESPERA_TOQUE);
        });

        lista.addEventListener('pointermove', (evento) => {
            if (!arraste || evento.pointerId !== arraste.id) return;
            if (!arraste.ativo) {
                const andou = Math.hypot(evento.clientX - arraste.x, evento.clientY - arraste.y) > LIMIAR;
                if (!andou) return;
                // Dedo que andou antes da espera está rolando a faixa, não arrastando
                if (evento.pointerType === 'touch') {
                    encerrar();
                    return;
                }
                comecar();
            }
            // Põe o item antes do primeiro outro cujo meio fica depois do ponteiro (ou no fim)
            const emPe = vertical();
            const outros = [...lista.querySelectorAll(seletor)].filter((item) => item !== arraste.item);
            const depois = outros.find((item) => {
                const caixa = item.getBoundingClientRect();
                return emPe
                    ? evento.clientY < caixa.top + caixa.height / 2
                    : evento.clientX < caixa.left + caixa.width / 2;
            });
            if (depois) {
                if (arraste.item.nextElementSibling !== depois) lista.insertBefore(arraste.item, depois);
            } else if (lista.lastElementChild !== arraste.item) {
                lista.append(arraste.item);
            }
        });

        lista.addEventListener('pointerup', encerrar);
        lista.addEventListener('pointercancel', encerrar);

        // Durante o arraste com o dedo, a faixa não rola junto
        lista.addEventListener('touchmove', (evento) => {
            if (arraste && arraste.ativo) evento.preventDefault();
        }, { passive: false });

        // O navegador arrastaria o link como endereço (para soltar em outra janela) e cortaria o arraste
        lista.addEventListener('dragstart', (evento) => {
            if (evento.target.closest && evento.target.closest(seletor)) evento.preventDefault();
        });

        lista.addEventListener('click', (evento) => {
            if (!ignorarClique) return;
            evento.preventDefault();
            evento.stopImmediatePropagation();
        }, true);

        lista.addEventListener('keydown', (evento) => {
            const item = evento.target.closest(seletor);
            const anterior = ['ArrowLeft', 'ArrowUp'].includes(evento.key);
            const proximo = ['ArrowRight', 'ArrowDown'].includes(evento.key);
            if (!item || !evento.altKey || !(anterior || proximo)) return;
            evento.preventDefault();
            if (anterior) {
                const vizinho = item.previousElementSibling;
                if (vizinho && vizinho.matches(seletor)) lista.insertBefore(item, vizinho);
            } else if (item.nextElementSibling) {
                lista.insertBefore(item.nextElementSibling, item);
            }
            item.focus();
            aoMudar();
        });
    }

    tornarReordenavel(abas, '.home-aba[data-app]', salvar);

    // Ordem dos robôs da barra lateral, guardada como a lista de nomes dos apps
    const lateral = document.querySelector('.home-lateral');
    const CHAVE_ROBOS = `home-robos-${abas.dataset.usuario}`;

    function salvarRobos() {
        try {
            localStorage.setItem(CHAVE_ROBOS, JSON.stringify([...lateral.children].map((link) => link.dataset.aba)));
        } catch (erro) {
            // Sem acesso ao localStorage: a ordem nova vale só até recarregar a página
        }
    }

    // Põe os robôs na ordem guardada. App que não estava na lista (um app novo) fica no fim.
    function restaurarRobos() {
        let ordem;
        try {
            ordem = JSON.parse(localStorage.getItem(CHAVE_ROBOS));
        } catch (erro) {
            return;
        }
        if (!Array.isArray(ordem)) return;
        const posicao = (link) => {
            const indice = ordem.indexOf(link.dataset.aba);
            return indice === -1 ? ordem.length : indice;
        };
        [...links].sort((a, b) => posicao(a) - posicao(b)).forEach((link) => lateral.append(link));
    }

    if (lateral) {
        restaurarRobos();
        tornarReordenavel(lateral, '.home-lateral-link[data-aba]', salvarRobos);
    }

    links.forEach((link) => {
        link.addEventListener('click', (evento) => {
            // Ctrl/Cmd+clique e clique do meio continuam abrindo o app numa aba do navegador
            if (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.button !== 0) return;
            evento.preventDefault();
            abrir(link.dataset.aba, link.href);
        });
    });

    restaurar();
})();
