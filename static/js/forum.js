// Curtir / descurtir (comentários e resolução oficial) sem recarregar a página.
// Sem JavaScript o formulário funciona do jeito normal (a página recarrega e volta ao item);
// aqui o envio é interceptado e feito com fetch, e só os botões e os totais são atualizados.
//
// Cada formulário .form-curtir tem data-tipo="curtir" ou "descurtir". Na resolução os dois ficam
// juntos num .votos e se excluem, então a resposta do servidor traz o estado dos dois e ambos
// os botões do grupo são atualizados. Os textos vêm nos data-* do botão (_botao_curtir.html).
const CAMPOS_DA_RESPOSTA = {
    curtir: { ativo: 'curtido', total: 'total_curtidas' },
    descurtir: { ativo: 'descurtido', total: 'total_descurtidas' },
};

function atualizarBotao(form, ativo, total) {
    const botao = form.querySelector('.btn-curtir');
    const { rotuloAtivo, rotuloInativo, alvo, unidade } = botao.dataset;
    botao.setAttribute('aria-pressed', String(ativo));
    botao.title = ativo ? 'Clique para desfazer' : `${rotuloInativo} ${alvo}`;
    botao.querySelector('.curtir-rotulo').textContent = ativo ? rotuloAtivo : rotuloInativo;

    const totalEl = form.querySelector('.curtidas-total');
    const oculto = document.createElement('span');
    oculto.className = 'visualmente-oculto';
    oculto.textContent = ` ${unidade}${total === 1 ? '' : 's'}`;
    totalEl.replaceChildren(String(total), oculto);
}

document.querySelectorAll('.form-curtir').forEach((form) => {
    form.addEventListener('submit', async (evento) => {
        evento.preventDefault();
        // Os formulários do mesmo grupo (curtir + descurtir da resolução) ou só este (comentário)
        const grupo = form.closest('.votos');
        const formularios = grupo ? [...grupo.querySelectorAll('.form-curtir')] : [form];
        const botoes = formularios.map((f) => f.querySelector('.btn-curtir'));
        botoes.forEach((b) => { b.disabled = true; });  // evita cliques duplos durante a requisição

        try {
            const resposta = await fetch(form.action, {
                method: 'POST',
                // FormData já leva o csrfmiddlewaretoken do formulário (proteção CSRF do Django)
                body: new FormData(form),
                headers: { Accept: 'application/json' },
            });
            if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
            const estado = await resposta.json();

            formularios.forEach((f) => {
                const campos = CAMPOS_DA_RESPOSTA[f.dataset.tipo];
                if (campos && campos.ativo in estado) {
                    atualizarBotao(f, estado[campos.ativo], estado[campos.total]);
                }
            });
        } catch {
            // Algo deu errado (ex: sessão expirou): envia do jeito tradicional, e o servidor decide
            form.submit();
        } finally {
            botoes.forEach((b) => { b.disabled = false; });
        }
    });
});
