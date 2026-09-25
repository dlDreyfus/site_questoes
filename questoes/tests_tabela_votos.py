"""Tabela de curtidas/descurtidas na tela de importação e a exclusão de questões (superusuário e "Administrador")."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import (
    Alternativa, Banca, Cargo, Comentario, HistoricoResolucao, Orgao, Questao, ResolucaoOficial, Simulado,
)
from .views import QUESTOES_POR_PAGINA_TABELA


class TabelaVotosTestCase(TestCase):
    url = reverse('questoes:importar_questoes')

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.superusuario = User.objects.create_superuser('chefe', password='senha-forte-123')
        cls.aluno = User.objects.create_user('aluno', password='senha-forte-123')
        cls.votantes = [User.objects.create_user(f'votante{i}', password='senha-forte-123') for i in range(4)]
        cls.banca = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.orgao = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.cargo = Cargo.objects.create(nome='Auditor')

    @classmethod
    def criar_questao(cls, codigo, curtidas=0, descurtidas=0, com_resolucao=True):
        questao = Questao.objects.create(
            codigo=codigo, enunciado='Enunciado', ano=2024, banca=cls.banca, orgao=cls.orgao, cargo=cls.cargo,
        )
        if com_resolucao:
            resolucao = ResolucaoOficial.objects.create(questao=questao, texto='Resolução')
            resolucao.curtidas.set(cls.votantes[:curtidas])
            resolucao.descurtidas.set(cls.votantes[:descurtidas])
        return questao

    def usuario_do_grupo_administrador(self):
        # Mesmo caminho do projeto real: a permissão de importar vem do grupo "Administrador"
        grupo = Group.objects.create(name='Administrador')
        grupo.permissions.add(Permission.objects.get(codename='importar_questoes'))
        usuario = get_user_model().objects.create_user('membro_admin', password='senha-forte-123')
        usuario.groups.add(grupo)
        return usuario

    def linhas(self, resposta):
        return [(q.codigo, q.total_curtidas, q.total_descurtidas) for q in resposta.context['pagina']]


class OrdenacaoETotaisTests(TabelaVotosTestCase):
    def setUp(self):
        self.client.force_login(self.superusuario)

    def test_ordena_por_descurtidas_depois_curtidas_depois_codigo(self):
        self.criar_questao('B-2', curtidas=1, descurtidas=1)
        self.criar_questao('A-1', curtidas=1, descurtidas=1)   # empate total: o código decide
        self.criar_questao('C-3', curtidas=3, descurtidas=1)   # mesmas descurtidas, mais curtidas
        self.criar_questao('D-4', curtidas=0, descurtidas=3)   # mais descurtidas: vem primeiro
        self.criar_questao('E-5', curtidas=4, descurtidas=0)
        self.criar_questao('F-6', com_resolucao=False)         # sem resolução: 0 e 0

        resposta = self.client.get(self.url)
        self.assertEqual(self.linhas(resposta), [
            ('D-4', 0, 3), ('C-3', 3, 1), ('A-1', 1, 1), ('B-2', 1, 1), ('E-5', 4, 0), ('F-6', 0, 0),
        ])

    def test_questoes_sem_codigo_ficam_por_ultimo_no_empate(self):
        sem_codigo = self.criar_questao(None)
        self.criar_questao('Z-9')
        resposta = self.client.get(self.url)
        self.assertEqual([q.codigo for q in resposta.context['pagina']], ['Z-9', None])
        self.assertContains(resposta, f'sem código (id {sem_codigo.pk})')

    def test_totais_nao_se_multiplicam_com_curtidas_e_descurtidas_juntas(self):
        # Sem distinct=True nos Count, 3 curtidas x 2 descurtidas apareceriam como 6 e 6
        self.criar_questao('A-1', curtidas=3, descurtidas=2)
        resposta = self.client.get(self.url)
        self.assertEqual(self.linhas(resposta), [('A-1', 3, 2)])

    def test_tabela_e_paginada(self):
        for i in range(QUESTOES_POR_PAGINA_TABELA + 3):
            self.criar_questao(f'Q-{i:03d}')
        resposta = self.client.get(self.url)
        self.assertEqual(len(resposta.context['pagina']), QUESTOES_POR_PAGINA_TABELA)
        resposta = self.client.get(self.url, {'page': 2})
        self.assertEqual(len(resposta.context['pagina']), 3)

    def test_sem_questoes_mostra_aviso(self):
        self.assertContains(self.client.get(self.url), 'Nenhuma questão cadastrada.')

    def test_consultas_nao_crescem_com_o_numero_de_questoes(self):
        self.criar_questao('A-1', curtidas=1)
        with CaptureQueriesContext(connection) as poucas:
            self.client.get(self.url)
        for i in range(5):
            self.criar_questao(f'B-{i}', curtidas=2, descurtidas=1)
        with CaptureQueriesContext(connection) as muitas:
            self.client.get(self.url)
        self.assertEqual(len(muitas), len(poucas))


class RespondidasTests(TabelaVotosTestCase):
    """Coluna "Respondidas": quantas vezes a questão foi respondida, somando todos os usuários."""

    def setUp(self):
        self.client.force_login(self.superusuario)

    def responder(self, questao, vezes, usuarios=None):
        # Fora de simulado o mesmo usuário pode refazer a questão: cada tentativa conta
        usuarios = usuarios or self.votantes
        for i in range(vezes):
            HistoricoResolucao.objects.create(usuario=usuarios[i % len(usuarios)], questao=questao, acertou=i % 2 == 0)

    def linhas(self, resposta):
        return [
            (q.codigo, q.total_descurtidas, q.total_respondidas, q.total_curtidas) for q in resposta.context['pagina']
        ]

    def test_conta_as_respostas_de_todos_os_usuarios_e_de_simulados(self):
        questao = self.criar_questao('A-1')
        self.responder(questao, 3, usuarios=[self.aluno])       # o mesmo usuário três vezes
        self.responder(questao, 2, usuarios=self.votantes[:2])  # outros dois usuários
        simulado = Simulado.objects.create(usuario=self.aluno, nome='S', descricao='')
        simulado.questoes.add(questao)
        HistoricoResolucao.objects.create(usuario=self.aluno, questao=questao, acertou=True, simulado=simulado)
        self.criar_questao('B-2')                               # nunca respondida: 0

        resposta = self.client.get(self.url)
        self.assertEqual(self.linhas(resposta), [('A-1', 0, 6, 0), ('B-2', 0, 0, 0)])
        self.assertContains(resposta, '<th>Respondidas</th>', html=True)

    def test_ordena_por_descurtidas_depois_respondidas_depois_curtidas_depois_codigo(self):
        self.responder(self.criar_questao('A-1', curtidas=4, descurtidas=1), 1)
        self.responder(self.criar_questao('B-2', curtidas=0, descurtidas=1), 5)  # mesmas descurtidas, mais respondida
        self.responder(self.criar_questao('C-3', curtidas=1, descurtidas=0), 2)
        self.responder(self.criar_questao('D-4', curtidas=3, descurtidas=0), 2)  # empate em respondidas: curtidas
        self.responder(self.criar_questao('F-6', curtidas=0, descurtidas=0), 2)  # empate total com E-5: código
        self.responder(self.criar_questao('E-5', curtidas=0, descurtidas=0), 2)
        self.responder(self.criar_questao('G-7', curtidas=4, descurtidas=0), 0)  # muitas curtidas, nenhuma resposta
        self.criar_questao('H-8', descurtidas=2)                                # mais descurtidas: primeiro

        resposta = self.client.get(self.url)
        self.assertEqual(self.linhas(resposta), [
            ('H-8', 2, 0, 0), ('B-2', 1, 5, 0), ('A-1', 1, 1, 4),
            ('D-4', 0, 2, 3), ('C-3', 0, 2, 1), ('E-5', 0, 2, 0), ('F-6', 0, 2, 0),
            ('G-7', 0, 0, 4),
        ])

    def test_respostas_nao_multiplicam_curtidas_e_descurtidas(self):
        self.responder(self.criar_questao('A-1', curtidas=3, descurtidas=2), 4)
        self.assertEqual(self.linhas(self.client.get(self.url)), [('A-1', 2, 4, 3)])

    def test_consultas_nao_crescem_com_as_respostas(self):
        questao = self.criar_questao('A-1', curtidas=1)
        self.responder(questao, 1)
        with CaptureQueriesContext(connection) as poucas:
            self.client.get(self.url)
        for i in range(5):
            self.responder(self.criar_questao(f'B-{i}', descurtidas=1), 3)
        with CaptureQueriesContext(connection) as muitas:
            self.client.get(self.url)
        self.assertEqual(len(muitas), len(poucas))


class PermissaoDasAcoesTests(TabelaVotosTestCase):
    def setUp(self):
        self.questao = self.criar_questao('A-1', curtidas=1, descurtidas=2)
        self.url_apagar = reverse('questoes:apagar_questao', args=[self.questao.pk])
        self.url_alterar = reverse('admin:questoes_questao_change', args=[self.questao.pk])

    def test_superusuario_ve_alterar_e_deletar(self):
        self.client.force_login(self.superusuario)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, '<th>Ações</th>')
        self.assertContains(resposta, f'href="{self.url_alterar}"')
        self.assertContains(resposta, f'href="{self.url_apagar}"')

    def test_grupo_administrador_ve_deletar_e_so_ve_alterar_se_puder_entrar_no_admin(self):
        usuario = self.usuario_do_grupo_administrador()
        self.client.force_login(usuario)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, f'href="{self.url_apagar}"')
        # Sem is_staff o admin do Django só levaria ao login: o link não aparece
        self.assertNotContains(resposta, f'href="{self.url_alterar}"')

        usuario.is_staff = True
        usuario.save()
        usuario.user_permissions.add(Permission.objects.get(codename='change_questao'))
        resposta = self.client.get(self.url)
        self.assertContains(resposta, f'href="{self.url_alterar}"')

    def test_usuario_com_so_a_permissao_de_importar_ve_a_tabela_mas_nao_as_acoes(self):
        usuario = get_user_model().objects.create_user('importador', password='senha-forte-123')
        usuario.user_permissions.add(Permission.objects.get(codename='importar_questoes'))
        self.client.force_login(usuario)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'A-1')
        self.assertNotContains(resposta, '<th>Ações</th>')
        self.assertNotContains(resposta, self.url_apagar)
        self.assertEqual(self.client.get(self.url_apagar).status_code, 403)
        self.assertEqual(self.client.post(self.url_apagar).status_code, 403)
        self.assertTrue(Questao.objects.filter(pk=self.questao.pk).exists())

    def test_aluno_comum_nao_acessa_nem_apaga(self):
        self.client.force_login(self.aluno)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(self.url_apagar).status_code, 403)
        self.assertEqual(self.client.post(self.url_apagar).status_code, 403)
        self.assertTrue(Questao.objects.filter(pk=self.questao.pk).exists())

    def test_visitante_e_mandado_para_o_login(self):
        self.assertRedirects(self.client.get(self.url_apagar), f"{reverse('usuarios:login')}?next={self.url_apagar}")
        self.assertEqual(self.client.post(self.url_apagar).status_code, 302)
        self.assertTrue(Questao.objects.filter(pk=self.questao.pk).exists())


class ApagarQuestaoTests(TabelaVotosTestCase):
    def setUp(self):
        self.questao = self.criar_questao('A-1')
        Alternativa.objects.create(questao=self.questao, ordem=1, texto='Certa', is_correta=True)
        Alternativa.objects.create(questao=self.questao, ordem=2, texto='Errada')
        HistoricoResolucao.objects.create(usuario=self.aluno, questao=self.questao, acertou=True)
        Comentario.objects.create(questao=self.questao, usuario=self.aluno, texto='Bom')
        self.url_apagar = reverse('questoes:apagar_questao', args=[self.questao.pk])
        self.client.force_login(self.usuario_do_grupo_administrador())

    def test_get_pede_confirmacao_e_nao_apaga(self):
        resposta = self.client.get(self.url_apagar)
        self.assertContains(resposta, 'Apagar "A-1"?')
        self.assertContains(resposta, '2 alternativas')
        self.assertContains(resposta, '1 resposta de usuários')
        self.assertContains(resposta, '1 comentário do fórum')
        self.assertTrue(Questao.objects.filter(pk=self.questao.pk).exists())

    def test_post_apaga_a_questao_e_o_que_depende_dela(self):
        resposta = self.client.post(self.url_apagar, follow=True)
        self.assertRedirects(resposta, reverse('questoes:importar_questoes'))
        self.assertContains(resposta, 'Questão &quot;A-1&quot; apagada.')
        self.assertFalse(Questao.objects.exists())
        self.assertFalse(Alternativa.objects.exists())
        self.assertFalse(ResolucaoOficial.objects.exists())
        self.assertFalse(HistoricoResolucao.objects.exists())
        self.assertFalse(Comentario.objects.exists())

    def test_apagar_uma_questao_preserva_as_outras(self):
        outra = self.criar_questao('B-2')
        self.client.post(self.url_apagar)
        self.assertEqual(list(Questao.objects.values_list('pk', flat=True)), [outra.pk])

    def test_questao_inexistente_da_404(self):
        self.assertEqual(self.client.post(reverse('questoes:apagar_questao', args=[99999])).status_code, 404)

    def test_questao_sem_codigo_usa_o_id_no_aviso(self):
        sem_codigo = self.criar_questao(None)
        resposta = self.client.post(reverse('questoes:apagar_questao', args=[sem_codigo.pk]), follow=True)
        self.assertContains(resposta, f'Questão &quot;Questão {sem_codigo.pk}&quot; apagada.')
