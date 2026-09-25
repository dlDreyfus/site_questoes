"""Filtros com várias opções marcadas ao mesmo tempo e busca textual."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .filtros import CAMPOS_SIMULADO, FiltrosQuestao
from .models import (
    Alternativa, Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Simulado, Topico,
)


class BaseSelecaoMultiplaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe', sigla='CEBRASPE')
        cls.vunesp = Banca.objects.create(nome='Vunesp', sigla='VUNESP')
        cls.tcu = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.tce = Orgao.objects.create(nome='Tribunal de Contas do Estado do RJ', sigla='TCE-RJ')
        cls.auditor = Cargo.objects.create(nome='Auditor')
        cls.analista = Cargo.objects.create(nome='Analista')
        cls.administrativo = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.licitacoes = Topico.objects.create(nome='Licitações', materia=cls.administrativo)
        cls.contratos = Topico.objects.create(nome='Contratos', materia=cls.administrativo)
        cls.direitos = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)

        def questao(codigo, enunciado, banca, orgao, cargo, ano, *topicos, alternativas=()):
            q = Questao.objects.create(
                codigo=codigo, enunciado=enunciado, ano=ano, banca=banca, orgao=orgao, cargo=cargo,
            )
            q.topicos.add(*topicos)
            for ordem, texto in enumerate(alternativas, start=1):
                Alternativa.objects.create(questao=q, ordem=ordem, texto=texto, is_correta=ordem == 1)
            return q

        cls.q1 = questao('FGV-TCU-2024-001', 'Sobre o pregão eletrônico, assinale a correta.',
                         cls.fgv, cls.tcu, cls.auditor, 2024, cls.licitacoes,
                         alternativas=('Modalidade para bens comuns', 'Exige garantia da proposta'))
        cls.q2 = questao('CEB-TCE-2023-002', 'Sobre contratos administrativos, julgue o item.',
                         cls.cebraspe, cls.tce, cls.analista, 2023, cls.contratos)
        cls.q3 = questao('VUN-TCU-2022-003', 'Sobre direitos fundamentais e o pregão, julgue o item.',
                         cls.vunesp, cls.tcu, cls.analista, 2022, cls.direitos)

    def setUp(self):
        self.client.force_login(self.usuario)


class SelecaoMultiplaTests(BaseSelecaoMultiplaTestCase):
    url = reverse('questoes:lista_questoes')

    def questoes(self, **parametros):
        return set(self.client.get(self.url, parametros).context['questoes'])

    def test_varios_valores_no_mesmo_filtro_somam_as_questoes(self):
        casos = (
            ({'banca': [self.fgv.id, self.cebraspe.id]}, {self.q1, self.q2}),
            ({'orgao': [self.tcu.id, self.tce.id]}, {self.q1, self.q2, self.q3}),
            ({'cargo': [self.auditor.id]}, {self.q1}),
            ({'ano': [2024, 2022]}, {self.q1, self.q3}),
            ({'topico': [self.licitacoes.id, self.direitos.id]}, {self.q1, self.q3}),
            ({'materia': [self.administrativo.id, self.constitucional.id]}, {self.q1, self.q2, self.q3}),
        )
        for parametros, esperadas in casos:
            with self.subTest(parametros=parametros):
                self.assertEqual(self.questoes(**parametros), esperadas)

    def test_filtros_diferentes_continuam_combinados(self):
        # (FGV ou Vunesp) e 2022: só a q3
        self.assertEqual(self.questoes(banca=[self.fgv.id, self.vunesp.id], ano=[2022]), {self.q3})

    def test_topico_marcado_refina_so_a_materia_dele(self):
        # Administrativo só em Licitações, mais Constitucional inteira
        parametros = {
            'materia': [self.administrativo.id, self.constitucional.id], 'topico': [self.licitacoes.id],
        }
        self.assertEqual(self.questoes(**parametros), {self.q1, self.q3})

    def test_topico_de_materia_desmarcada_e_ignorado(self):
        resposta = self.client.get(self.url, {'materia': [self.constitucional.id], 'topico': [self.licitacoes.id]})
        self.assertEqual(resposta.context['selecionados']['topico'], ())
        self.assertEqual(set(resposta.context['questoes']), {self.q3})

    def test_cascata_oferece_as_opcoes_para_marcar_mais_valores(self):
        contexto = self.client.get(self.url, {'banca': [self.fgv.id, self.cebraspe.id]}).context
        # O próprio filtro continua oferecendo a Vunesp; os outros só o que as duas bancas têm
        self.assertEqual(set(contexto['bancas']), {self.fgv, self.cebraspe, self.vunesp})
        self.assertEqual(set(contexto['anos']), {2024, 2023})
        self.assertEqual(set(contexto['orgaos']), {self.tcu, self.tce})

    def test_com_materia_marcada_pode_marcar_outra(self):
        contexto = self.client.get(self.url, {'materia': [self.administrativo.id], 'topico': [self.licitacoes.id]}).context
        self.assertEqual(set(contexto['materias']), {self.administrativo, self.constitucional})
        self.assertEqual(set(contexto['topicos']), {self.licitacoes, self.contratos})

    def test_opcoes_marcadas_aparecem_marcadas(self):
        resposta = self.client.get(self.url, {'banca': [self.fgv.id, self.cebraspe.id]})
        for banca in (self.fgv, self.cebraspe):
            self.assertContains(
                resposta, f'<label class="filtro-opcao"><input type="checkbox" name="banca" value="{banca.id}" '
                f'checked> {banca.sigla}</label>', html=True,
            )
        self.assertContains(
            resposta, f'<label class="filtro-opcao"><input type="checkbox" name="banca" value="{self.vunesp.id}"> '
            'VUNESP</label>', html=True,
        )
        # Sem JavaScript, o resumo do filtro mostra quantas opções estão marcadas
        self.assertContains(resposta, '2 bancas')
        self.assertContains(resposta, '<span class="filtros-contador">1 ativo</span>', html=True)

    def test_valores_repetidos_ou_invalidos_sao_ignorados(self):
        filtros = FiltrosQuestao.da_requisicao({'banca': [str(self.fgv.id), 'abc', str(self.fgv.id), '']})
        self.assertEqual(filtros.banca, (self.fgv.id,))

    def test_paginacao_mantem_todos_os_valores(self):
        for i in range(10):
            Questao.objects.create(enunciado=f'Extra {i}', ano=2024, banca=self.cebraspe, orgao=self.tcu, cargo=self.auditor)
        resposta = self.client.get(self.url, {'banca': [self.fgv.id, self.cebraspe.id]})
        self.assertContains(resposta, f'banca={self.fgv.id}&amp;banca={self.cebraspe.id}&amp;page=2')

    def test_novo_simulado_recebe_todos_os_valores_da_lista(self):
        url = self.client.get(self.url, {'banca': [self.fgv.id, self.cebraspe.id], 'busca': 'sobre'}).context[
            'url_novo_simulado'
        ]
        self.assertEqual(
            url, f"{reverse('questoes:novo_simulado')}?busca=sobre&banca={self.fgv.id}&banca={self.cebraspe.id}",
        )


class BuscaTextualTests(BaseSelecaoMultiplaTestCase):
    url = reverse('questoes:lista_questoes')

    def questoes(self, busca, **outros):
        return set(self.client.get(self.url, {'busca': busca, **outros}).context['questoes'])

    def test_campo_de_busca_vem_antes_dos_filtros(self):
        conteudo = self.client.get(self.url, {'busca': 'pregão'}).content.decode()
        self.assertIn('name="busca"', conteudo)
        self.assertIn('value="pregão"', conteudo)
        self.assertLess(conteudo.index('name="busca"'), conteudo.index('name="banca"'))

    def test_busca_no_enunciado_no_codigo_e_nas_alternativas(self):
        self.assertEqual(self.questoes('pregão'), {self.q1, self.q3})
        self.assertEqual(self.questoes('CEB-TCE'), {self.q2})
        self.assertEqual(self.questoes('bens comuns'), {self.q1})

    def test_ignora_maiusculas_e_espacos_extras(self):
        self.assertEqual(self.questoes('  SOBRE   CONTRATOS  '), {self.q2})

    def test_todas_as_palavras_precisam_aparecer(self):
        self.assertEqual(self.questoes('pregão fundamentais'), {self.q3})
        self.assertEqual(self.questoes('pregão inexistente'), set())

    def test_questao_com_varias_alternativas_iguais_aparece_uma_vez(self):
        resposta = self.client.get(self.url, {'busca': 'e'})
        ids = [q.id for q in resposta.context['questoes']]
        self.assertEqual(len(ids), len(set(ids)))

    def test_busca_combina_com_os_filtros_e_restringe_a_cascata(self):
        self.assertEqual(self.questoes('pregão', banca=[self.vunesp.id]), {self.q3})
        contexto = self.client.get(self.url, {'busca': 'pregão'}).context
        self.assertEqual(set(contexto['bancas']), {self.fgv, self.vunesp})
        self.assertEqual(contexto['filtros_ativos'], 1)

    def test_busca_vazia_nao_filtra(self):
        self.assertEqual(self.questoes('   '), {self.q1, self.q2, self.q3})
        self.assertEqual(FiltrosQuestao.da_requisicao({'busca': '   '}).ativos, 0)

    def test_busca_muito_longa_e_cortada(self):
        filtros = FiltrosQuestao.da_requisicao({'busca': 'a' * 1000})
        self.assertEqual(len(filtros.busca), 200)

    def test_painel_de_desempenho_tambem_tem_busca(self):
        HistoricoResolucao.objects.create(
            usuario=self.usuario, questao=self.q1, alternativa_escolhida=self.q1.alternativas.first(), acertou=True,
        )
        resposta = self.client.get(reverse('usuarios:dashboard'), {'busca': 'contratos'})
        self.assertContains(resposta, 'name="busca"')
        self.assertEqual(resposta.context['total'], 0)
        resposta = self.client.get(reverse('usuarios:dashboard'), {'busca': 'pregão'})
        self.assertEqual(resposta.context['total'], 1)


class SimuladoComSelecaoMultiplaTests(BaseSelecaoMultiplaTestCase):
    def test_tela_reenvia_cada_valor_num_campo_oculto(self):
        resposta = self.client.get(
            reverse('questoes:novo_simulado'), {'banca': [self.fgv.id, self.vunesp.id], 'busca': 'pregão'},
        )
        for banca in (self.fgv, self.vunesp):
            self.assertContains(resposta, f'<input type="hidden" name="banca" value="{banca.id}">', html=True)
        self.assertContains(resposta, '<input type="hidden" name="busca" value="pregão">', html=True)
        self.assertContains(resposta, 'Criar simulado com 2 questões')

    def test_cria_simulado_com_varios_valores_e_descreve_todos(self):
        self.client.post(reverse('questoes:criar_simulado'), {
            'busca': 'sobre', 'banca': [self.fgv.id, self.cebraspe.id], 'ano': [2024, 2023],
        })
        simulado = Simulado.objects.get()
        self.assertEqual(set(simulado.questoes.all()), {self.q1, self.q2})
        self.assertEqual(simulado.descricao, 'Busca: "sobre" · Banca: FGV, CEBRASPE · Ano: 2024, 2023')

    def test_sem_questoes_volta_com_todos_os_valores(self):
        resposta = self.client.post(reverse('questoes:criar_simulado'), {
            'banca': [self.fgv.id, self.cebraspe.id], 'ano': [2022],
        })
        self.assertRedirects(
            resposta, f"{reverse('questoes:novo_simulado')}?banca={self.fgv.id}&banca={self.cebraspe.id}&ano=2022",
            fetch_redirect_response=False,
        )

    def test_as_duas_situacoes_juntas_somam_erradas_e_nao_resolvidas(self):
        HistoricoResolucao.objects.create(
            usuario=self.usuario, questao=self.q1, alternativa_escolhida=self.q1.alternativas.last(), acertou=False,
        )
        HistoricoResolucao.objects.create(
            usuario=self.usuario, questao=self.q2, alternativa_escolhida=None, acertou=True,
        )
        filtros = FiltrosQuestao.da_requisicao(
            {'situacao': ['erradas', 'nao_resolvidas']}, campos=CAMPOS_SIMULADO, usuario=self.usuario,
        )
        self.assertEqual(set(filtros.aplicar(Questao.objects.all())), {self.q1, self.q3})
        self.assertEqual(filtros.descricao(), 'Somente questões que errei ou Questões que ainda não resolvi')
