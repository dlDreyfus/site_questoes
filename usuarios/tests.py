import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from questoes.models import Alternativa, Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Topico


class LoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')

    def test_usa_o_model_de_usuario_do_projeto(self):
        self.assertEqual(get_user_model()._meta.label, 'usuarios.Usuario')

    def test_login_redireciona_para_a_pagina_pedida(self):
        resposta = self.client.post(
            f"{reverse('usuarios:login')}?next=/%3Fano%3D2024",
            {'username': 'aluno', 'password': 'senha-forte-123'},
        )
        self.assertRedirects(resposta, '/?ano=2024', fetch_redirect_response=False)

    def test_usuario_logado_nao_ve_o_login_de_novo(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse('usuarios:login'))
        self.assertRedirects(resposta, reverse('questoes:lista_questoes'))

    def test_logout(self):
        self.client.force_login(self.usuario)
        resposta = self.client.post(reverse('usuarios:logout'))
        self.assertRedirects(resposta, reverse('usuarios:login'))
        self.assertEqual(self.client.get(reverse('questoes:lista_questoes')).status_code, 302)


class CadastroTests(TestCase):
    url = reverse('usuarios:cadastro')
    dados_validos = {
        'username': 'novo_aluno', 'email': 'novo@exemplo.com',
        'password1': 'Senha-Forte-2026', 'password2': 'Senha-Forte-2026',
    }

    def test_login_tem_link_para_cadastro(self):
        resposta = self.client.get(reverse('usuarios:login'))
        self.assertContains(resposta, f'href="{self.url}"')
        self.assertContains(resposta, 'Cadastrar Novo Usuário')

    def cadastrar(self):
        return self.client.post(self.url, self.dados_validos)

    def test_cadastro_cria_conta_ativa_faz_login_e_mostra_boas_vindas(self):
        resposta = self.client.post(self.url, self.dados_validos, follow=True)
        self.assertRedirects(resposta, reverse('questoes:lista_questoes'))
        usuario = get_user_model().objects.get(username='novo_aluno')
        self.assertTrue(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertEqual(usuario.email, 'novo@exemplo.com')
        self.assertTrue(usuario.check_password('Senha-Forte-2026'))
        self.assertEqual(resposta.context['user'], usuario)
        self.assertContains(resposta, 'Conta criada com sucesso. Bem-vindo(a), novo_aluno!')

    def test_cadastro_nao_envia_email(self):
        self.cadastrar()
        self.assertEqual(len(mail.outbox), 0)

    def test_conta_criada_consegue_entrar_depois(self):
        self.cadastrar()
        self.client.logout()
        resposta = self.client.post(
            reverse('usuarios:login'), {'username': 'novo_aluno', 'password': 'Senha-Forte-2026'},
        )
        self.assertRedirects(resposta, reverse('questoes:lista_questoes'))

    def test_banco_impede_email_repetido(self):
        get_user_model().objects.create_user('primeiro', email='repetido@exemplo.com')
        with self.assertRaises(IntegrityError):
            get_user_model().objects.create_user('segundo', email='REPETIDO@exemplo.com')

    def test_contas_sem_email_continuam_permitidas(self):
        get_user_model().objects.create_user('sem_email_1')
        get_user_model().objects.create_user('sem_email_2')
        self.assertEqual(get_user_model().objects.filter(email='').count(), 2)

    def test_dados_invalidos_nao_criam_usuario(self):
        get_user_model().objects.create_user('existente', email='existente@exemplo.com', password='senha-forte-123')
        casos = {
            'usuário repetido (maiúsculas)': {'username': 'EXISTENTE'},
            'e-mail repetido (maiúsculas)': {'email': 'EXISTENTE@exemplo.com'},
            'senhas diferentes': {'password2': 'Outra-Senha-2026'},
            'senha fraca': {'password1': '123', 'password2': '123'},
            'sem e-mail': {'email': ''},
        }
        for nome, alteracao in casos.items():
            with self.subTest(caso=nome):
                resposta = self.client.post(self.url, {**self.dados_validos, **alteracao})
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(resposta.context['form'].errors)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_usuario_logado_e_redirecionado(self):
        usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')
        self.client.force_login(usuario)
        self.assertRedirects(self.client.get(self.url), reverse('questoes:lista_questoes'))


class RecuperarSenhaTests(TestCase):
    url = reverse('usuarios:recuperar_senha')

    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user(
            'aluno', email='aluno@exemplo.com', password='senha-antiga-123',
        )

    def pedir_link(self, email='aluno@exemplo.com'):
        return self.client.post(self.url, {'email': email})

    def link_do_email(self):
        # Extrai do corpo do e-mail o caminho /usuarios/redefinir-senha/<uid>/<token>/
        return re.search(r'https?://[^/]+(/\S+)', mail.outbox[0].body).group(1)

    def test_login_tem_link_para_recuperar_senha(self):
        self.assertContains(self.client.get(reverse('usuarios:login')), f'href="{self.url}"')

    def test_envia_email_com_link(self):
        resposta = self.pedir_link()
        self.assertRedirects(resposta, reverse('usuarios:recuperar_senha_enviado'))
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ['aluno@exemplo.com'])
        self.assertEqual(email.subject, 'Simulado - Recuperação de senha')
        self.assertIn('/usuarios/redefinir-senha/', email.body)

    def test_email_informa_o_nome_de_usuario_mas_nunca_a_senha(self):
        self.pedir_link()
        corpo = mail.outbox[0].body
        self.assertIn('Seu nome de usuário (login) é: aluno', corpo)
        self.assertNotIn('senha-antiga-123', corpo)

    def test_email_inexistente_nao_revela_nada(self):
        resposta = self.pedir_link('ninguem@exemplo.com')
        # Mesmo redirecionamento de quando o e-mail existe, mas nenhum e-mail é enviado
        self.assertRedirects(resposta, reverse('usuarios:recuperar_senha_enviado'))
        self.assertEqual(len(mail.outbox), 0)

    def test_fluxo_completo_troca_a_senha(self):
        self.pedir_link()
        # O Django troca o token da URL por um marcador na sessão e redireciona (evita vazar o token)
        resposta = self.client.get(self.link_do_email(), follow=True)
        self.assertTrue(resposta.context['validlink'])
        resposta = self.client.post(
            resposta.redirect_chain[-1][0],
            {'new_password1': 'Senha-Nova-2026', 'new_password2': 'Senha-Nova-2026'},
        )
        self.assertRedirects(resposta, reverse('usuarios:redefinir_senha_concluido'))
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.check_password('Senha-Nova-2026'))

    def test_link_nao_pode_ser_reutilizado(self):
        self.pedir_link()
        link = self.link_do_email()
        resposta = self.client.get(link, follow=True)
        self.client.post(
            resposta.redirect_chain[-1][0],
            {'new_password1': 'Senha-Nova-2026', 'new_password2': 'Senha-Nova-2026'},
        )
        resposta = self.client.get(link, follow=True)
        self.assertFalse(resposta.context['validlink'])
        self.assertContains(resposta, 'Link inválido')

    def test_link_adulterado_e_invalido(self):
        resposta = self.client.get(
            reverse('usuarios:redefinir_senha', kwargs={'uidb64': 'MQ', 'token': 'token-falso'}), follow=True,
        )
        self.assertFalse(resposta.context['validlink'])


class DashboardTests(TestCase):
    url = reverse('usuarios:dashboard')

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user('aluno', password='senha-forte-123')
        cls.outro = User.objects.create_user('outro', password='senha-forte-123')
        banca = Banca.objects.create(nome='FGV')
        questao = Questao.objects.create(
            enunciado='x', ano=2024, banca=banca,
            orgao=Orgao.objects.create(nome='TCU', sigla='TCU'), cargo=Cargo.objects.create(nome='Auditor'),
        )
        certa = Alternativa.objects.create(questao=questao, texto='Certa', is_correta=True)
        errada = Alternativa.objects.create(questao=questao, texto='Errada')

        def responder(usuario, alternativa):
            HistoricoResolucao.objects.create(
                usuario=usuario, questao=questao, alternativa_escolhida=alternativa, acertou=alternativa.is_correta,
            )

        responder(cls.usuario, certa)
        responder(cls.usuario, certa)
        responder(cls.usuario, errada)
        responder(cls.outro, errada)  # não pode entrar na conta do 'aluno'

    def test_exige_login(self):
        resposta = self.client.get(self.url)
        self.assertRedirects(resposta, f"{reverse('usuarios:login')}?next={self.url}")

    def test_calcula_o_desempenho_do_usuario_logado(self):
        self.client.force_login(self.usuario)
        contexto = self.client.get(self.url).context
        self.assertEqual(
            (contexto['total'], contexto['acertos'], contexto['erros'], contexto['percentual']),
            (3, 2, 1, 66.7),
        )

    def test_sem_respostas(self):
        novato = get_user_model().objects.create_user('novato', password='senha-forte-123')
        self.client.force_login(novato)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.context['percentual'], 0)
        self.assertContains(resposta, 'Nenhum dado encontrado')


class DashboardFiltrosTests(TestCase):
    """Estatísticas estratificadas por banca, cargo, matéria e tópico."""
    url = reverse('usuarios:dashboard')

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user('aluno', password='senha-forte-123')
        cls.outro = User.objects.create_user('outro', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe', sigla='CEBRASPE')
        cls.auditor = Cargo.objects.create(nome='Auditor')
        cls.analista = Cargo.objects.create(nome='Analista')
        orgao = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.administrativo = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.licitacoes = Topico.objects.create(nome='Licitações', materia=cls.administrativo)
        cls.contratos = Topico.objects.create(nome='Contratos', materia=cls.administrativo)
        cls.direitos = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)

        def questao(banca, cargo, *topicos):
            q = Questao.objects.create(enunciado='x', ano=2024, banca=banca, orgao=orgao, cargo=cargo)
            q.topicos.add(*topicos)
            return q

        def responder(usuario, questao, *resultados):
            for acertou in resultados:
                HistoricoResolucao.objects.create(usuario=usuario, questao=questao, acertou=acertou)

        # q1 tem DOIS tópicos da mesma matéria: filtrar pela matéria não pode contar as respostas em dobro
        q1 = questao(cls.fgv, cls.auditor, cls.licitacoes, cls.contratos)
        q2 = questao(cls.cebraspe, cls.analista, cls.direitos)
        q3 = questao(cls.fgv, cls.analista, cls.contratos)
        responder(cls.usuario, q1, True, False)       # 2 respostas, 1 acerto
        responder(cls.usuario, q2, True, True, True)  # 3 respostas, 3 acertos
        responder(cls.usuario, q3, False)             # 1 resposta, 0 acertos
        responder(cls.outro, q1, True, True, True)    # de outro usuário: nunca entra na conta

    def setUp(self):
        self.client.force_login(self.usuario)

    def estatisticas(self, **filtros):
        contexto = self.client.get(self.url, filtros).context
        return contexto['total'], contexto['acertos'], contexto['erros']

    def test_sem_filtro_conta_tudo_do_usuario(self):
        self.assertEqual(self.estatisticas(), (6, 4, 2))

    def test_cada_filtro_estratifica(self):
        casos = {
            'banca FGV': ({'banca': self.fgv.id}, (3, 1, 2)),
            'banca Cebraspe': ({'banca': self.cebraspe.id}, (3, 3, 0)),
            'cargo Analista': ({'cargo': self.analista.id}, (4, 3, 1)),
            'cargo Auditor': ({'cargo': self.auditor.id}, (2, 1, 1)),
            # q1 tem 2 tópicos de Administrativo: continua contando 2 respostas, não 4
            'matéria Administrativo': ({'materia': self.administrativo.id}, (3, 1, 2)),
            'matéria Constitucional': ({'materia': self.constitucional.id}, (3, 3, 0)),
            'tópico Contratos': ({'topico': self.contratos.id}, (3, 1, 2)),
            'tópico Licitações': ({'topico': self.licitacoes.id}, (2, 1, 1)),
        }
        for nome, (filtros, esperado) in casos.items():
            with self.subTest(nome):
                self.assertEqual(self.estatisticas(**filtros), esperado)

    def test_filtros_combinados_e_percentual(self):
        self.assertEqual(self.estatisticas(banca=self.fgv.id, cargo=self.analista.id), (1, 0, 1))
        contexto = self.client.get(self.url, {'cargo': self.analista.id}).context
        self.assertEqual(contexto['percentual'], 75.0)

    def test_topico_de_outra_materia_e_ignorado(self):
        self.assertEqual(self.estatisticas(materia=self.constitucional.id, topico=self.licitacoes.id), (3, 3, 0))

    def test_orgao_ano_e_valores_invalidos_sao_ignorados(self):
        # O painel só filtra por banca, cargo, matéria e tópico
        self.assertEqual(self.estatisticas(orgao=999, ano=1999), (6, 4, 2))
        self.assertEqual(self.estatisticas(banca='abc', topico='²'), (6, 4, 2))
        self.assertEqual(self.client.get(self.url, {'ano': 1999}).context['filtros_ativos'], 0)

    def test_combinacao_sem_respostas_mostra_aviso_proprio(self):
        resposta = self.client.get(self.url, {'banca': self.cebraspe.id, 'cargo': self.auditor.id})
        self.assertEqual(resposta.context['total'], 0)
        self.assertContains(resposta, 'Nenhuma resposta com esses filtros')
        self.assertContains(resposta, f'<a href="{self.url}">Limpar filtros</a>', html=True)
        self.assertNotContains(resposta, 'Nenhum dado encontrado')

    def test_mostra_so_os_quatro_filtros_e_mantem_a_selecao(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'materia': self.administrativo.id})
        for campo in ('banca', 'cargo', 'materia', 'topico'):
            self.assertContains(resposta, f'name="{campo}"')
        for campo in ('orgao', 'ano'):
            self.assertNotContains(resposta, f'name="{campo}"')
        self.assertContains(resposta, 'data-campos="4"')
        self.assertContains(resposta, f'action="{self.url}"')
        self.assertContains(
            resposta, f'<label class="filtro-opcao"><input type="checkbox" name="banca" value="{self.fgv.id}" checked> '
            'FGV</label>', html=True,
        )
        # Com a matéria escolhida, o dropdown de tópicos só tem os tópicos dela
        self.assertEqual(set(resposta.context['topicos']), {self.licitacoes, self.contratos})
        self.assertContains(resposta, '<span class="filtros-contador">2 ativos</span>', html=True)
