// Aplica os filtros da lista de questões assim que um dropdown muda,
// sem precisar clicar em "Aplicar Filtros" (o botão só aparece com JavaScript desativado).
document.querySelectorAll('.filtro-form select').forEach((select) => {
    select.addEventListener('change', () => select.form.submit());
});

// Painel de filtros recolhível no celular.
// O CSS só esconde o formulário recolhido em telas pequenas; no tablet/computador ele fica sempre visível.
const formFiltros = document.getElementById('filtros');
const botaoFiltros = document.querySelector('.btn-filtros');

if (formFiltros && botaoFiltros) {
    const definirAberto = (aberto) => {
        formFiltros.toggleAttribute('data-recolhido', !aberto);
        botaoFiltros.setAttribute('aria-expanded', String(aberto));
    };

    // Começa aberto só se houver algum filtro em uso (para o usuário ver o que está filtrando)
    definirAberto(Number(formFiltros.dataset.filtrosAtivos) > 0);
    botaoFiltros.hidden = false;

    botaoFiltros.addEventListener('click', () => {
        definirAberto(botaoFiltros.getAttribute('aria-expanded') !== 'true');
    });
}
