"""Simulados públicos: o dono marca o simulado como público e os outros usuários o fazem numa cópia própria."""
from django.urls import reverse

from .models import Simulado
from .tests_simulados import BaseSimuladosTestCase


class CriarEEditarPublicoTests(BaseSimuladosTestCase):
    def test_novo_simulado_oferece_a_opcao_publico(self):
        self.assertContains(self.client.get(reverse('questoes:novo_simulado')), 'name="publico"')

    def test_simulado_e_privado_por_padrao(self):
        self.client.post(reverse('questoes:criar_simulado'), {'nome': 'Privado'})
        self.assertFalse(Simulado.objects.get(nome='Privado').publico)

    def test_cria_simulado_publico(self):
        self.client.post(reverse('questoes:criar_simulado'), {'nome': 'Aberto', 'publico': '1'})
        self.assertTrue(Simulado.objects.get(nome='Aberto').publico)

    def test_editar_torna_publico_e_privado_de_novo(self):
        simulado = self.criar_simulado(self.q1)
        url = reverse('questoes:editar_simulado', args=[simulado.id])
        self.client.post(url, {'nome': simulado.nome, 'publico': 'on'})
        simulado.refresh_from_db()
        self.assertTrue(simulado.publico)
        # Caixa desmarcada não é enviada pelo navegador: volta a ser privado
        self.client.post(url, {'nome': simulado.nome})
        simulado.refresh_from_db()
        self.assertFalse(simulado.publico)


class SimuladosPublicosTests(BaseSimuladosTestCase):
    url = reverse('questoes:simulados_publicos')

    def setUp(self):
        super().setUp()
        self.publico = self.criar_simulado(self.q1, self.q2, usuario=self.outro, nome='Público do outro')
        self.publico.publico = True
        self.publico.save()
        self.privado = self.criar_simulado(self.q3, usuario=self.outro, nome='Privado do outro')

    def fazer(self, simulado):
        return self.client.post(reverse('questoes:fazer_simulado', args=[simulado.id]))

    def test_exige_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('usuarios:login')}?next={self.url}")

    def test_botao_no_cabecalho_de_todas_as_paginas(self):
        for pagina in ('questoes:lista_questoes', 'usuarios:dashboard', 'questoes:simulados_publicos'):
            with self.subTest(pagina=pagina):
                self.assertContains(self.client.get(reverse(pagina)), f'href="{self.url}"')

    def test_lista_so_os_publicos_com_autor_e_total_de_questoes(self):
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'Público do outro')
        self.assertContains(resposta, 'Criado por <strong>outro</strong>')
        self.assertContains(resposta, '2 questões')
        self.assertNotContains(resposta, 'Privado do outro')

    def test_simulado_publico_do_proprio_usuario_mostra_abrir(self):
        meu = self.criar_simulado(self.q1, nome='Meu público')
        meu.publico = True
        meu.save()
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'Criado por <strong>aluno</strong> (você)')
        self.assertContains(resposta, f'href="{reverse("questoes:simulado_detalhe", args=[meu.id])}"')

    def test_fazer_cria_uma_copia_privada_com_as_mesmas_questoes(self):
        resposta = self.fazer(self.publico)
        copia = self.usuario.simulados.get()
        self.assertRedirects(resposta, reverse('questoes:simulado_detalhe', args=[copia.id]))
        self.assertEqual(set(copia.questoes.all()), {self.q1, self.q2})
        self.assertEqual(copia.origem, self.publico)
        self.assertEqual(copia.nome, 'Público do outro')
        self.assertFalse(copia.publico)

    def test_fazer_de_novo_volta_para_a_mesma_copia(self):
        self.fazer(self.publico)
        resposta = self.fazer(self.publico)
        copia = self.usuario.simulados.get()
        self.assertRedirects(resposta, reverse('questoes:simulado_detalhe', args=[copia.id]))
        # Na lista, o botão vira "Continuar" e leva à cópia; o original conta quem já fez
        lista = self.client.get(self.url)
        self.assertContains(lista, 'Continuar')
        self.assertContains(lista, 'Feito por 1 pessoa')

    def test_respostas_da_copia_nao_afetam_o_original(self):
        self.fazer(self.publico)
        copia = self.usuario.simulados.get()
        self.client.post(reverse('questoes:responder_questao', args=[self.q1.id]), {
            'alternativa': self.q1.certa.id, 'simulado': copia.id,
            'next': reverse('questoes:simulado_detalhe', args=[copia.id]),
        })
        self.assertEqual(copia.resolucoes.count(), 1)
        self.assertEqual(self.publico.resolucoes.count(), 0)

    def test_nao_da_para_fazer_simulado_privado(self):
        self.assertEqual(self.fazer(self.privado).status_code, 404)
        self.assertFalse(self.usuario.simulados.exists())

    def test_fazer_so_aceita_post(self):
        url = reverse('questoes:fazer_simulado', args=[self.publico.id])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_dono_que_faz_o_proprio_simulado_vai_para_ele(self):
        self.client.force_login(self.outro)
        resposta = self.fazer(self.publico)
        self.assertRedirects(resposta, reverse('questoes:simulado_detalhe', args=[self.publico.id]))
        self.assertEqual(self.outro.simulados.count(), 2)

    def test_apagar_o_original_mantem_a_copia(self):
        self.fazer(self.publico)
        self.publico.delete()
        copia = self.usuario.simulados.get()
        self.assertIsNone(copia.origem)
        self.assertEqual(self.client.get(reverse('questoes:simulado_detalhe', args=[copia.id])).status_code, 200)

    def test_simulado_publico_continua_so_o_dono_responde_nele(self):
        # Abrir o original (de outro usuário) continua dando 404: só a cópia é do usuário
        url = reverse('questoes:simulado_detalhe', args=[self.publico.id])
        self.assertEqual(self.client.get(url).status_code, 404)
