"""Percentual de acerto da questão (todos os usuários), exibido junto à resolução, depois do Descurtir."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import HistoricoResolucao, ResolucaoOficial
from .tests import BaseQuestoesTestCase
from .views import _acertos_da_questao


class AcertosDaQuestaoTests(BaseQuestoesTestCase):
    def setUp(self):
        super().setUp()
        self.resolucao = ResolucaoOficial.objects.create(questao=self.questao, texto='Art. 28 da Lei 14.133.')
        User = get_user_model()
        self.colegas = [User.objects.create_user(f'colega{i}', password='senha-forte-123') for i in range(3)]

    def resposta(self, usuario, acertou, questao=None):
        questao = questao or self.questao
        HistoricoResolucao.objects.create(
            usuario=usuario, questao=questao, acertou=acertou,
            alternativa_escolhida=self.certa if acertou else self.errada,
        )

    def responder_pelo_site(self, alternativa):
        url = reverse('questoes:responder_questao', args=[self.questao.id])
        return self.client.post(url, {'alternativa': alternativa.id}, follow=True)

    def test_sem_respostas(self):
        self.assertEqual(_acertos_da_questao(self.questao.id), {'pessoas': 0, 'percentual': 0})

    def test_cada_pessoa_conta_uma_vez_pela_primeira_resposta(self):
        # colega0 errou e depois acertou: conta como erro. colega1 acertou e depois errou: conta como acerto.
        self.resposta(self.colegas[0], False)
        self.resposta(self.colegas[0], True)
        self.resposta(self.colegas[1], True)
        self.resposta(self.colegas[1], False)
        self.resposta(self.colegas[2], True)
        self.assertEqual(_acertos_da_questao(self.questao.id), {'pessoas': 3, 'percentual': 67})

    def test_respostas_de_outras_questoes_nao_contam(self):
        self.resposta(self.colegas[0], True)
        self.resposta(self.colegas[1], False, questao=self.outra_questao)
        self.assertEqual(_acertos_da_questao(self.questao.id), {'pessoas': 1, 'percentual': 100})

    def test_aparece_depois_do_descurtir_incluindo_a_resposta_do_usuario(self):
        self.resposta(self.colegas[0], False)
        pagina = self.responder_pelo_site(self.certa)
        conteudo = pagina.content.decode()
        self.assertContains(pagina, '<strong>50%</strong> acertaram')
        self.assertContains(pagina, '(2 pessoas resolveram)')
        url_descurtir = reverse('questoes:descurtir_resolucao', args=[self.resolucao.id])
        self.assertLess(conteudo.index(f'action="{url_descurtir}"'), conteudo.index('class="acertos-questao"'))

    def test_singular_para_uma_pessoa(self):
        self.assertContains(self.responder_pelo_site(self.errada), '(1 pessoa resolveu)')

    def test_nao_aparece_antes_de_responder(self):
        self.resposta(self.colegas[0], True)
        self.assertNotContains(self.client.get(reverse('questoes:lista_questoes')), 'class="acertos-questao"')


class DificuldadeDaQuestaoTests(BaseQuestoesTestCase):
    def setUp(self):
        super().setUp()
        ResolucaoOficial.objects.create(questao=self.questao, texto='Art. 28 da Lei 14.133.')
        self.url_facil = reverse('questoes:avaliar_facil', args=[self.questao.id])
        self.url_dificil = reverse('questoes:avaliar_dificil', args=[self.questao.id])

    def responder(self):
        url = reverse('questoes:responder_questao', args=[self.questao.id])
        return self.client.post(url, {'alternativa': self.certa.id}, follow=True)

    def votar(self, url):
        return self.client.post(url, headers={'Accept': 'application/json'}).json()

    def test_botoes_e_texto_aparecem_com_a_resolucao_depois_de_responder(self):
        lista = self.client.get(reverse('questoes:lista_questoes'))
        self.assertNotContains(lista, f'action="{self.url_facil}"')
        pagina = self.responder()
        conteudo = pagina.content.decode()
        self.assertContains(pagina, f'action="{self.url_facil}"')
        self.assertContains(pagina, f'action="{self.url_dificil}"')
        self.assertContains(pagina, 'Ninguém classificou a dificuldade desta questão ainda.')
        # Abaixo do Descurtir e do percentual de acerto
        self.assertLess(conteudo.index('class="acertos-questao"'), conteudo.index(f'action="{self.url_facil}"'))

    def test_exige_ter_respondido_a_questao(self):
        self.assertEqual(self.client.post(self.url_facil).status_code, 403)
        self.assertFalse(self.questao.avaliacoes_facil.exists())

    def test_so_aceita_post(self):
        self.responder()
        self.assertEqual(self.client.get(self.url_facil).status_code, 405)

    def test_facil_e_dificil_se_excluem_e_clicar_de_novo_desfaz(self):
        self.responder()
        estado = self.votar(self.url_facil)
        self.assertEqual(estado, {
            'facil': True, 'total_avaliacoes_facil': 1, 'dificil': False, 'total_avaliacoes_dificil': 0,
            'total_avaliacoes': 1, 'percentual_facil': 100, 'percentual_dificil': 0,
        })
        estado = self.votar(self.url_dificil)
        self.assertEqual((estado['facil'], estado['dificil'], estado['percentual_dificil']), (False, True, 100))
        estado = self.votar(self.url_dificil)
        self.assertEqual((estado['dificil'], estado['total_avaliacoes']), (False, 0))

    def test_percentuais_entre_quem_classificou(self):
        User = get_user_model()
        colegas = [User.objects.create_user(f'colega{i}', password='senha-forte-123') for i in range(3)]
        self.questao.avaliacoes_facil.add(colegas[0])
        self.questao.avaliacoes_dificil.add(colegas[1], colegas[2])
        pagina = self.responder()
        self.assertContains(pagina, '<strong>33%</strong> acharam fácil')
        self.assertContains(pagina, '<strong>67%</strong> acharam difícil')
        self.assertContains(pagina, '(3 pessoas classificaram)')

    def test_sem_javascript_volta_para_a_resolucao(self):
        self.responder()
        resposta = self.client.post(self.url_facil, {'next': reverse('questoes:lista_questoes')})
        self.assertRedirects(
            resposta, f"{reverse('questoes:lista_questoes')}#dificuldade-{self.questao.id}",
            fetch_redirect_response=False,
        )
        self.assertContains(self.client.get(resposta.url), 'Fácil ✓')
