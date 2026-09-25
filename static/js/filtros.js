// Filtros de múltipla escolha: cada filtro é um <details> com caixas de marcação.
// O usuário marca quantas opções quiser; ao fechar o filtro (clicando fora, no resumo ou com Esc),
// o formulário é enviado se algo mudou, sem precisar clicar em "Aplicar Filtros" (o botão só aparece
// com JavaScript desativado). O envio atualiza a cascata: as opções dos outros filtros se ajustam.
const filtrosMultiplos = document.querySelectorAll('.filtro-form .filtro-multiplo');

// Valores marcados num filtro, como texto (para saber se mudaram desde que a página carregou)
const marcados = (filtro) => Array.from(filtro.querySelectorAll('input:checked'), (caixa) => caixa.value).join(',');

// Resumo exibido no filtro fechado: "Todas as Bancas", os nomes marcados (até 2) ou "3 bancas"
const atualizarResumo = (filtro) => {
    const nomes = Array.from(filtro.querySelectorAll('input:checked'), (caixa) => caixa.parentElement.textContent.trim());
    const resumo = filtro.querySelector('.filtro-resumo');
    if (nomes.length === 0) {
        resumo.textContent = filtro.dataset.nenhum;
    } else if (nomes.length <= 2) {
        resumo.textContent = nomes.join(', ');
    } else {
        resumo.textContent = `${nomes.length} ${filtro.dataset.plural}`;
    }
};

// Texto sem acentos e em minúsculas, para a busca de opções ("licitacao" encontra "Licitações")
const normalizar = (texto) => texto.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();

// Campo de busca no topo da lista de opções: esconde as opções que não contêm o texto digitado.
// Criado aqui (e não no template) porque sem JavaScript ele não teria função. Não tem 'name': não vai
// para a URL. Nos tópicos, o nome da matéria some quando nenhum tópico dela combina.
const criarBuscaDeOpcoes = (filtro) => {
    const lista = filtro.querySelector('.filtro-opcoes');
    const opcoes = Array.from(lista.querySelectorAll('.filtro-opcao'));
    if (opcoes.length === 0) return null;

    const campo = document.createElement('input');
    campo.type = 'search';
    campo.className = 'filtro-opcoes-busca';
    campo.placeholder = 'Filtrar opções';
    campo.autocomplete = 'off';
    campo.setAttribute('aria-label', `Filtrar ${filtro.dataset.plural}`);

    const nenhuma = document.createElement('p');
    nenhuma.className = 'filtro-sem-opcoes';
    nenhuma.textContent = 'Nenhuma opção encontrada';
    nenhuma.hidden = true;

    const filtrar = () => {
        const termo = normalizar(campo.value);
        let visiveis = 0;
        opcoes.forEach((opcao) => {
            opcao.hidden = termo !== '' && !normalizar(opcao.textContent).includes(termo);
            if (!opcao.hidden) visiveis += 1;
        });
        lista.querySelectorAll('.filtro-opcoes-grupo').forEach((grupo) => {
            grupo.hidden = !grupo.querySelector('.filtro-opcao:not([hidden])');
        });
        nenhuma.hidden = visiveis > 0;
    };

    campo.addEventListener('input', filtrar);
    // Enter aqui só filtra: não envia o formulário (que é enviado ao fechar o filtro)
    campo.addEventListener('keydown', (evento) => {
        if (evento.key === 'Enter') evento.preventDefault();
    });
    // O 'change' do campo sobe até o <details>, mas não é uma opção marcada: não precisa ir adiante
    campo.addEventListener('change', (evento) => evento.stopPropagation());

    lista.prepend(campo);
    lista.append(nenhuma);
    return {
        campo,
        limpar: () => {
            campo.value = '';
            filtrar();
        },
    };
};

// Só com mouse o foco vai direto para a busca ao abrir o filtro (no celular, abriria o teclado à toa)
const focarAoAbrir = window.matchMedia('(pointer: fine)').matches;

filtrosMultiplos.forEach((filtro) => {
    const inicial = marcados(filtro);
    atualizarResumo(filtro);
    const busca = criarBuscaDeOpcoes(filtro);

    filtro.addEventListener('toggle', () => {
        if (!busca) return;
        if (filtro.open && focarAoAbrir) {
            busca.campo.focus({ preventScroll: true });
        } else if (!filtro.open) {
            // Ao reabrir, todas as opções voltam a aparecer
            busca.limpar();
        }
    });

    filtro.addEventListener('change', () => atualizarResumo(filtro));

    filtro.addEventListener('toggle', () => {
        if (filtro.open) {
            // Só um filtro aberto por vez (fechar o anterior o aplica, se ele mudou)
            filtrosMultiplos.forEach((outro) => {
                if (outro !== filtro) outro.open = false;
            });
        } else if (marcados(filtro) !== inicial) {
            filtro.closest('form').requestSubmit();
        }
    });

    // Esc fecha o filtro e devolve o foco ao resumo
    filtro.addEventListener('keydown', (evento) => {
        if (evento.key === 'Escape' && filtro.open) {
            filtro.open = false;
            filtro.querySelector('summary').focus();
        }
    });
});

// Clique fora de um filtro aberto o fecha (e o aplica, se mudou)
document.addEventListener('click', (evento) => {
    filtrosMultiplos.forEach((filtro) => {
        if (filtro.open && !filtro.contains(evento.target)) filtro.open = false;
    });
});

// Busca textual: o "x" do campo (navegadores que o exibem) limpa a busca e já reaplica os filtros
const campoBusca = document.getElementById('busca');
if (campoBusca) {
    const buscaInicial = campoBusca.value;
    campoBusca.addEventListener('search', () => {
        if (campoBusca.value === '' && buscaInicial !== '') campoBusca.form.requestSubmit();
    });
}

// Painel de filtros recolhível no celular.
// O CSS só esconde o formulário recolhido em telas pequenas; no tablet/computador ele fica sempre visível.
const formFiltros = document.getElementById('filtros');
const botaoFiltros = document.querySelector('.btn-filtros');

if (formFiltros && botaoFiltros) {
    const definirAberto = (aberto) => {
        formFiltros.toggleAttribute('data-recolhido', !aberto);
        botaoFiltros.setAttribute('aria-expanded', String(aberto));
    };

    // Começa aberto só se houver algum filtro em uso (para o usuário ver o que está filtrando),
    // ou sempre, nas páginas em que os filtros são o assunto principal (data-filtros-abertos)
    definirAberto(Number(formFiltros.dataset.filtrosAtivos) > 0 || 'filtrosAbertos' in formFiltros.dataset);
    botaoFiltros.hidden = false;

    botaoFiltros.addEventListener('click', () => {
        definirAberto(botaoFiltros.getAttribute('aria-expanded') !== 'true');
    });
}
