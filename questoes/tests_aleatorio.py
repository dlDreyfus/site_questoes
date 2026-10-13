"""Botão "Aleatório": questões em ordem aleatória (respeitando os filtros) na lista e nos simulados."""
import random

from django.urls import reverse

from .models import Simulado
from .tests_simulados import BaseSimuladosTestCase

SEMENTE = 12345


def embaralhados(questoes, semente=SEMENTE):
    """A ordem que a semente deve produzir: os ids em ordem crescente, embaralhados por ela."""
    ids = sorted(questao.pk for questao in questoes)
    random.Random(semente).shuffle(ids)
    return ids


class BaseAleatorioTestCase(BaseSimuladosTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Questões suficientes para que a ordem embaralhada seja diferente da normal
        cls.extras = [cls.criar_questao(cls.fgv, 2010 + i, cls.licitacoes) for i in range(6)]
        cls.todas = [cls.q1, cls.q2, cls.q3, *cls.extras]

    def ordem_exibida(self, url, total, **parametros):
        """Ids das questões, página por página (uma questão por página)."""
        ids = []
        for pagina in range(1, total + 1):
            resposta = self.client.get(url, {**parametros, 'page': pagina})
            ids += [questao.pk for questao in resposta.context['questoes']]
        return ids


class ListaAleatoriaTests(BaseAleatorioTestCase):
    url = reverse('questoes:lista_questoes')

    def test_botao_ao_lado_do_ultima_liga_a_ordem_aleatoria_mantendo_os_filtros(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'page': 3})
        self.assertIsNone(resposta.context['aleatorio'])
        url_aleatorio = resposta.context['url_aleatorio']
        self.assertTrue(url_aleatorio.startswith(f'{self.url}?banca={self.fgv.id}&aleatorio='))
        self.assertNotIn('page=', url_aleatorio)
        self.assertContains(resposta, 'class="btn-limpar btn-aleatorio"')
        # Só o símbolo aparece (sem "ligado"/"desligado"); o nome fica para leitores de tela
        self.assertContains(
            resposta, '<span aria-hidden="true">🔀</span><span class="visualmente-oculto">Aleatório</span>', html=True,
        )
        # Na paginação, logo depois do "Última" (e não mais junto do "Limpar")
        html = resposta.content.decode()
        paginacao = html[html.index('<nav class="paginacao"'):]
        self.assertLess(paginacao.index('Última'), paginacao.index('btn-aleatorio'))
        self.assertNotIn('btn-aleatorio', html[:html.index('<nav class="paginacao"')])
        self.assertNotContains(resposta, 'name="aleatorio"')

    def test_cada_clique_sorteia_uma_semente_nova(self):
        urls = {self.client.get(self.url).context['url_aleatorio'] for _ in range(5)}
        self.assertGreater(len(urls), 1)

    def test_mostra_todas_as_questoes_uma_vez_na_ordem_sorteada(self):
        ordem = self.ordem_exibida(self.url, len(self.todas), aleatorio=SEMENTE)
        self.assertEqual(ordem, embaralhados(self.todas))
        self.assertNotEqual(ordem, [questao.pk for questao in sorted(self.todas, key=lambda q: -q.ano)])
        # Mesma semente, mesma ordem: "Próxima" segue a ordem sorteada
        self.assertEqual(self.ordem_exibida(self.url, len(self.todas), aleatorio=SEMENTE), ordem)

    def test_numero_exibido_e_o_da_questao_na_ordem_normal(self):
        # Ligado, "Questão X de N" mostra o número da questão sorteada (ex: da 11 para a 15), e não 1, 2, 3...
        normal = [q.pk for q in sorted(self.todas, key=lambda q: (-q.ano, q.pk))]
        sorteada = embaralhados(self.todas)
        for pagina in (1, 2, 3):
            with self.subTest(pagina=pagina):
                resposta = self.client.get(self.url, {'aleatorio': SEMENTE, 'page': pagina})
                numero = normal.index(sorteada[pagina - 1]) + 1
                self.assertContains(resposta, f'Questão {numero} de {len(self.todas)}')
        # Desligado, continua sendo a posição na ordem normal
        self.assertContains(self.client.get(self.url, {'page': 2}), f'Questão 2 de {len(self.todas)}')

    def test_respeita_os_filtros(self):
        fgv = [questao for questao in self.todas if questao.banca == self.fgv]
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'aleatorio': SEMENTE})
        self.assertEqual(resposta.context['pagina'].paginator.count, len(fgv))
        ordem = self.ordem_exibida(self.url, len(fgv), banca=self.fgv.id, aleatorio=SEMENTE)
        self.assertEqual(ordem, embaralhados(fgv))

    def test_ligado_o_botao_volta_a_ordem_normal_e_a_semente_segue_com_os_filtros(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'aleatorio': SEMENTE})
        self.assertEqual(resposta.context['aleatorio'], SEMENTE)
        self.assertEqual(resposta.context['url_aleatorio'], f'{self.url}?banca={self.fgv.id}')
        self.assertContains(resposta, 'class="btn-limpar btn-aleatorio ativo"')
        # Mudar um filtro reenvia o formulário: a ordem continua aleatória
        self.assertContains(resposta, f'<input type="hidden" name="aleatorio" value="{SEMENTE}">', html=True)
        # O "Novo simulado" leva a ordem aleatória junto
        self.assertEqual(
            resposta.context['url_novo_simulado'],
            f"{reverse('questoes:novo_simulado')}?banca={self.fgv.id}&aleatorio={SEMENTE}",
        )

    def test_semente_invalida_e_ignorada(self):
        for valor in ('abc', '0', '-5', str(2**31), ''):
            with self.subTest(valor=valor):
                resposta = self.client.get(self.url, {'aleatorio': valor})
                self.assertEqual(resposta.status_code, 200)
                self.assertIsNone(resposta.context['aleatorio'])

    def test_meu_desempenho_nao_tem_o_botao(self):
        resposta = self.client.get(reverse('usuarios:dashboard'))
        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, 'btn-aleatorio')


class NovoSimuladoAleatorioTests(BaseAleatorioTestCase):
    url = reverse('questoes:novo_simulado')
    criar = reverse('questoes:criar_simulado')

    def test_sem_paginacao_o_botao_fica_junto_dos_filtros(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id})
        self.assertTrue(resposta.context['url_aleatorio'].startswith(f'{self.url}?banca={self.fgv.id}&aleatorio='))
        self.assertContains(resposta, 'class="btn-limpar btn-aleatorio"')

    def test_ligado_o_formulario_de_criacao_leva_a_semente(self):
        resposta = self.client.get(self.url, {'aleatorio': SEMENTE})
        self.assertContains(resposta, 'em ordem aleatória')
        # Um campo no formulário dos filtros e outro no de criação
        self.assertContains(resposta, f'<input type="hidden" name="aleatorio" value="{SEMENTE}">', count=2, html=True)

    def test_cria_o_simulado_ja_embaralhado(self):
        self.client.post(self.criar, {'banca': self.fgv.id, 'aleatorio': SEMENTE})
        self.assertEqual(Simulado.objects.get().semente, SEMENTE)

    def test_sem_o_botao_cria_na_ordem_normal(self):
        self.client.post(self.criar, {'banca': self.fgv.id, 'aleatorio': 'abc'})
        self.assertIsNone(Simulado.objects.get().semente)

    def test_sem_questoes_volta_para_a_tela_com_a_ordem_aleatoria(self):
        resposta = self.client.post(self.criar, {'banca': self.fgv.id, 'ano': 1990, 'aleatorio': SEMENTE})
        self.assertRedirects(
            resposta, f'{self.url}?banca={self.fgv.id}&ano=1990&aleatorio={SEMENTE}', fetch_redirect_response=False,
        )


class SimuladoAleatorioTests(BaseAleatorioTestCase):
    def url(self, simulado):
        return reverse('questoes:simulado_detalhe', args=[simulado.id])

    def alternar(self, simulado):
        return self.client.post(reverse('questoes:alternar_ordem_simulado', args=[simulado.id]))

    def test_simulado_com_semente_mostra_as_questoes_embaralhadas(self):
        simulado = self.criar_simulado(*self.todas)
        simulado.semente = SEMENTE
        simulado.save()
        self.assertEqual(self.ordem_exibida(self.url(simulado), len(self.todas)), embaralhados(self.todas))

    def test_botao_liga_e_desliga_a_ordem_aleatoria(self):
        simulado = self.criar_simulado(*self.todas)
        self.assertContains(self.client.get(self.url(simulado)), 'aria-pressed="false"')

        resposta = self.alternar(simulado)
        self.assertRedirects(resposta, self.url(simulado), fetch_redirect_response=False)
        simulado.refresh_from_db()
        self.assertIsNotNone(simulado.semente)
        resposta = self.client.get(self.url(simulado))
        self.assertContains(resposta, 'aria-pressed="true"')
        self.assertContains(resposta, 'Questões em ordem aleatória.')
        self.assertEqual(
            self.ordem_exibida(self.url(simulado), len(self.todas)), embaralhados(self.todas, simulado.semente),
        )

        self.alternar(simulado)
        simulado.refresh_from_db()
        self.assertIsNone(simulado.semente)
        self.assertContains(self.client.get(self.url(simulado)), 'Questões de volta à ordem normal.')

    def test_respostas_dadas_continuam_no_simulado(self):
        simulado = self.criar_simulado(self.q1, self.q2)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        self.alternar(simulado)
        self.assertEqual(self.client.get(self.url(simulado)).context['respondidas'], 1)

    def test_so_o_dono_e_so_por_post(self):
        simulado = self.criar_simulado(self.q1, usuario=self.outro)
        self.assertEqual(self.alternar(simulado).status_code, 404)
        meu = self.criar_simulado(self.q1)
        url = reverse('questoes:alternar_ordem_simulado', args=[meu.id])
        self.assertEqual(self.client.get(url).status_code, 405)


class SemAleatorioOrdemNormalTests(BaseAleatorioTestCase):
    """Com o botão desligado, nenhuma tela embaralha: ano mais recente primeiro, depois a ordem de cadastro."""

    def ordem_normal(self, questoes):
        return [q.pk for q in sorted(questoes, key=lambda q: (-q.ano, q.pk))]

    def test_lista_desligada_mostra_a_ordem_normal(self):
        url = reverse('questoes:lista_questoes')
        self.assertEqual(self.ordem_exibida(url, len(self.todas)), self.ordem_normal(self.todas))
        self.assertContains(self.client.get(url), 'class="btn-limpar btn-aleatorio"')

    def test_simulado_desligado_mostra_a_ordem_normal(self):
        simulado = self.criar_simulado(*self.todas)
        url = reverse('questoes:simulado_detalhe', args=[simulado.id])
        self.assertEqual(self.ordem_exibida(url, len(self.todas)), self.ordem_normal(self.todas))
        resposta = self.client.get(url)
        self.assertContains(resposta, 'class="btn-limpar btn-aleatorio"')
        # No simulado o botão também saiu do topo e foi para a paginação
        html = resposta.content.decode()
        self.assertNotIn('btn-aleatorio', html[:html.index('<nav class="paginacao"')])

    def test_simulado_ligado_fica_destacado(self):
        simulado = self.criar_simulado(*self.todas)
        simulado.semente = SEMENTE
        simulado.save()
        resposta = self.client.get(reverse('questoes:simulado_detalhe', args=[simulado.id]))
        self.assertContains(resposta, 'class="btn-limpar btn-aleatorio ativo"')
