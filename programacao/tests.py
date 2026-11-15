from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse


class HomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user('aluno', password='senha-forte-123')

    def test_exige_login(self):
        resposta = self.client.get(reverse('programacao:home'))
        self.assertEqual(resposta.status_code, 302)

    def test_mostra_a_home(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse('programacao:home'))
        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, 'home.html')

    def test_login_leva_para_a_home(self):
        resposta = self.client.post(reverse('usuarios:login'), {'username': 'aluno', 'password': 'senha-forte-123'})
        self.assertRedirects(resposta, reverse('programacao:home'))

    def test_barra_lateral_abre_os_apps_em_abas(self):
        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse('programacao:home'))
        self.assertContains(resposta, f'href="{reverse("questoes:lista_questoes")}" class="home-lateral-link robo-link-questoes" data-aba="Questões"')
        self.assertContains(resposta, f'href="{reverse("programacao:inicio")}" class="home-lateral-link robo-link-programacao" data-aba="Programação"')
        self.assertContains(resposta, 'js/abas.js')
        # No lugar dos nomes, mini robôs com balões de fala
        self.assertContains(resposta, '<span class="robo-balao">REVISE FAZENDO QUESTÕES</span>', html=True)
        self.assertContains(resposta, '<span class="robo-balao">ESTUDE LÓGICA DE PROGRAMAÇÃO</span>', html=True)
        self.assertContains(resposta, 'class="robo"', count=2)
        # As abas abertas são guardadas no navegador numa chave por usuário
        self.assertContains(resposta, f'data-abas data-usuario="{self.usuario.pk}"')
        # Anúncio no topo, no estilo MS-DOS da tela de login
        self.assertContains(
            resposta,
            '<p class="terminal-texto" data-terminal>C:\\&gt; Este espaço ajuda a deixar o projeto gratuito '
            'através de anúncios e propagandas pagas</p>',
        )
        self.assertContains(resposta, 'js/terminal.js')
        # A Home tem a própria barra do topo, no lugar do cabeçalho das outras páginas
        self.assertNotContains(resposta, 'class="topo"')

    def test_apps_podem_abrir_em_iframe_do_proprio_site(self):
        self.client.force_login(self.usuario)
        for url in (reverse('questoes:lista_questoes'), reverse('programacao:inicio')):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url)['X-Frame-Options'], 'SAMEORIGIN')


class InicioTests(TestCase):
    def test_exige_login(self):
        self.assertEqual(self.client.get(reverse('programacao:inicio')).status_code, 302)

    def test_mostra_a_pagina_do_app(self):
        self.client.force_login(get_user_model().objects.create_user('aluno'))
        resposta = self.client.get(reverse('programacao:inicio'))
        self.assertTemplateUsed(resposta, 'em_construcao.html')
        self.assertContains(resposta, 'Estamos construindo esta página')
        self.assertContains(resposta, 'class="topo"')


class EmConstrucaoTests(TestCase):
    def renderizar(self, contexto=None):
        requisicao = RequestFactory().get('/')
        requisicao.user = get_user_model().objects.create_user('aluno')
        return render_to_string('em_construcao.html', contexto or {}, request=requisicao)

    def test_textos_padrao(self):
        html = self.renderizar()
        self.assertIn('Em construção', html)
        self.assertIn('Estamos construindo esta página', html)
        self.assertIn(f'href="{reverse("programacao:home")}"', html)

    def test_titulo_e_mensagem_da_view(self):
        html = self.renderizar({'titulo': 'Exercícios de lógica', 'mensagem': 'Logo teremos exercícios.'})
        self.assertIn('Exercícios de lógica', html)
        self.assertIn('Logo teremos exercícios.', html)
        self.assertNotIn('Estamos construindo esta página', html)
