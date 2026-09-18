import re

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

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

    def link_do_email(self, indice=-1):
        # Extrai do corpo do e-mail o caminho /usuarios/ativar/<uid>/<token>/
        return re.search(r'https?://[^/]+(/\S+)', mail.outbox[indice].body).group(1)

    def test_cadastro_cria_conta_inativa_e_envia_email(self):
        resposta = self.cadastrar()
        self.assertRedirects(resposta, reverse('usuarios:ativacao_enviada'))
        usuario = get_user_model().objects.get(username='novo_aluno')
        self.assertFalse(usuario.is_active)
        self.assertFalse(usuario.is_staff)
        self.assertEqual(usuario.email, 'novo@exemplo.com')
        self.assertTrue(usuario.check_password('Senha-Forte-2026'))
        # Não entra logado antes de ativar
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['novo@exemplo.com'])
        self.assertEqual(mail.outbox[0].subject, 'Simulado - Ative sua conta')
        self.assertIn('/usuarios/ativar/', mail.outbox[0].body)

    def test_abrir_o_link_so_mostra_o_botao_sem_ativar(self):
        # Filtros de e-mail/antivírus que "visitam" o link não podem ativar a conta
        self.cadastrar()
        resposta = self.client.get(self.link_do_email())
        self.assertTemplateUsed(resposta, 'usuarios/ativar_conta.html')
        self.assertContains(resposta, 'Ativar minha conta')
        self.assertFalse(get_user_model().objects.get(username='novo_aluno').is_active)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_botao_ativa_a_conta_faz_login_e_mostra_boas_vindas(self):
        self.cadastrar()
        resposta = self.client.post(self.link_do_email(), follow=True)
        self.assertRedirects(resposta, reverse('questoes:lista_questoes'))
        usuario = get_user_model().objects.get(username='novo_aluno')
        self.assertTrue(usuario.is_active)
        self.assertEqual(resposta.context['user'], usuario)
        self.assertContains(resposta, 'Conta ativada com sucesso. Bem-vindo(a), novo_aluno!')

    def test_ativacao_exige_csrf(self):
        # Sem o token CSRF (ex: formulário forjado em outro site), o POST é recusado: evita login CSRF
        self.cadastrar()
        cliente_sem_csrf = Client(enforce_csrf_checks=True)
        resposta = cliente_sem_csrf.post(self.link_do_email())
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(get_user_model().objects.get(username='novo_aluno').is_active)

    def test_link_de_ativacao_so_vale_uma_vez(self):
        self.cadastrar()
        link = self.link_do_email()
        self.client.post(link)
        self.client.logout()
        for metodo in (self.client.get, self.client.post):
            with self.subTest(metodo=metodo.__name__):
                resposta = metodo(link)
                self.assertTemplateUsed(resposta, 'usuarios/ativacao_invalida.html')
                self.assertNotIn('_auth_user_id', self.client.session)

    def test_link_adulterado_ou_de_recuperacao_de_senha_nao_ativa(self):
        self.cadastrar()
        usuario = get_user_model().objects.get(username='novo_aluno')
        uid = urlsafe_base64_encode(force_bytes(usuario.pk))
        # Token da recuperação de senha (outro "sal") e token inventado não servem para ativar
        for token in (default_token_generator.make_token(usuario), 'token-falso'):
            for metodo in (self.client.get, self.client.post):
                with self.subTest(token=token, metodo=metodo.__name__):
                    resposta = metodo(reverse('usuarios:ativar_conta', args=[uid, token]))
                    self.assertTemplateUsed(resposta, 'usuarios/ativacao_invalida.html')
        resposta = self.client.get(reverse('usuarios:ativar_conta', args=['uid-invalido', 'x']))
        self.assertTemplateUsed(resposta, 'usuarios/ativacao_invalida.html')
        usuario.refresh_from_db()
        self.assertFalse(usuario.is_active)

    def test_login_antes_de_ativar_avisa_e_oferece_reenvio(self):
        self.cadastrar()
        resposta = self.client.post(
            reverse('usuarios:login'), {'username': 'novo_aluno', 'password': 'Senha-Forte-2026'},
        )
        self.assertContains(resposta, 'Sua conta ainda não foi ativada')
        self.assertContains(resposta, f'href="{reverse("usuarios:reenviar_ativacao")}"')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_inativo_com_senha_errada_nao_revela_a_conta(self):
        self.cadastrar()
        resposta = self.client.post(reverse('usuarios:login'), {'username': 'novo_aluno', 'password': 'errada'})
        self.assertNotContains(resposta, 'Sua conta ainda não foi ativada')
        self.assertNotContains(resposta, 'Reenviar link de ativação')

    def test_reenviar_ativacao(self):
        self.cadastrar()
        resposta = self.client.post(reverse('usuarios:reenviar_ativacao'), {'email': 'NOVO@exemplo.com'})
        self.assertRedirects(resposta, reverse('usuarios:ativacao_enviada'))
        self.assertEqual(len(mail.outbox), 2)
        # O novo link funciona
        self.client.post(self.link_do_email())
        self.assertTrue(get_user_model().objects.get(username='novo_aluno').is_active)

    def test_reenviar_nao_envia_para_conta_ativa_ou_inexistente(self):
        get_user_model().objects.create_user('ativo', email='ativo@exemplo.com', password='senha-forte-123')
        for email in ('ativo@exemplo.com', 'ninguem@exemplo.com'):
            with self.subTest(email=email):
                resposta = self.client.post(reverse('usuarios:reenviar_ativacao'), {'email': email})
                # Mesma resposta de sempre, para não revelar quais e-mails existem
                self.assertRedirects(resposta, reverse('usuarios:ativacao_enviada'))
        self.assertEqual(len(mail.outbox), 0)

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
        self.assertContains(resposta, f'<option value="{self.fgv.id}" selected>FGV</option>', html=True)
        # Com a matéria escolhida, o dropdown de tópicos só tem os tópicos dela
        self.assertEqual(set(resposta.context['topicos']), {self.licitacoes, self.contratos})
        self.assertContains(resposta, '<span class="filtros-contador">2 ativos</span>', html=True)
