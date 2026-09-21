"""Subcabeçalho (templates/base.html) com a quantidade de questões cadastradas."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse

from .tests import BaseQuestoesTestCase


class SubcabecalhoTests(BaseQuestoesTestCase):
    # Dados-base: 2 questões (q1: FGV/2024/Licitações; q2: Cebraspe/2023/Contratos, as duas em Direito Administrativo)
    lista = reverse('questoes:lista_questoes')
    dashboard = reverse('usuarios:dashboard')

    def test_lista_sem_filtros_mostra_o_total(self):
        resposta = self.client.get(self.lista)
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas</p>')
        self.assertNotContains(resposta, 'com os filtros escolhidos')

    def test_lista_com_filtros_conta_so_as_questoes_filtradas(self):
        resposta = self.client.get(self.lista, {'banca': self.fgv.id})
        self.assertContains(resposta, '<strong>1</strong> questão cadastrada com os filtros escolhidos</p>')
        resposta = self.client.get(self.lista, {'banca': self.fgv.id, 'ano': 2023})
        self.assertContains(resposta, '<strong>0</strong> questões cadastradas com os filtros escolhidos</p>')

    def test_questao_com_dois_topicos_da_mesma_materia_conta_uma_vez(self):
        self.questao.topicos.add(self.outro_topico_mesma_materia)
        resposta = self.client.get(self.lista, {'materia': self.direito.id})
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas com os filtros escolhidos</p>')

    def test_a_contagem_nao_depende_da_pagina(self):
        for i in range(12):
            self.criar_questao(ano=2020, banca=self.fgv, enunciado=f'Extra {i}')
        resposta = self.client.get(self.lista, {'banca': self.fgv.id, 'page': 2})
        self.assertContains(resposta, '<strong>13</strong> questões cadastradas com os filtros escolhidos</p>')

    def test_lista_nao_repete_a_contagem_no_corpo_da_pagina(self):
        self.assertNotContains(self.client.get(self.lista), 'questões encontradas')

    def test_painel_conta_as_questoes_cadastradas_e_nao_so_as_respondidas(self):
        # O usuário não respondeu nada, mas o subcabeçalho conta as questões cadastradas
        resposta = self.client.get(self.dashboard)
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas</p>')
        resposta = self.client.get(self.dashboard, {'banca': self.cebraspe.id})
        self.assertContains(resposta, '<strong>1</strong> questão cadastrada com os filtros escolhidos</p>')

    def test_painel_ignora_filtros_que_ele_nao_tem(self):
        # O painel só filtra por banca, cargo, matéria e tópico: órgão e ano não entram na conta
        resposta = self.client.get(self.dashboard, {'orgao': self.outro_orgao.id, 'ano': 1999})
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas</p>')
        self.assertNotContains(resposta, 'com os filtros escolhidos')

    def test_paginas_sem_filtros_mostram_o_total_geral(self):
        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        self.client.force_login(admin)
        resposta = self.client.get(reverse('questoes:importar_questoes'))
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas</p>')
        # Filtros da URL não valem onde não há filtros
        resposta = self.client.get(reverse('questoes:importar_questoes'), {'banca': self.fgv.id})
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas</p>')
        self.assertNotContains(resposta, 'com os filtros escolhidos')

    def test_total_geral_acompanha_o_singular(self):
        self.outra_questao.delete()
        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        self.client.force_login(admin)
        resposta = self.client.get(reverse('questoes:importar_questoes'))
        self.assertContains(resposta, '<strong>1</strong> questão cadastrada</p>')

    def test_total_geral_so_e_consultado_onde_nao_ha_filtros_e_uma_unica_vez(self):
        # O context processor entrega o total geral de forma preguiçosa: a lista e o painel usam a
        # contagem própria (com filtros) e não podem gastar uma consulta com o total geral
        chamadas = []

        def contar():
            chamadas.append(1)
            return 99

        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        with patch('questoes.context_processors.Questao') as questao_falsa:
            questao_falsa.objects.count = contar
            self.client.get(self.lista, {'banca': self.fgv.id})
            self.client.get(self.dashboard)
            self.assertEqual(chamadas, [])

            self.client.force_login(admin)
            resposta = self.client.get(reverse('questoes:importar_questoes'))
            self.assertContains(resposta, '<strong>99</strong> questões cadastradas</p>')
            self.assertEqual(chamadas, [1])

    def test_visitante_sem_login_nao_ve_o_subcabecalho(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('usuarios:login')), 'subcabecalho')
