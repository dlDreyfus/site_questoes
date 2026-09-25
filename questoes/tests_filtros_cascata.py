"""Filtros em cascata: cada dropdown só oferece as opções que combinam com o que foi escolhido nos outros."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .filtros import FiltrosQuestao
from .models import Banca, Cargo, Materia, Orgao, Questao, Topico


class FiltrosEmCascataTests(TestCase):
    url = reverse('questoes:lista_questoes')

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe', sigla='CEBRASPE')
        cls.banca_sem_questoes = Banca.objects.create(nome='Vunesp', sigla='VUNESP')
        cls.tcu = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.tce = Orgao.objects.create(nome='Tribunal de Contas do Estado do RJ', sigla='TCE-RJ')
        cls.auditor = Cargo.objects.create(nome='Auditor')
        cls.analista = Cargo.objects.create(nome='Analista')
        cls.administrativo = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.contabilidade = Materia.objects.create(nome='Contabilidade')
        cls.licitacoes = Topico.objects.create(nome='Licitações', materia=cls.administrativo)
        cls.contratos = Topico.objects.create(nome='Contratos', materia=cls.administrativo)
        cls.direitos = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)
        cls.balanco = Topico.objects.create(nome='Balanço', materia=cls.contabilidade)

        def questao(banca, orgao, cargo, ano, *topicos):
            q = Questao.objects.create(enunciado='x', ano=ano, banca=banca, orgao=orgao, cargo=cargo)
            q.topicos.add(*topicos)
            return q

        # q1 tem tópicos de DUAS matérias: é o caso que mais facilmente furaria a cascata
        cls.q1 = questao(cls.fgv, cls.tcu, cls.auditor, 2024, cls.licitacoes, cls.direitos)
        cls.q2 = questao(cls.fgv, cls.tce, cls.analista, 2023, cls.contratos)
        cls.q3 = questao(cls.cebraspe, cls.tcu, cls.analista, 2022, cls.direitos)

    def setUp(self):
        self.client.force_login(self.usuario)

    @staticmethod
    def caixa(campo, valor, rotulo, marcada=False):
        """HTML de uma opção de filtro (caixa de marcação com o rótulo)."""
        return (
            f'<label class="filtro-opcao"><input type="checkbox" name="{campo}" value="{valor}"'
            f'{" checked" if marcada else ""}> {rotulo}</label>'
        )

    def opcoes(self, **filtros):
        """Opções que cada dropdown recebe para os filtros dados (conjuntos, para ignorar a ordem)."""
        contexto = self.client.get(self.url, filtros).context
        return {
            'banca': set(contexto['bancas']), 'orgao': set(contexto['orgaos']), 'cargo': set(contexto['cargos']),
            'materia': set(contexto['materias']), 'topico': set(contexto['topicos']), 'ano': set(contexto['anos']),
        }

    def test_sem_filtros_so_aparecem_opcoes_que_tem_questoes(self):
        opcoes = self.opcoes()
        self.assertEqual(opcoes['banca'], {self.fgv, self.cebraspe})
        self.assertEqual(opcoes['orgao'], {self.tcu, self.tce})
        self.assertEqual(opcoes['cargo'], {self.auditor, self.analista})
        self.assertEqual(opcoes['materia'], {self.administrativo, self.constitucional})
        self.assertEqual(opcoes['topico'], {self.licitacoes, self.contratos, self.direitos})
        self.assertEqual(opcoes['ano'], {2024, 2023, 2022})

    def test_escolher_uma_banca_filtra_os_demais_dropdowns(self):
        opcoes = self.opcoes(banca=self.cebraspe.id)
        self.assertEqual(opcoes['orgao'], {self.tcu})
        self.assertEqual(opcoes['cargo'], {self.analista})
        self.assertEqual(opcoes['materia'], {self.constitucional})
        self.assertEqual(opcoes['topico'], {self.direitos})
        self.assertEqual(opcoes['ano'], {2022})

    def test_cada_tipo_de_filtro_restringe_os_outros(self):
        casos = {
            'orgao': ({'orgao': self.tce.id}, {
                'banca': {self.fgv}, 'cargo': {self.analista}, 'materia': {self.administrativo},
                'topico': {self.contratos}, 'ano': {2023},
            }),
            'cargo': ({'cargo': self.auditor.id}, {
                'banca': {self.fgv}, 'orgao': {self.tcu}, 'materia': {self.administrativo, self.constitucional},
                'topico': {self.licitacoes, self.direitos}, 'ano': {2024},
            }),
            'ano': ({'ano': 2022}, {
                'banca': {self.cebraspe}, 'orgao': {self.tcu}, 'cargo': {self.analista},
                'materia': {self.constitucional}, 'topico': {self.direitos},
            }),
            'matéria': ({'materia': self.administrativo.id}, {
                'banca': {self.fgv}, 'orgao': {self.tcu, self.tce}, 'cargo': {self.auditor, self.analista},
                'topico': {self.licitacoes, self.contratos}, 'ano': {2024, 2023},
            }),
        }
        for nome, (filtros, esperado) in casos.items():
            with self.subTest(nome):
                opcoes = self.opcoes(**filtros)
                for campo, valores in esperado.items():
                    self.assertEqual(opcoes[campo], valores, campo)

    def test_o_proprio_dropdown_continua_com_as_opcoes_que_combinam_com_os_outros(self):
        # Escolhida a FGV, o dropdown de bancas continua oferecendo a Cebraspe (o usuário pode trocar)...
        self.assertEqual(self.opcoes(banca=self.fgv.id)['banca'], {self.fgv, self.cebraspe})
        # ...mas com o órgão TCE-RJ escolhido, só a FGV tem questões dele
        self.assertEqual(self.opcoes(banca=self.fgv.id, orgao=self.tce.id)['banca'], {self.fgv})

    def test_topico_limita_a_materia_ao_dono_dele(self):
        # q1 tem tópicos de duas matérias, mas escolher "Licitações" só combina com Administrativo:
        # oferecer Constitucional faria o tópico ser descartado ao escolhê-la
        opcoes = self.opcoes(topico=self.licitacoes.id)
        self.assertEqual(opcoes['materia'], {self.administrativo})
        self.assertEqual(opcoes['topico'], {self.licitacoes, self.contratos, self.direitos})

    def test_materia_limita_os_topicos_aos_dela(self):
        # q1 tem Licitações e Direitos Fundamentais, mas com Constitucional só o segundo é oferecido
        opcoes = self.opcoes(materia=self.constitucional.id)
        self.assertEqual(opcoes['topico'], {self.direitos})
        self.assertEqual(opcoes['materia'], {self.administrativo, self.constitucional})

    def test_materia_e_topico_juntos(self):
        opcoes = self.opcoes(materia=self.constitucional.id, topico=self.direitos.id, banca=self.cebraspe.id)
        self.assertEqual(opcoes['materia'], {self.constitucional})
        self.assertEqual(opcoes['topico'], {self.direitos})
        self.assertEqual(opcoes['ano'], {2022})

    def test_toda_opcao_oferecida_leva_a_pelo_menos_uma_questao(self):
        # Propriedade central da cascata: escolhendo qualquer opção de qualquer dropdown, sobre
        # qualquer filtro já escolhido, a lista nunca fica vazia
        todas = Questao.objects.all()
        for campo_inicial, valor_inicial in (
            ('banca', self.fgv.id), ('banca', self.cebraspe.id), ('orgao', self.tce.id), ('cargo', self.auditor.id),
            ('ano', 2022), ('materia', self.constitucional.id), ('topico', self.licitacoes.id),
        ):
            opcoes = self.opcoes(**{campo_inicial: valor_inicial})
            for campo, valores in opcoes.items():
                for valor in valores:
                    filtros = {campo_inicial: valor_inicial}
                    filtros[campo] = getattr(valor, 'id', valor)
                    with self.subTest(f'{campo_inicial}={valor_inicial} + {campo}={filtros[campo]}'):
                        aplicados = FiltrosQuestao.da_requisicao(filtros)
                        self.assertTrue(aplicados.aplicar(todas).exists())

    def test_combinacao_sem_questoes_mantem_as_selecoes_visiveis(self):
        # Ex: uma URL antiga. Sem questões, a lista fica vazia, mas os dropdowns mostram o que está filtrando
        resposta = self.client.get(self.url, {'banca': self.cebraspe.id, 'orgao': self.tce.id})
        self.assertEqual(list(resposta.context['questoes']), [])
        self.assertContains(resposta, self.caixa('banca', self.cebraspe.id, 'CEBRASPE', marcada=True), html=True)
        self.assertContains(resposta, self.caixa('orgao', self.tce.id, 'TCE-RJ', marcada=True), html=True)

    def test_ano_selecionado_sem_combinacao_continua_no_dropdown(self):
        opcoes = self.opcoes(banca=self.cebraspe.id, ano=2024)
        self.assertIn(2024, opcoes['ano'])

    def test_html_so_traz_as_opcoes_disponiveis(self):
        resposta = self.client.get(self.url, {'banca': self.cebraspe.id})
        self.assertContains(resposta, self.caixa('orgao', self.tcu.id, 'TCU'), html=True)
        self.assertContains(resposta, self.caixa('ano', 2022, '2022'), html=True)
        self.assertNotContains(resposta, 'TCE-RJ')
        self.assertNotContains(resposta, 'Auditor')
        self.assertNotContains(resposta, 'value="2024"')
        # Bancas que não têm nenhuma questão nunca aparecem
        self.assertNotContains(resposta, 'VUNESP')
        # Matéria e tópico sem questões também não
        self.assertNotContains(resposta, 'Contabilidade')
        self.assertNotContains(resposta, 'Balanço')

    def test_valores_invalidos_na_url_nao_quebram_a_cascata(self):
        for valor in ('abc', '²', '999999', ''):
            with self.subTest(valor=valor):
                parametros = dict.fromkeys(('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano'), valor)
                self.assertEqual(self.client.get(self.url, parametros).status_code, 200)


class DashboardEmCascataTests(TestCase):
    """O painel de desempenho usa os mesmos filtros (só banca, cargo, matéria e tópico)."""
    url = reverse('usuarios:dashboard')

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe', sigla='CEBRASPE')
        cls.auditor = Cargo.objects.create(nome='Auditor')
        cls.analista = Cargo.objects.create(nome='Analista')
        cls.tcu = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.administrativo = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.licitacoes = Topico.objects.create(nome='Licitações', materia=cls.administrativo)
        cls.direitos = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)
        for banca, cargo, topico in ((cls.fgv, cls.auditor, cls.licitacoes), (cls.cebraspe, cls.analista, cls.direitos)):
            questao = Questao.objects.create(enunciado='x', ano=2024, banca=banca, orgao=cls.tcu, cargo=cargo)
            questao.topicos.add(topico)

    def setUp(self):
        self.client.force_login(self.usuario)

    def test_filtros_do_painel_tambem_funcionam_em_cascata(self):
        contexto = self.client.get(self.url, {'banca': self.cebraspe.id}).context
        self.assertEqual(set(contexto['cargos']), {self.analista})
        self.assertEqual(set(contexto['materias']), {self.constitucional})
        self.assertEqual(set(contexto['topicos']), {self.direitos})
        # A própria banca continua com as duas opções
        self.assertEqual(set(contexto['bancas']), {self.fgv, self.cebraspe})

    def test_parametros_que_o_painel_nao_usa_nao_restringem_as_opcoes(self):
        contexto = self.client.get(self.url, {'orgao': 999, 'ano': 1999}).context
        self.assertEqual(set(contexto['cargos']), {self.auditor, self.analista})
        self.assertEqual(set(contexto['materias']), {self.administrativo, self.constitucional})
