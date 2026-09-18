"""Testes do fórum (comentários e respostas nas questões)."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import COMENTARIO_TAMANHO_MAXIMO, Comentario, ResolucaoOficial
from .tests import BaseQuestoesTestCase


class ForumTests(BaseQuestoesTestCase):
    lista = reverse('questoes:lista_questoes')

    def comentar(self, texto, questao=None, resposta_a=None, next_url='/'):
        questao = questao or self.questao
        dados = {'texto': texto, 'next': next_url}
        if resposta_a is not None:
            dados['resposta_a'] = resposta_a
        return self.client.post(reverse('questoes:comentar_questao', args=[questao.id]), dados)

    def test_exige_login_e_post(self):
        url = reverse('questoes:comentar_questao', args=[self.questao.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        resposta = self.client.post(url, {'texto': 'Oi'})
        self.assertIn(reverse('usuarios:login'), resposta.url)
        self.assertFalse(Comentario.objects.exists())

    def test_publica_comentario_e_volta_para_ele(self):
        resposta = self.comentar('Gabarito correto: art. 28 da Lei 14.133.', next_url='/?ano=2024&page=1')
        comentario = Comentario.objects.get()
        self.assertEqual((comentario.questao, comentario.usuario, comentario.resposta_a),
                         (self.questao, self.usuario, None))
        self.assertEqual(resposta.url, f'/?ano=2024&page=1#comentario-{comentario.id}')

    def test_forum_da_questao_comentada_abre_expandido_uma_vez(self):
        self.comentar('Primeiro!')
        pagina = self.client.get(self.lista)
        self.assertContains(pagina, f'id="comentarios-{self.questao.id}" open')
        self.assertNotContains(pagina, f'id="comentarios-{self.outra_questao.id}" open')
        # Recarregando a página, volta ao normal (recolhido)
        self.assertNotContains(self.client.get(self.lista), f'id="comentarios-{self.questao.id}" open')

    def test_lista_mostra_contagem_comentarios_e_respostas(self):
        outro = get_user_model().objects.create_user('colega', password='senha-forte-123')
        principal = Comentario.objects.create(questao=self.questao, usuario=outro, texto='Por que não é a A?')
        Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='@colega Porque...',
                                  resposta_a=principal)
        pagina = self.client.get(self.lista)
        self.assertContains(pagina, 'Comentários (2)')
        self.assertContains(pagina, 'Comentários (0)')
        self.assertContains(pagina, 'Por que não é a A?')
        self.assertContains(pagina, '@colega Porque...')
        # Botão Responder já com a menção ao autor
        self.assertContains(pagina, f'maxlength="{COMENTARIO_TAMANHO_MAXIMO}" required>@colega </textarea>')

    def test_contagem_nao_duplica_com_filtro_por_materia(self):
        # A questão tem 1 tópico da matéria; com 2 tópicos o JOIN do filtro duplicaria a contagem
        self.questao.topicos.add(self.outro_topico_mesma_materia)
        Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='Único')
        pagina = self.client.get(self.lista, {'materia': self.direito.id})
        self.assertContains(pagina, 'Comentários (1)')

    def test_resposta_a_uma_resposta_entra_na_mesma_conversa(self):
        principal = Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='Comentário')
        resposta = Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='Resposta',
                                             resposta_a=principal)
        self.comentar('@aluno concordo', resposta_a=resposta.id)
        nova = Comentario.objects.latest('id')
        self.assertEqual(nova.resposta_a, principal)

    def test_nao_responde_comentario_de_outra_questao_ou_inexistente(self):
        de_outra = Comentario.objects.create(questao=self.outra_questao, usuario=self.usuario, texto='Outra')
        for resposta_a in (de_outra.id, 999999, 'abc'):
            with self.subTest(resposta_a=resposta_a):
                self.comentar('Tentativa', resposta_a=resposta_a)
        # 'abc' é ignorado (vira comentário principal); os outros dois são recusados
        self.assertEqual(list(self.questao.comentarios.values_list('resposta_a', flat=True)), [None])

    def test_recusa_comentario_vazio_ou_longo_demais_com_aviso_no_card(self):
        for texto in ('   ', 'x' * (COMENTARIO_TAMANHO_MAXIMO + 1)):
            with self.subTest(tamanho=len(texto)):
                resposta = self.comentar(texto)
                self.assertEqual(resposta.url, f'/#comentarios-{self.questao.id}')
                mensagens = [(m.level_tag, m.extra_tags) for m in self.client.get(self.lista).context['messages']]
                self.assertEqual(mensagens, [('warning', str(self.questao.id))])
        self.assertFalse(Comentario.objects.exists())

    def test_aceita_exatamente_o_limite(self):
        self.comentar('x' * COMENTARIO_TAMANHO_MAXIMO)
        self.assertEqual(len(Comentario.objects.get().texto), COMENTARIO_TAMANHO_MAXIMO)

    def test_banco_impede_texto_fora_do_limite(self):
        for texto in ('', 'x' * (COMENTARIO_TAMANHO_MAXIMO + 1)):
            # atomic(): cada erro de integridade fica isolado e não invalida a transação do teste
            with self.subTest(tamanho=len(texto)), self.assertRaises(IntegrityError), transaction.atomic():
                Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto=texto)

    def test_html_digitado_aparece_como_texto(self):
        Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='<script>alert(1)</script>\nFim')
        pagina = self.client.get(self.lista)
        self.assertNotContains(pagina, '<script>alert(1)</script>')
        self.assertContains(pagina, '&lt;script&gt;alert(1)&lt;/script&gt;<br>Fim')

    def test_ignora_next_externo(self):
        resposta = self.comentar('Oi', next_url='https://site-malicioso.com/')
        self.assertTrue(resposta.url.startswith(f"{self.lista}#comentario-"))

    def test_admin_lista_comentarios(self):
        Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='y' * 100)
        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        self.client.force_login(admin)
        resposta = self.client.get(reverse('admin:questoes_comentario_changelist'))
        self.assertContains(resposta, 'y' * 80 + '…')


class CurtidasTests(BaseQuestoesTestCase):
    lista = reverse('questoes:lista_questoes')

    def setUp(self):
        super().setUp()
        self.autor = get_user_model().objects.create_user('autor', password='senha-forte-123')
        self.comentario = Comentario.objects.create(questao=self.questao, usuario=self.autor, texto='Boa questão')
        self.url = reverse('questoes:curtir_comentario', args=[self.comentario.id])

    def curtir(self, json=False, **dados):
        cabecalhos = {'headers': {'Accept': 'application/json'}} if json else {}
        return self.client.post(self.url, dados, **cabecalhos)

    def botao_na_lista(self):
        # Trecho do HTML com o botão de curtir deste comentário
        html = self.client.get(self.lista).content.decode()
        inicio = html.index(f'id="comentario-{self.comentario.id}"')
        return html[inicio:html.index('</form>', inicio)]

    def test_exige_login_e_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertIn(reverse('usuarios:login'), self.curtir().url)
        self.assertEqual(self.comentario.curtidas.count(), 0)

    def test_curtir_e_descurtir_alternam(self):
        self.curtir()
        self.assertEqual(list(self.comentario.curtidas.all()), [self.usuario])
        self.curtir()
        self.assertEqual(self.comentario.curtidas.count(), 0)

    def test_resposta_json_para_o_javascript(self):
        resposta = self.curtir(json=True)
        self.assertEqual(resposta.json(), {'curtido': True, 'total_curtidas': 1})
        resposta = self.curtir(json=True)
        self.assertEqual(resposta.json(), {'curtido': False, 'total_curtidas': 0})

    def test_sem_javascript_volta_ao_comentario_com_o_forum_aberto(self):
        resposta = self.curtir(next='/?ano=2024')
        self.assertEqual(resposta.url, f'/?ano=2024#comentario-{self.comentario.id}')
        self.assertContains(self.client.get(self.lista), f'id="comentarios-{self.questao.id}" open')

    def test_ignora_next_externo(self):
        resposta = self.curtir(next='https://site-malicioso.com/')
        self.assertEqual(resposta.url, f'{self.lista}#comentario-{self.comentario.id}')

    def test_cada_usuario_conta_uma_vez_e_ve_o_proprio_estado(self):
        outros = [get_user_model().objects.create_user(f'fa{i}', password='x') for i in range(2)]
        self.comentario.curtidas.add(*outros)
        # O aluno ainda não curtiu: vê o total dos outros e o botão "Curtir"
        botao = self.botao_na_lista()
        self.assertIn('aria-pressed="false"', botao)
        self.assertIn('Curtir</span>', botao)
        self.assertIn('2<span class="visualmente-oculto"> curtidas</span>', botao)
        # Depois de curtir, vê "Curtido" e o total atualizado
        self.curtir()
        botao = self.botao_na_lista()
        self.assertIn('aria-pressed="true"', botao)
        self.assertIn('Curtido</span>', botao)
        self.assertIn('3<span class="visualmente-oculto"> curtidas</span>', botao)
        # Para outro usuário, o botão continua "Curtir" (o estado é por usuário)
        self.client.force_login(outros[0])
        self.assertIn('aria-pressed="true"', self.botao_na_lista())
        self.client.force_login(self.autor)
        self.assertIn('aria-pressed="false"', self.botao_na_lista())

    def test_curtidas_nao_duplicam_nem_desordenam_a_conversa(self):
        # O Count das curtidas gera GROUP BY: a conversa precisa continuar em ordem cronológica
        segundo = Comentario.objects.create(questao=self.questao, usuario=self.autor, texto='Segundo')
        resposta1 = Comentario.objects.create(questao=self.questao, usuario=self.autor, texto='R1',
                                              resposta_a=self.comentario)
        resposta2 = Comentario.objects.create(questao=self.questao, usuario=self.autor, texto='R2',
                                              resposta_a=self.comentario)
        resposta2.curtidas.add(self.usuario, self.autor)
        segundo.curtidas.add(self.usuario)
        questao = next(q for q in self.client.get(self.lista).context['questoes'] if q == self.questao)
        principais = questao.comentarios_principais
        self.assertEqual(principais, [self.comentario, segundo])
        self.assertEqual(list(principais[0].respostas.all()), [resposta1, resposta2])
        self.assertEqual([r.total_curtidas for r in principais[0].respostas.all()], [0, 2])
        self.assertEqual(questao.total_comentarios, 4)

    def test_numero_de_consultas_nao_cresce_com_as_curtidas(self):
        def consultas():
            with CaptureQueriesContext(connection) as contexto:
                self.client.get(self.lista)
            return len(contexto.captured_queries)

        consultas()  # aquece a sessão
        antes = consultas()
        for i in range(5):
            outro = get_user_model().objects.create_user(f'u{i}', password='x')
            novo = Comentario.objects.create(questao=self.questao, usuario=outro, texto=f'c{i}')
            Comentario.objects.create(questao=self.questao, usuario=outro, texto='r', resposta_a=novo)
            novo.curtidas.add(self.usuario, outro)
        self.assertEqual(consultas(), antes)

    def test_apagar_comentario_ou_usuario_remove_as_curtidas(self):
        Curtida = Comentario.curtidas.through
        fa = get_user_model().objects.create_user('fa', password='x')
        self.comentario.curtidas.add(self.usuario, fa)
        fa.delete()
        self.assertEqual(list(self.comentario.curtidas.all()), [self.usuario])
        self.comentario.delete()
        self.assertEqual(Curtida.objects.count(), 0)


class CurtidasResolucaoTests(BaseQuestoesTestCase):
    lista = reverse('questoes:lista_questoes')

    def setUp(self):
        super().setUp()
        self.resolucao = ResolucaoOficial.objects.create(questao=self.questao, texto='Art. 28 da Lei 14.133.')
        self.url = reverse('questoes:curtir_resolucao', args=[self.resolucao.id])

    def responder(self):
        url = reverse('questoes:responder_questao', args=[self.questao.id])
        return self.client.post(url, {'alternativa': self.certa.id}, follow=True)

    def curtir(self, json=False, **dados):
        cabecalhos = {'headers': {'Accept': 'application/json'}} if json else {}
        return self.client.post(self.url, dados, **cabecalhos)

    def test_exige_login_e_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertIn(reverse('usuarios:login'), self.curtir().url)
        self.assertEqual(self.resolucao.curtidas.count(), 0)

    def test_botao_aparece_junto_com_a_resolucao_depois_de_responder(self):
        self.assertNotContains(self.client.get(self.lista), f'action="{self.url}"')
        pagina = self.responder()
        self.assertContains(pagina, f'id="resolucao-{self.resolucao.id}"')
        self.assertContains(pagina, f'action="{self.url}"')
        self.assertContains(pagina, 'data-alvo="esta resolução"')

    def test_curtir_e_descurtir_alternam_com_json(self):
        # A resposta traz o estado dos dois votos, para o JavaScript atualizar os dois botões
        self.assertEqual(self.curtir(json=True).json(),
                         {'curtido': True, 'total_curtidas': 1, 'descurtido': False, 'total_descurtidas': 0})
        self.assertEqual(self.curtir(json=True).json(),
                         {'curtido': False, 'total_curtidas': 0, 'descurtido': False, 'total_descurtidas': 0})
        self.assertEqual(self.resolucao.curtidas.count(), 0)

    def descurtir(self, json=False, **dados):
        cabecalhos = {'headers': {'Accept': 'application/json'}} if json else {}
        url = reverse('questoes:descurtir_resolucao', args=[self.resolucao.id])
        return self.client.post(url, dados, **cabecalhos)

    def test_descurtir_exige_login_e_post(self):
        url = reverse('questoes:descurtir_resolucao', args=[self.resolucao.id])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertIn(reverse('usuarios:login'), self.descurtir().url)
        self.assertEqual(self.resolucao.descurtidas.count(), 0)

    def test_descurtir_alterna(self):
        self.assertEqual(self.descurtir(json=True).json(),
                         {'curtido': False, 'total_curtidas': 0, 'descurtido': True, 'total_descurtidas': 1})
        self.assertEqual(self.descurtir(json=True).json(),
                         {'curtido': False, 'total_curtidas': 0, 'descurtido': False, 'total_descurtidas': 0})

    def test_curtir_e_descurtir_se_excluem(self):
        self.curtir()
        self.descurtir()
        self.assertEqual((self.resolucao.curtidas.count(), list(self.resolucao.descurtidas.all())),
                         (0, [self.usuario]))
        self.curtir()
        self.assertEqual((list(self.resolucao.curtidas.all()), self.resolucao.descurtidas.count()),
                         ([self.usuario], 0))

    def test_votos_de_varios_usuarios_somam_separado(self):
        outros = [get_user_model().objects.create_user(f'v{i}', password='x') for i in range(3)]
        self.resolucao.curtidas.add(*outros[:2])
        self.resolucao.descurtidas.add(outros[2])
        self.assertEqual(self.descurtir(json=True).json(),
                         {'curtido': False, 'total_curtidas': 2, 'descurtido': True, 'total_descurtidas': 2})

    def test_dois_botoes_na_resolucao_com_totais_corretos(self):
        # Dois Count na mesma consulta: sem distinct os totais sairiam multiplicados
        outros = [get_user_model().objects.create_user(f'w{i}', password='x') for i in range(5)]
        self.resolucao.curtidas.add(*outros[:3])
        self.resolucao.descurtidas.add(*outros[3:])
        self.descurtir()  # o aluno descurte (sem JavaScript): a resolução continua visível
        pagina = self.client.get(self.lista).content.decode()
        inicio = pagina.index(f'id="resolucao-{self.resolucao.id}"')
        trecho = pagina[inicio:pagina.index('</details>', inicio)]
        self.assertIn('data-tipo="curtir"', trecho)
        self.assertIn('data-tipo="descurtir"', trecho)
        self.assertIn('3<span class="visualmente-oculto"> curtidas</span>', trecho)
        self.assertIn('3<span class="visualmente-oculto"> descurtidas</span>', trecho)
        # Só o 👎 está marcado para o aluno
        self.assertIn('aria-pressed="false"', trecho[:trecho.index('data-tipo="descurtir"')])
        self.assertIn('aria-pressed="true"', trecho[trecho.index('data-tipo="descurtir"'):])
        self.assertIn('Descurtido</span>', trecho)

    def test_comentarios_nao_tem_descurtir(self):
        Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='Oi')
        pagina = self.client.get(self.lista).content.decode()
        self.assertNotIn('data-tipo="descurtir"', pagina)
        comentario = Comentario.objects.get()
        resposta = self.client.post(reverse('questoes:curtir_comentario', args=[comentario.id]),
                                    headers={'Accept': 'application/json'})
        self.assertEqual(resposta.json(), {'curtido': True, 'total_curtidas': 1})

    def test_com_javascript_nao_deixa_a_resolucao_aberta_na_proxima_visita(self):
        # Sem recarregar a página, nada deve "sobrar" na sessão para a próxima visita
        self.curtir(json=True)
        self.assertNotContains(self.client.get(self.lista), f'id="resolucao-{self.resolucao.id}"')

    def test_sem_javascript_a_resolucao_continua_visivel_com_o_novo_estado(self):
        self.responder()
        resposta = self.curtir(next='/?ano=2024')
        self.assertEqual(resposta.url, f'/?ano=2024#resolucao-{self.resolucao.id}')
        pagina = self.client.get(self.lista).content.decode()
        inicio = pagina.index(f'id="resolucao-{self.resolucao.id}"')
        trecho = pagina[inicio:pagina.index('</details>', inicio)]
        self.assertIn('aria-pressed="true"', trecho)
        self.assertIn('1<span class="visualmente-oculto"> curtida</span>', trecho)

    def test_estado_e_total_por_usuario(self):
        outros = [get_user_model().objects.create_user(f'fa{i}', password='x') for i in range(3)]
        self.resolucao.curtidas.add(*outros)
        pagina = self.responder().content.decode()
        inicio = pagina.index(f'id="resolucao-{self.resolucao.id}"')
        trecho = pagina[inicio:pagina.index('</details>', inicio)]
        self.assertIn('aria-pressed="false"', trecho)
        self.assertIn('3<span class="visualmente-oculto"> curtidas</span>', trecho)

    def test_curtidas_da_resolucao_e_dos_comentarios_sao_independentes(self):
        comentario = Comentario.objects.create(questao=self.questao, usuario=self.usuario, texto='Oi')
        self.curtir()
        self.assertEqual(comentario.curtidas.count(), 0)
        self.assertEqual(list(self.resolucao.curtidas.all()), [self.usuario])

    def test_resolucao_inexistente(self):
        resposta = self.client.post(reverse('questoes:curtir_resolucao', args=[999999]))
        self.assertEqual(resposta.status_code, 404)
