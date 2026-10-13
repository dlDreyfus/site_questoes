// Tela estilo MS-DOS da página de login: apaga o texto e o "digita" de novo, letra por letra, com o
// cursor piscando no fim, em looping. Quem pediu movimento reduzido ao sistema vê o texto inteiro, sem animação.
(function () {
    const terminal = document.querySelector('[data-terminal]');
    if (!terminal) return;

    const texto = terminal.textContent;
    const cursor = document.createElement('span');
    cursor.className = 'terminal-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    cursor.textContent = '_';

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        terminal.append(cursor);
        return;
    }

    // O leitor de tela lê a frase inteira de uma vez (na cópia oculta), não letra por letra
    const paraLeitor = document.createElement('span');
    paraLeitor.className = 'visualmente-oculto';
    paraLeitor.textContent = texto;
    const digitado = document.createElement('span');
    digitado.setAttribute('aria-hidden', 'true');
    terminal.replaceChildren(paraLeitor, digitado, cursor);

    let posicao = 0;
    function digitar() {
        posicao += 1;
        digitado.textContent = texto.slice(0, posicao);
        if (posicao >= texto.length) {
            // Em looping: deixa a mensagem completa na tela por um tempo, limpa (como o "cls" do DOS),
            // espera um instante com só o cursor piscando e digita tudo de novo
            setTimeout(function () {
                posicao = 0;
                digitado.textContent = '';
                setTimeout(digitar, 1000);
            }, 4000);
            return;
        }
        // Ritmo de quem digita: um pouco irregular, com pausa maior na quebra de linha
        const proximo = texto[posicao - 1];
        // (6 a 20 ms por letra, em média uns 13 ms; 150 ms ao trocar de linha)
        const pausa = proximo === '\n' ? 150 : 6 + Math.random() * 14;
        setTimeout(digitar, pausa);
    }
    setTimeout(digitar, 500);
})();
