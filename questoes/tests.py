from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Alternativa, Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Topico
from .views import QUESTOES_POR_PAGINA


class BaseQuestoesTestCase(TestCase):
    # Dados criados uma única vez para toda a classe de testes (mais rápido que setUp)
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe')
        cls.orgao = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.cargo = Cargo.objects.create(nome='Auditor')
        cls.outro_orgao = Orgao.objects.create(nome='Tribunal de Contas do Estado do RJ', sigla='TCE-RJ')
        cls.outro_cargo = Cargo.objects.create(nome='Analista')
        cls.direito = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.topico = Topico.objects.create(nome='Licitações', materia=cls.direito)
        cls.outro_topico_mesma_materia = Topico.objects.create(nome='Contratos', materia=cls.direito)
        cls.topico_constitucional = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)

        cls.questao = cls.criar_questao(ano=2024, banca=cls.fgv, enunciado='Questão da FGV')
        cls.questao.topicos.add(cls.topico)
        cls.errada = Alternativa.objects.create(questao=cls.questao, ordem=1, texto='Errada')
        cls.certa = Alternativa.objects.create(questao=cls.questao, ordem=2, texto='Certa', is_correta=True)

        cls.outra_questao = cls.criar_questao(
            ano=2023, banca=cls.cebraspe, enunciado='Questão do Cebraspe', orgao=cls.outro_orgao, cargo=cls.outro_cargo,
        )
        cls.outra_questao.topicos.add(cls.outro_topico_mesma_materia)
        cls.certa_da_outra = Alternativa.objects.create(
            questao=cls.outra_questao, ordem=1, texto='Certa da outra', is_correta=True,
        )

    @classmethod
    def criar_questao(cls, ano, banca, enunciado='Enunciado', orgao=None, cargo=None):
        return Questao.objects.create(
            enunciado=enunciado, ano=ano, banca=banca, orgao=orgao or cls.orgao, cargo=cargo or cls.cargo,
        )

    def setUp(self):
        self.client.force_login(self.usuario)


class ListaQuestoesTests(BaseQuestoesTestCase):
    url = reverse('questoes:lista_questoes')

    def test_exige_login(self):
        self.client.logout()
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, f"{reverse('usuarios:login')}?next={self.url}")

    def test_lista_todas_as_questoes(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Questão da FGV')
        self.assertContains(resposta, 'Questão do Cebraspe')

    def test_cada_filtro_separa_as_questoes(self):
        casos = (
            {'banca': self.fgv.id},
            {'orgao': self.orgao.id},
            {'cargo': self.cargo.id},
            {'topico': self.topico.id},
            {'ano': 2024},
        )
        for parametros in casos:
            with self.subTest(parametros=parametros):
                resposta = self.client.get(self.url, parametros)
                self.assertEqual(list(resposta.context['questoes']), [self.questao])

    def test_filtro_por_materia_inclui_todos_os_topicos_dela(self):
        resposta = self.client.get(self.url, {'materia': self.direito.id})
        self.assertEqual(list(resposta.context['questoes']), [self.questao, self.outra_questao])
        resposta = self.client.get(self.url, {'materia': self.constitucional.id})
        self.assertEqual(list(resposta.context['questoes']), [])

    def test_filtros_combinados(self):
        resposta = self.client.get(self.url, {'orgao': self.outro_orgao.id, 'cargo': self.outro_cargo.id})
        self.assertEqual(list(resposta.context['questoes']), [self.outra_questao])
        resposta = self.client.get(self.url, {'orgao': self.orgao.id, 'cargo': self.outro_cargo.id})
        self.assertEqual(list(resposta.context['questoes']), [])

    def test_dropdowns_mostram_as_opcoes_e_mantem_a_selecao(self):
        resposta = self.client.get(self.url, {'orgao': self.outro_orgao.id, 'cargo': self.cargo.id})
        self.assertContains(resposta, f'<option value="{self.outro_orgao.id}" selected>TCE-RJ</option>', html=True)
        self.assertContains(resposta, f'<option value="{self.cargo.id}" selected>Auditor</option>', html=True)
        # Tópicos agrupados por matéria
        self.assertContains(resposta, '<optgroup label="Direito Constitucional">')

    def test_com_materia_escolhida_so_aparecem_os_topicos_dela(self):
        resposta = self.client.get(self.url, {'materia': self.direito.id})
        self.assertEqual(
            set(resposta.context['topicos']), {self.topico, self.outro_topico_mesma_materia},
        )

    def test_topico_de_outra_materia_e_ignorado(self):
        # Ex: o usuário escolheu um tópico de Constitucional e depois trocou a matéria para Administrativo
        resposta = self.client.get(self.url, {'materia': self.direito.id, 'topico': self.topico_constitucional.id})
        self.assertIsNone(resposta.context['topico_selecionado'])
        self.assertEqual(list(resposta.context['questoes']), [self.questao, self.outra_questao])

    def test_conta_os_filtros_ativos(self):
        casos = (
            ({}, 0),
            ({'banca': self.fgv.id}, 1),
            ({'banca': self.fgv.id, 'orgao': self.orgao.id, 'ano': 2024}, 3),
            # Valor inválido é ignorado, então não conta como filtro ativo
            ({'banca': 'abc'}, 0),
        )
        for parametros, esperado in casos:
            with self.subTest(parametros=parametros):
                resposta = self.client.get(self.url, parametros)
                self.assertEqual(resposta.context['filtros_ativos'], esperado)
                self.assertContains(resposta, f'data-filtros-ativos="{esperado}"')

    def test_botao_filtros_comeca_escondido_e_mostra_o_contador(self):
        # 'hidden' no HTML: sem JavaScript o botão não aparece e os filtros ficam sempre visíveis
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'class="btn-filtros"')
        self.assertContains(resposta, 'aria-controls="filtros" aria-expanded="true" hidden')
        self.assertNotContains(resposta, 'filtros-contador')
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'ano': 2024})
        self.assertContains(resposta, '<span class="filtros-contador">2 ativos</span>', html=True)

    def test_card_mostra_orgao_e_cargo(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id})
        self.assertContains(resposta, '<strong>Órgão:</strong> TCU', html=False)
        self.assertContains(resposta, '<strong>Cargo:</strong> Auditor', html=False)

    def test_filtros_invalidos_sao_ignorados(self):
        # '²' passa em str.isdigit() mas quebra int(): antes gerava erro 500
        for valor in ('abc', '²', '1a', ''):
            with self.subTest(valor=valor):
                parametros = dict.fromkeys(('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano'), valor)
                resposta = self.client.get(self.url, parametros)
                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, 'Questão da FGV')

    def test_questoes_mais_recentes_primeiro(self):
        resposta = self.client.get(self.url)
        self.assertEqual(list(resposta.context['questoes']), [self.questao, self.outra_questao])

    def test_alternativas_na_ordem_definida(self):
        # Criada por último, mas com ordem 0: deve aparecer primeiro
        primeira = Alternativa.objects.create(questao=self.questao, ordem=0, texto='Primeira')
        self.assertEqual(list(self.questao.alternativas.all()), [primeira, self.errada, self.certa])

    def test_paginacao_mantem_filtros(self):
        for i in range(QUESTOES_POR_PAGINA + 1):
            self.criar_questao(ano=2020, banca=self.fgv, enunciado=f'Extra {i}')
        resposta = self.client.get(self.url, {'banca': self.fgv.id})
        pagina = resposta.context['pagina']
        self.assertEqual(pagina.paginator.count, QUESTOES_POR_PAGINA + 2)
        self.assertEqual(len(pagina.object_list), QUESTOES_POR_PAGINA)
        self.assertContains(resposta, f'?banca={self.fgv.id}&amp;page=2')

    def test_pagina_invalida_nao_quebra(self):
        for pagina in ('abc', '999', '-1'):
            with self.subTest(pagina=pagina):
                self.assertEqual(self.client.get(self.url, {'page': pagina}).status_code, 200)


class ResponderQuestaoTests(BaseQuestoesTestCase):
    def responder(self, dados, questao=None):
        url = reverse('questoes:responder_questao', args=[(questao or self.questao).id])
        return self.client.post(url, dados, follow=True)

    def mensagens(self, resposta):
        return [(m.level_tag, str(m)) for m in resposta.context['messages']]

    def test_exige_login(self):
        self.client.logout()
        resposta = self.client.post(reverse('questoes:responder_questao', args=[self.questao.id]))
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse('usuarios:login'), resposta.url)
        self.assertFalse(HistoricoResolucao.objects.exists())

    def test_so_aceita_post(self):
        resposta = self.client.get(reverse('questoes:responder_questao', args=[self.questao.id]))
        self.assertEqual(resposta.status_code, 405)

    def test_resposta_certa(self):
        resposta = self.responder({'alternativa': self.certa.id})
        self.assertEqual(self.mensagens(resposta), [('success', 'Resposta Correta! Excelente.')])
        historico = HistoricoResolucao.objects.get()
        self.assertEqual(
            (historico.usuario, historico.questao, historico.alternativa_escolhida, historico.acertou),
            (self.usuario, self.questao, self.certa, True),
        )

    def test_resposta_errada_mostra_a_correta(self):
        resposta = self.responder({'alternativa': self.errada.id})
        self.assertEqual(self.mensagens(resposta), [('error', 'Resposta Incorreta. A correta é: Certa')])
        self.assertFalse(HistoricoResolucao.objects.get().acertou)

    def test_alternativa_invalida_nao_grava_historico(self):
        # Vazia, texto, e a alternativa correta de OUTRA questão (tentativa de fraude)
        for dados in ({}, {'alternativa': 'abc'}, {'alternativa': self.certa_da_outra.id}):
            with self.subTest(dados=dados):
                resposta = self.responder(dados)
                self.assertEqual(self.mensagens(resposta)[0][0], 'warning')
        self.assertFalse(HistoricoResolucao.objects.exists())

    def test_volta_para_a_pagina_de_origem(self):
        url = reverse('questoes:responder_questao', args=[self.questao.id])
        resposta = self.client.post(url, {'alternativa': self.certa.id, 'next': '/?ano=2024&page=1'})
        self.assertEqual(resposta.url, f'/?ano=2024&page=1#questao-{self.questao.id}')

    def test_ignora_next_externo(self):
        url = reverse('questoes:responder_questao', args=[self.questao.id])
        resposta = self.client.post(url, {'alternativa': self.certa.id, 'next': 'https://site-malicioso.com/'})
        self.assertEqual(resposta.url, f"{reverse('questoes:lista_questoes')}#questao-{self.questao.id}")


class ModelsTests(BaseQuestoesTestCase):
    def test_banco_impede_duas_alternativas_corretas(self):
        with self.assertRaises(IntegrityError):
            Alternativa.objects.create(questao=self.questao, texto='Outra certa', is_correta=True)

    def test_apagar_alternativa_preserva_historico(self):
        HistoricoResolucao.objects.create(
            usuario=self.usuario, questao=self.questao, alternativa_escolhida=self.errada, acertou=False,
        )
        self.errada.delete()
        historico = HistoricoResolucao.objects.get()
        self.assertIsNone(historico.alternativa_escolhida)
        self.assertFalse(historico.acertou)


class AdminAlternativasTests(BaseQuestoesTestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        self.client.force_login(admin)
        self.url = reverse('admin:questoes_questao_change', args=[self.questao.id])

    def dados_formulario(self, alternativas):
        # Monta o POST da tela da questão no admin; 'alternativas' é uma lista de dicts por linha do inline
        dados = {
            'enunciado': self.questao.enunciado, 'tipo': self.questao.tipo, 'ano': self.questao.ano,
            'banca': self.fgv.id, 'orgao': self.orgao.id, 'cargo': self.cargo.id, 'topicos': [self.topico.id],
            'alternativas-TOTAL_FORMS': len(alternativas), 'alternativas-INITIAL_FORMS': 2,
            'alternativas-MIN_NUM_FORMS': 0, 'alternativas-MAX_NUM_FORMS': 1000,
        }
        for i, alternativa in enumerate(alternativas):
            for campo, valor in alternativa.items():
                if valor is not False:
                    dados[f'alternativas-{i}-{campo}'] = valor
            dados[f'alternativas-{i}-questao'] = self.questao.id
        return dados

    def linha(self, alternativa=None, texto='Nova', ordem=3, is_correta=False, DELETE=False):
        return {
            'id': alternativa.id if alternativa else '', 'ordem': ordem,
            'texto': alternativa.texto if alternativa else texto, 'is_correta': 'on' if is_correta else False,
            'DELETE': 'on' if DELETE else False,
        }

    def test_trocar_a_alternativa_correta(self):
        # Correta passa da 2ª para a 1ª: exige desmarcar a antiga antes de salvar a nova
        resposta = self.client.post(self.url, self.dados_formulario([
            self.linha(self.errada, ordem=1, is_correta=True),
            self.linha(self.certa, ordem=2, is_correta=False),
        ]))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(list(self.questao.alternativas.filter(is_correta=True)), [self.errada])

    def test_apagar_a_correta_e_marcar_outra(self):
        resposta = self.client.post(self.url, self.dados_formulario([
            self.linha(self.errada, ordem=1, is_correta=True),
            self.linha(self.certa, ordem=2, is_correta=True, DELETE=True),
        ]))
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(list(self.questao.alternativas.all()), [self.errada])
        self.assertTrue(self.questao.alternativas.get().is_correta)

    def test_exige_exatamente_uma_correta(self):
        casos = {
            'nenhuma': [self.linha(self.errada, ordem=1), self.linha(self.certa, ordem=2)],
            'duas': [
                self.linha(self.errada, ordem=1, is_correta=True),
                self.linha(self.certa, ordem=2, is_correta=True),
            ],
        }
        for nome, linhas in casos.items():
            with self.subTest(caso=nome):
                resposta = self.client.post(self.url, self.dados_formulario(linhas))
                self.assertEqual(resposta.status_code, 200)
                self.assertContains(resposta, 'Marque exatamente uma alternativa como correta.')
        # Nada foi alterado no banco
        self.assertEqual(list(self.questao.alternativas.filter(is_correta=True)), [self.certa])

    def test_historico_e_somente_leitura(self):
        self.assertEqual(self.client.get(reverse('admin:questoes_historicoresolucao_add')).status_code, 403)
        self.assertEqual(self.client.get(reverse('admin:questoes_historicoresolucao_changelist')).status_code, 200)
