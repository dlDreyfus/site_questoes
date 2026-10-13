"""Botão "Atualizar questões": acrescenta ao simulado as questões cadastradas depois que atendem aos filtros."""
from django.urls import reverse

from .models import Simulado
from .tests_simulados import BaseSimuladosTestCase


class AtualizarSimuladoTests(BaseSimuladosTestCase):
    criar = reverse('questoes:criar_simulado')

    def criar_pelo_site(self, **filtros):
        self.client.post(self.criar, filtros)
        return Simulado.objects.latest('pk')

    def atualizar(self, simulado):
        return self.client.post(reverse('questoes:atualizar_simulado', args=[simulado.id]), follow=True)

    def test_criar_grava_os_filtros(self):
        simulado = self.criar_pelo_site(banca=self.fgv.id, busca='Enunciado')
        self.assertEqual(simulado.filtros, {'busca': ['Enunciado'], 'banca': [self.fgv.id]})

    def test_inclui_as_questoes_novas_que_atendem_aos_filtros(self):
        simulado = self.criar_pelo_site(banca=self.fgv.id)
        self.assertEqual(set(simulado.questoes.all()), {self.q1, self.q3})
        nova_fgv = self.criar_questao(self.fgv, 2021, self.licitacoes)
        nova_cebraspe = self.criar_questao(self.cebraspe, 2021, self.licitacoes)

        resposta = self.atualizar(simulado)
        self.assertContains(resposta, '1 questão nova foi incluída no simulado.')
        self.assertEqual(set(simulado.questoes.all()), {self.q1, self.q3, nova_fgv})
        self.assertNotIn(nova_cebraspe, simulado.questoes.all())

    def test_mantem_as_respostas_e_nao_remove_questoes(self):
        simulado = self.criar_pelo_site(banca=self.fgv.id)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        # Mesmo que uma questão deixe de atender aos filtros, ela continua no simulado
        self.q3.banca = self.cebraspe
        self.q3.save()
        self.criar_questao(self.fgv, 2021, self.licitacoes)
        self.atualizar(simulado)
        self.assertIn(self.q3, simulado.questoes.all())
        self.assertEqual(simulado.questoes.count(), 3)
        self.assertEqual(simulado.resolucoes.count(), 1)

    def test_sem_questoes_novas(self):
        simulado = self.criar_pelo_site(banca=self.fgv.id)
        resposta = self.atualizar(simulado)
        self.assertContains(resposta, 'Nenhuma questão nova atende aos filtros deste simulado.')
        self.assertEqual(simulado.questoes.count(), 2)

    def test_sem_filtros_inclui_todas_as_novas(self):
        simulado = self.criar_pelo_site()
        nova = self.criar_questao(self.cebraspe, 2021, self.licitacoes)
        self.atualizar(simulado)
        self.assertIn(nova, simulado.questoes.all())

    def test_busca_gravada_continua_valendo(self):
        simulado = self.criar_pelo_site(busca='CEBRASPE')
        self.assertEqual(set(simulado.questoes.all()), {self.q2})
        nova = self.criar_questao(self.cebraspe, 2021, self.licitacoes)
        self.criar_questao(self.fgv, 2021, self.licitacoes)
        self.atualizar(simulado)
        self.assertEqual(set(simulado.questoes.all()), {self.q2, nova})

    def test_ainda_nao_resolvi_considera_o_historico_atual(self):
        self.responder(self.usuario, self.q1, True)
        simulado = self.criar_pelo_site(situacao='nao_resolvidas')
        self.assertEqual(set(simulado.questoes.all()), {self.q2, self.q3})
        nova = self.criar_questao(self.fgv, 2021, self.licitacoes)
        self.atualizar(simulado)
        self.assertEqual(set(simulado.questoes.all()), {self.q2, self.q3, nova})

    def test_simulado_antigo_sem_filtros_gravados(self):
        antigo = self.criar_simulado(self.q1)
        self.assertIsNone(antigo.filtros)
        self.assertNotContains(
            self.client.get(reverse('questoes:simulado_detalhe', args=[antigo.id])), 'Atualizar questões',
        )
        self.criar_questao(self.fgv, 2021, self.licitacoes)
        resposta = self.atualizar(antigo)
        self.assertContains(resposta, 'não pode ser atualizado')
        self.assertEqual(antigo.questoes.count(), 1)

    def test_botao_aparece_no_simulado_com_filtros(self):
        simulado = self.criar_pelo_site(banca=self.fgv.id)
        resposta = self.client.get(reverse('questoes:simulado_detalhe', args=[simulado.id]))
        self.assertContains(resposta, f'action="{reverse("questoes:atualizar_simulado", args=[simulado.id])}"')

    def test_so_o_dono_e_so_por_post(self):
        alheio = self.criar_simulado(self.q1, usuario=self.outro)
        alheio.filtros = {}
        alheio.save()
        url = reverse('questoes:atualizar_simulado', args=[alheio.id])
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(alheio.questoes.count(), 1)
        meu = self.criar_pelo_site()
        self.assertEqual(self.client.get(reverse('questoes:atualizar_simulado', args=[meu.id])).status_code, 405)

    def test_copia_de_simulado_publico_leva_os_filtros(self):
        self.client.force_login(self.outro)
        original = self.criar_pelo_site(banca=self.fgv.id)
        original.publico = True
        original.save()
        self.client.force_login(self.usuario)
        self.client.post(reverse('questoes:fazer_simulado', args=[original.id]))
        copia = self.usuario.simulados.get()
        self.assertEqual(copia.filtros, original.filtros)
        nova = self.criar_questao(self.fgv, 2021, self.licitacoes)
        self.atualizar(copia)
        self.assertIn(nova, copia.questoes.all())
        # A cópia é atualizada sozinha: o original só muda quando o dono atualiza o dele
        self.assertNotIn(nova, original.questoes.all())
