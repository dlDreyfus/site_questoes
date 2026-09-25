"""Simulados: conjuntos fixos de questões criados a partir dos filtros (mais "errei" e "ainda não resolvi")."""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from .filtros import CAMPOS_SIMULADO, TODOS_OS_CAMPOS, FiltrosQuestao
from .models import (
    Alternativa, Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Simulado, Topico,
)


class BaseSimuladosTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.usuario = User.objects.create_user('aluno', password='senha-forte-123')
        cls.outro = User.objects.create_user('outro', password='senha-forte-123')
        cls.fgv = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        cls.cebraspe = Banca.objects.create(nome='Cebraspe', sigla='CEBRASPE')
        cls.orgao = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cls.cargo = Cargo.objects.create(nome='Auditor')
        cls.administrativo = Materia.objects.create(nome='Direito Administrativo')
        cls.constitucional = Materia.objects.create(nome='Direito Constitucional')
        cls.licitacoes = Topico.objects.create(nome='Licitações', materia=cls.administrativo)
        cls.contratos = Topico.objects.create(nome='Contratos', materia=cls.administrativo)
        cls.direitos = Topico.objects.create(nome='Direitos Fundamentais', materia=cls.constitucional)

        # q1 tem DOIS tópicos da mesma matéria: os joins não podem contá-la em dobro
        cls.q1 = cls.criar_questao(cls.fgv, 2024, cls.licitacoes, cls.contratos)
        cls.q2 = cls.criar_questao(cls.cebraspe, 2023, cls.contratos)
        cls.q3 = cls.criar_questao(cls.fgv, 2022, cls.direitos)

    @classmethod
    def criar_questao(cls, banca, ano, *topicos):
        questao = Questao.objects.create(
            enunciado=f'Enunciado {banca} {ano}', ano=ano, banca=banca, orgao=cls.orgao, cargo=cls.cargo,
        )
        questao.topicos.add(*topicos)
        questao.errada = Alternativa.objects.create(questao=questao, ordem=1, texto=f'Errada {ano}')
        questao.certa = Alternativa.objects.create(questao=questao, ordem=2, texto=f'Certa {ano}', is_correta=True)
        return questao

    @staticmethod
    def responder(usuario, questao, acertou, simulado=None):
        return HistoricoResolucao.objects.create(
            usuario=usuario, questao=questao, acertou=acertou, simulado=simulado,
            alternativa_escolhida=questao.certa if acertou else questao.errada,
        )

    def setUp(self):
        self.client.force_login(self.usuario)

    def criar_simulado(self, *questoes, usuario=None, nome='Meu simulado'):
        simulado = Simulado.objects.create(usuario=usuario or self.usuario, nome=nome, descricao='Sem filtros')
        simulado.questoes.set(questoes)
        return simulado


class SituacaoDaQuestaoTests(BaseSimuladosTestCase):
    """Os dois filtros novos: 'que errei' e 'ainda não resolvi'."""

    def questoes(self, situacao, usuario=None, **outros):
        filtros = FiltrosQuestao.da_requisicao(
            {'situacao': situacao, **outros}, campos=CAMPOS_SIMULADO, usuario=usuario or self.usuario,
        )
        return set(filtros.aplicar(Questao.objects.all()))

    def test_errei_e_a_ultima_resposta_errada(self):
        self.responder(self.usuario, self.q1, False)
        self.responder(self.usuario, self.q2, False)
        self.responder(self.usuario, self.q2, True)   # errou e depois acertou: já dominou, sai
        self.responder(self.usuario, self.q3, True)
        self.responder(self.usuario, self.q3, False)  # acertou e depois errou: volta
        self.assertEqual(self.questoes('erradas'), {self.q1, self.q3})

    def test_errei_ignora_questoes_nunca_respondidas_e_as_acertadas(self):
        self.responder(self.usuario, self.q1, True)
        self.assertEqual(self.questoes('erradas'), set())

    def test_nao_resolvidas_sao_as_que_o_usuario_nunca_respondeu(self):
        self.responder(self.usuario, self.q1, True)
        self.responder(self.usuario, self.q2, False)
        self.assertEqual(self.questoes('nao_resolvidas'), {self.q3})

    def test_sem_respostas_todas_estao_nao_resolvidas_e_nenhuma_errada(self):
        self.assertEqual(self.questoes('nao_resolvidas'), {self.q1, self.q2, self.q3})
        self.assertEqual(self.questoes('erradas'), set())

    def test_respostas_de_outro_usuario_nao_contam(self):
        self.responder(self.outro, self.q1, False)
        self.responder(self.outro, self.q2, True)
        self.assertEqual(self.questoes('erradas'), set())
        self.assertEqual(self.questoes('nao_resolvidas'), {self.q1, self.q2, self.q3})
        self.assertEqual(self.questoes('erradas', usuario=self.outro), {self.q1})

    def test_situacao_combina_com_os_outros_filtros(self):
        for questao in (self.q1, self.q2, self.q3):
            self.responder(self.usuario, questao, False)
        self.assertEqual(self.questoes('erradas', banca=self.fgv.id), {self.q1, self.q3})
        self.assertEqual(self.questoes('erradas', ano=2023), {self.q2})

    def test_questao_com_dois_topicos_da_mesma_materia_aparece_uma_vez(self):
        self.responder(self.usuario, self.q1, False)
        filtros = FiltrosQuestao.da_requisicao(
            {'situacao': 'erradas', 'materia': self.administrativo.id}, campos=CAMPOS_SIMULADO, usuario=self.usuario,
        )
        self.assertEqual(list(filtros.aplicar(Questao.objects.all())), [self.q1])

    def test_situacao_invalida_ou_sem_usuario_e_ignorada(self):
        self.assertEqual(self.questoes('inexistente'), {self.q1, self.q2, self.q3})
        sem_usuario = FiltrosQuestao.da_requisicao({'situacao': 'erradas'}, campos=CAMPOS_SIMULADO)
        self.assertEqual(sem_usuario.situacao, ())

    def test_lista_e_painel_nao_aceitam_situacao(self):
        # A situação só existe na criação de simulados: nas outras telas o parâmetro é ignorado
        filtros = FiltrosQuestao.da_requisicao({'situacao': 'erradas'}, campos=TODOS_OS_CAMPOS, usuario=self.usuario)
        self.assertEqual(filtros.situacao, ())
        self.assertEqual(filtros.ativos, 0)

    def test_situacao_conta_como_filtro_ativo(self):
        filtros = FiltrosQuestao.da_requisicao(
            {'situacao': 'erradas', 'banca': self.fgv.id}, campos=CAMPOS_SIMULADO, usuario=self.usuario,
        )
        self.assertEqual(filtros.ativos, 2)

    def test_descricao_dos_filtros(self):
        filtros = FiltrosQuestao.da_requisicao(
            {'banca': self.fgv.id, 'topico': self.licitacoes.id, 'ano': 2024, 'situacao': 'nao_resolvidas'},
            campos=CAMPOS_SIMULADO, usuario=self.usuario,
        )
        self.assertEqual(
            filtros.descricao(), 'Banca: FGV · Tópico: Licitações · Ano: 2024 · Questões que ainda não resolvi',
        )
        self.assertEqual(FiltrosQuestao().descricao(), 'Sem filtros (todas as questões)')

    def test_cascata_considera_a_situacao(self):
        # O usuário só errou a q2 (Cebraspe, 2023, Contratos): os outros dropdowns só oferecem o que ela tem
        self.responder(self.usuario, self.q2, False)
        self.responder(self.usuario, self.q1, True)
        resposta = self.client.get(reverse('questoes:novo_simulado'), {'situacao': 'erradas'})
        self.assertEqual(set(resposta.context['bancas']), {self.cebraspe})
        self.assertEqual(set(resposta.context['anos']), {2023})
        self.assertEqual(set(resposta.context['topicos']), {self.contratos})
        self.assertEqual(set(resposta.context['materias']), {self.administrativo})


class NovoSimuladoTests(BaseSimuladosTestCase):
    url = reverse('questoes:novo_simulado')

    def test_exige_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('usuarios:login')}?next={self.url}")

    def test_mostra_todos_os_filtros_e_a_situacao(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        for campo in ('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano', 'situacao'):
            self.assertContains(resposta, f'name="{campo}"')
        self.assertContains(resposta, 'Somente questões que errei')
        self.assertContains(resposta, 'Questões que ainda não resolvi')
        self.assertContains(resposta, 'data-filtros-abertos')
        self.assertContains(resposta, f'action="{self.url}"')

    def test_situacao_escolhida_fica_selecionada(self):
        resposta = self.client.get(self.url, {'situacao': 'erradas'})
        self.assertContains(
            resposta, '<label class="filtro-opcao"><input type="checkbox" name="situacao" value="erradas" checked> '
            'Somente questões que errei</label>', html=True,
        )

    def test_mostra_quantas_questoes_o_simulado_teria(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id})
        self.assertContains(resposta, 'Criar simulado com 2 questões')
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas com os filtros escolhidos</p>')
        resposta = self.client.get(self.url, {'banca': self.cebraspe.id})
        self.assertContains(resposta, 'Criar simulado com 1 questão')

    def test_reenvia_os_filtros_escolhidos_no_formulario_de_criacao(self):
        resposta = self.client.get(self.url, {'banca': self.fgv.id, 'ano': 2024, 'situacao': 'nao_resolvidas'})
        self.assertContains(resposta, f'<input type="hidden" name="banca" value="{self.fgv.id}">', html=True)
        self.assertContains(resposta, '<input type="hidden" name="ano" value="2024">', html=True)
        self.assertContains(resposta, '<input type="hidden" name="situacao" value="nao_resolvidas">', html=True)

    def test_sem_questoes_nao_oferece_o_botao_de_criar(self):
        # Ninguém errou nada ainda: "que errei" não tem questões
        resposta = self.client.get(self.url, {'situacao': 'erradas'})
        self.assertNotContains(resposta, 'Criar simulado com')
        self.assertContains(resposta, 'Nenhuma questão atende a esses filtros')

    def test_valores_invalidos_nao_quebram(self):
        for valor in ('abc', '²', '999999', ''):
            with self.subTest(valor=valor):
                parametros = dict.fromkeys(CAMPOS_SIMULADO, valor)
                self.assertEqual(self.client.get(self.url, parametros).status_code, 200)


class CriarSimuladoTests(BaseSimuladosTestCase):
    url = reverse('questoes:criar_simulado')

    def test_exige_login(self):
        self.client.logout()
        resposta = self.client.post(self.url, {})
        self.assertRedirects(resposta, f"{reverse('usuarios:login')}?next={self.url}")
        self.assertEqual(Simulado.objects.count(), 0)

    def test_so_aceita_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_cria_com_as_questoes_que_atendem_aos_filtros(self):
        resposta = self.client.post(self.url, {'banca': self.fgv.id, 'nome': 'Só FGV'})
        simulado = Simulado.objects.get()
        self.assertRedirects(resposta, reverse('questoes:simulado_detalhe', args=[simulado.id]))
        self.assertEqual(simulado.nome, 'Só FGV')
        self.assertEqual(simulado.usuario, self.usuario)
        self.assertEqual(set(simulado.questoes.all()), {self.q1, self.q3})
        self.assertEqual(simulado.descricao, 'Banca: FGV')

    def test_questao_com_dois_topicos_da_mesma_materia_entra_uma_vez(self):
        self.client.post(self.url, {'materia': self.administrativo.id})
        simulado = Simulado.objects.get()
        self.assertEqual(sorted(simulado.questoes.values_list('pk', flat=True)), sorted([self.q1.pk, self.q2.pk]))

    def test_as_questoes_ficam_congeladas(self):
        self.client.post(self.url, {'banca': self.fgv.id})
        simulado = Simulado.objects.get()
        nova = self.criar_questao(self.fgv, 2021, self.licitacoes)
        self.responder(self.usuario, self.q1, True)
        self.assertEqual(set(simulado.questoes.all()), {self.q1, self.q3})
        self.assertNotIn(nova, simulado.questoes.all())

    def test_somente_questoes_que_errei(self):
        self.responder(self.usuario, self.q1, False)
        self.responder(self.usuario, self.q2, True)
        self.client.post(self.url, {'situacao': 'erradas'})
        self.assertEqual(set(Simulado.objects.get().questoes.all()), {self.q1})
        self.assertEqual(Simulado.objects.get().descricao, 'Somente questões que errei')

    def test_questoes_que_ainda_nao_resolvi(self):
        self.responder(self.usuario, self.q1, True)
        self.responder(self.usuario, self.q2, False)
        self.client.post(self.url, {'situacao': 'nao_resolvidas', 'ano': 2022})
        self.assertEqual(set(Simulado.objects.get().questoes.all()), {self.q3})

    def test_historico_de_outro_usuario_nao_define_a_situacao(self):
        self.responder(self.outro, self.q1, False)
        self.client.post(self.url, {'situacao': 'erradas'})
        self.assertEqual(Simulado.objects.count(), 0)

    def test_sem_filtros_leva_todas_as_questoes(self):
        self.client.post(self.url, {})
        self.assertEqual(Simulado.objects.get().questoes.count(), 3)
        self.assertEqual(Simulado.objects.get().descricao, 'Sem filtros (todas as questões)')

    def test_nome_padrao_e_limite_de_tamanho(self):
        self.client.post(self.url, {'nome': '   '})
        self.assertTrue(Simulado.objects.get().nome.startswith('Simulado de '))
        Simulado.objects.all().delete()
        self.client.post(self.url, {'nome': 'x' * 300})
        self.assertEqual(len(Simulado.objects.get().nome), 100)

    def test_sem_questoes_nao_cria_e_volta_para_a_tela_com_os_filtros(self):
        resposta = self.client.post(self.url, {'banca': self.cebraspe.id, 'ano': 2024})
        self.assertEqual(Simulado.objects.count(), 0)
        # Sem buscar a página do redirecionamento: ela consumiria a mensagem antes de eu conferi-la
        self.assertRedirects(
            resposta, f"{reverse('questoes:novo_simulado')}?banca={self.cebraspe.id}&ano=2024",
            fetch_redirect_response=False,
        )
        self.assertContains(self.client.get(resposta.url), 'Nenhuma questão atende aos filtros escolhidos')

    def test_valores_invalidos_sao_ignorados(self):
        self.client.post(self.url, {'banca': 'abc', 'situacao': 'hack', 'ano': '²'})
        self.assertEqual(Simulado.objects.get().questoes.count(), 3)


class SimuladoDetalheTests(BaseSimuladosTestCase):
    def url(self, simulado):
        return reverse('questoes:simulado_detalhe', args=[simulado.id])

    def test_exige_login(self):
        simulado = self.criar_simulado(self.q1)
        self.client.logout()
        self.assertRedirects(self.client.get(self.url(simulado)), f"{reverse('usuarios:login')}?next={self.url(simulado)}")

    def test_so_o_dono_acessa(self):
        simulado = self.criar_simulado(self.q1, usuario=self.outro)
        self.assertEqual(self.client.get(self.url(simulado)).status_code, 404)

    def test_mostra_so_as_questoes_do_simulado_com_o_formulario_de_resposta(self):
        simulado = self.criar_simulado(self.q1, self.q3, nome='Revisão')
        resposta = self.client.get(self.url(simulado))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'Revisão')
        self.assertContains(resposta, 'Enunciado FGV 2024')
        self.assertContains(resposta, 'Enunciado FGV 2022')
        self.assertNotContains(resposta, 'Enunciado CEBRASPE 2023')
        # A resposta dada aqui fica ligada ao simulado
        self.assertContains(resposta, f'<input type="hidden" name="simulado" value="{simulado.id}">', html=True)
        self.assertContains(resposta, '<strong>2</strong> questões cadastradas neste simulado</p>')

    def test_progresso_conta_so_as_respostas_dadas_no_simulado(self):
        simulado = self.criar_simulado(self.q1, self.q2, self.q3)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        self.responder(self.usuario, self.q2, False, simulado=simulado)
        self.responder(self.usuario, self.q3, True)  # avulsa (fora do simulado): não entra no progresso
        contexto = self.client.get(self.url(simulado)).context
        self.assertEqual((contexto['respondidas'], contexto['acertos'], contexto['erros']), (2, 1, 1))
        self.assertEqual(contexto['percentual'], 50.0)
        self.assertFalse(contexto['concluido'])

    def test_simulado_concluido(self):
        simulado = self.criar_simulado(self.q1, self.q2)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        self.responder(self.usuario, self.q2, True, simulado=simulado)
        resposta = self.client.get(self.url(simulado))
        self.assertTrue(resposta.context['concluido'])
        # Em pt-br o Django escreve o decimal com vírgula
        self.assertContains(resposta, 'Simulado concluído! Você acertou 2 de 2 questões (100,0%).')

    def test_questao_respondida_fica_somente_leitura_com_a_correta_em_destaque(self):
        simulado = self.criar_simulado(self.q1, self.q2)
        self.responder(self.usuario, self.q1, False, simulado=simulado)
        resposta = self.client.get(self.url(simulado))
        self.assertContains(resposta, 'Resultado neste simulado: ✘ Errou')
        self.assertContains(resposta, '✔ Correta')
        self.assertContains(resposta, '✘ Sua resposta')
        # Só a q2 (não respondida) ainda tem formulário de resposta
        self.assertNotContains(resposta, f'action="{reverse("questoes:responder_questao", args=[self.q1.id])}"')
        self.assertContains(resposta, f'action="{reverse("questoes:responder_questao", args=[self.q2.id])}"')

    def test_resposta_certa_marcada_e_indicada_como_tal(self):
        simulado = self.criar_simulado(self.q1)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        resposta = self.client.get(self.url(simulado))
        self.assertContains(resposta, 'Resultado neste simulado: ✔ Acertou')
        self.assertContains(resposta, '✔ Sua resposta (correta)')

    def test_paginacao(self):
        extras = [self.criar_questao(self.fgv, 2000 + i, self.licitacoes) for i in range(11)]
        simulado = self.criar_simulado(*extras)
        resposta = self.client.get(self.url(simulado))
        self.assertEqual(len(resposta.context['questoes']), 10)
        self.assertEqual(resposta.context['pagina'].paginator.count, 11)
        self.assertContains(resposta, 'Página 1 de 2')
        self.assertEqual(len(self.client.get(self.url(simulado), {'page': 2}).context['questoes']), 1)


class ResponderNoSimuladoTests(BaseSimuladosTestCase):
    def responder_via_site(self, questao, simulado=None, alternativa=None, **extras):
        dados = {'alternativa': (alternativa or questao.certa).id, **extras}
        if simulado is not None:
            dados['simulado'] = simulado.id
            dados.setdefault('next', reverse('questoes:simulado_detalhe', args=[simulado.id]))
        return self.client.post(reverse('questoes:responder_questao', args=[questao.id]), dados)

    def test_resposta_fica_registrada_no_simulado_e_no_historico(self):
        simulado = self.criar_simulado(self.q1)
        resposta = self.responder_via_site(self.q1, simulado)
        self.assertRedirects(
            resposta, f"{reverse('questoes:simulado_detalhe', args=[simulado.id])}#questao-{self.q1.id}",
            fetch_redirect_response=False,
        )
        historico = HistoricoResolucao.objects.get()
        self.assertEqual((historico.simulado, historico.usuario, historico.acertou), (simulado, self.usuario, True))

    def test_nao_da_para_responder_duas_vezes_a_mesma_questao_no_simulado(self):
        simulado = self.criar_simulado(self.q1)
        self.responder_via_site(self.q1, simulado, alternativa=self.q1.errada)
        resposta = self.responder_via_site(self.q1, simulado, alternativa=self.q1.certa)
        self.assertEqual(HistoricoResolucao.objects.count(), 1)
        self.assertFalse(HistoricoResolucao.objects.get().acertou)
        pagina = self.client.get(resposta.url.split('#')[0])
        self.assertContains(pagina, 'Você já respondeu esta questão neste simulado.')

    def test_a_constraint_do_banco_impede_duplicar(self):
        simulado = self.criar_simulado(self.q1)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.responder(self.usuario, self.q1, False, simulado=simulado)

    def test_fora_do_simulado_continua_podendo_refazer(self):
        self.responder_via_site(self.q1)
        self.responder_via_site(self.q1)
        self.assertEqual(HistoricoResolucao.objects.filter(simulado__isnull=True).count(), 2)

    def test_simulado_de_outro_usuario_e_ignorado(self):
        alheio = self.criar_simulado(self.q1, usuario=self.outro)
        self.responder_via_site(self.q1, alheio)
        historico = HistoricoResolucao.objects.get()
        self.assertIsNone(historico.simulado)
        self.assertEqual(historico.usuario, self.usuario)

    def test_simulado_que_nao_tem_a_questao_e_ignorado(self):
        simulado = self.criar_simulado(self.q2)
        self.responder_via_site(self.q1, simulado)
        self.assertIsNone(HistoricoResolucao.objects.get().simulado)

    def test_id_de_simulado_invalido_e_ignorado(self):
        for valor in ('abc', '²', '999999'):
            with self.subTest(valor=valor):
                self.client.post(
                    reverse('questoes:responder_questao', args=[self.q1.id]),
                    {'alternativa': self.q1.certa.id, 'simulado': valor},
                )
        self.assertEqual(HistoricoResolucao.objects.count(), 3)
        self.assertFalse(HistoricoResolucao.objects.filter(simulado__isnull=False).exists())

    def test_sem_alternativa_no_simulado_nao_grava(self):
        simulado = self.criar_simulado(self.q1)
        self.client.post(
            reverse('questoes:responder_questao', args=[self.q1.id]), {'simulado': simulado.id},
        )
        self.assertEqual(HistoricoResolucao.objects.count(), 0)

    def test_resolver_no_simulado_alimenta_o_painel_de_desempenho(self):
        simulado = self.criar_simulado(self.q1)
        self.responder_via_site(self.q1, simulado)
        contexto = self.client.get(reverse('usuarios:dashboard')).context
        self.assertEqual((contexto['total'], contexto['acertos']), (1, 1))

    def test_apagar_o_simulado_mantem_as_respostas(self):
        simulado = self.criar_simulado(self.q1)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        simulado.delete()
        historico = HistoricoResolucao.objects.get()
        self.assertIsNone(historico.simulado)

    def test_errar_no_simulado_faz_a_questao_entrar_em_que_errei(self):
        simulado = self.criar_simulado(self.q1)
        self.responder_via_site(self.q1, simulado, alternativa=self.q1.errada)
        self.client.post(reverse('questoes:criar_simulado'), {'situacao': 'erradas'})
        self.assertEqual(set(Simulado.objects.first().questoes.all()), {self.q1})


class NovoSimuladoNaListaTests(BaseSimuladosTestCase):
    """O botão "Novo simulado" da lista de questões, que leva os filtros escolhidos para a tela de criação."""
    lista = reverse('questoes:lista_questoes')
    novo = reverse('questoes:novo_simulado')

    def test_lista_tem_o_botao_sem_filtros_e_com_endereco_limpo(self):
        resposta = self.client.get(self.lista)
        self.assertContains(resposta, f'<a href="{self.novo}" class="btn-desempenho">Novo simulado</a>', html=True)
        # Sem filtros não sobra "?" no endereço
        self.assertNotContains(resposta, f'{self.novo}?')

    def test_botao_leva_os_filtros_escolhidos(self):
        resposta = self.client.get(self.lista, {'banca': self.fgv.id, 'ano': 2024})
        self.assertEqual(resposta.context['url_novo_simulado'], f'{self.novo}?banca={self.fgv.id}&ano=2024')
        self.assertContains(resposta, f'href="{self.novo}?banca={self.fgv.id}&amp;ano=2024"')

    def test_botao_nao_leva_a_pagina_nem_valores_invalidos(self):
        resposta = self.client.get(self.lista, {'banca': self.fgv.id, 'page': 2, 'ano': 'abc', 'x': 'y'})
        self.assertEqual(resposta.context['url_novo_simulado'], f'{self.novo}?banca={self.fgv.id}')

    def test_tela_de_novo_simulado_abre_com_os_filtros_da_lista(self):
        url = self.client.get(self.lista, {'materia': self.administrativo.id, 'ano': 2023}).context['url_novo_simulado']
        resposta = self.client.get(url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta, f'<label class="filtro-opcao"><input type="checkbox" name="materia" '
            f'value="{self.administrativo.id}" checked> Direito Administrativo</label>', html=True,
        )
        self.assertContains(
            resposta, '<label class="filtro-opcao"><input type="checkbox" name="ano" value="2023" checked> 2023</label>',
            html=True,
        )
        self.assertContains(resposta, 'Criar simulado com 1 questão')

    def test_botao_tambem_aparece_na_lista_vazia(self):
        resposta = self.client.get(self.lista, {'banca': self.cebraspe.id, 'ano': 2024})
        self.assertContains(resposta, 'Nenhuma questão encontrada.')
        self.assertContains(resposta, 'Novo simulado')


class MeuDesempenhoSimuladosTests(BaseSimuladosTestCase):
    url = reverse('usuarios:dashboard')

    def test_tem_o_botao_para_criar_simulado(self):
        resposta = self.client.get(self.url)
        self.assertContains(resposta, f'href="{reverse("questoes:novo_simulado")}"')

    def test_sem_simulados_mostra_o_convite_para_criar(self):
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'Meus simulados')
        self.assertContains(resposta, 'Você ainda não criou nenhum simulado.')

    def test_lista_so_os_simulados_do_usuario_com_o_progresso(self):
        simulado = self.criar_simulado(self.q1, self.q2, self.q3, nome='Revisão geral')
        self.criar_simulado(self.q1, usuario=self.outro, nome='Do outro usuário')
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        self.responder(self.usuario, self.q2, False, simulado=simulado)

        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'Revisão geral')
        self.assertNotContains(resposta, 'Do outro usuário')
        self.assertContains(resposta, f'href="{reverse("questoes:simulado_detalhe", args=[simulado.id])}"')
        item = resposta.context['simulados'][0]
        self.assertEqual((item.qtd_questoes, item.qtd_respondidas, item.qtd_acertos), (3, 2, 1))
        self.assertContains(resposta, '2 de 3 respondidas · 1 acerto')
        self.assertNotContains(resposta, 'Você ainda não criou nenhum simulado.')

    def test_simulado_concluido_e_marcado(self):
        simulado = self.criar_simulado(self.q1)
        self.responder(self.usuario, self.q1, True, simulado=simulado)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'simulado-card concluido')
        self.assertContains(resposta, '· Concluído')

    def test_simulado_novo_nao_aparece_como_concluido(self):
        self.criar_simulado(self.q1)
        self.assertNotContains(self.client.get(self.url), 'concluido')

    def test_mais_recentes_primeiro(self):
        antigo = self.criar_simulado(self.q1, nome='Antigo')
        recente = self.criar_simulado(self.q1, nome='Recente')
        simulados = list(self.client.get(self.url).context['simulados'])
        self.assertEqual(simulados, [recente, antigo])

    def test_lista_de_simulados_nao_depende_dos_filtros_do_painel(self):
        self.criar_simulado(self.q1, nome='Revisão geral')
        resposta = self.client.get(self.url, {'banca': self.cebraspe.id})
        self.assertContains(resposta, 'Revisão geral')

    def test_varias_respostas_nao_multiplicam_as_contagens(self):
        # Os Count juntos fazem JOIN de questões e respostas: sem distinct, 3 x 3 = 9
        simulado = self.criar_simulado(self.q1, self.q2, self.q3)
        for questao in (self.q1, self.q2, self.q3):
            self.responder(self.usuario, questao, True, simulado=simulado)
        item = self.client.get(self.url).context['simulados'][0]
        self.assertEqual((item.qtd_questoes, item.qtd_respondidas, item.qtd_acertos), (3, 3, 3))


class EditarSimuladoTests(BaseSimuladosTestCase):
    def setUp(self):
        super().setUp()
        self.simulado = self.criar_simulado(self.q1, self.q2, nome='Nome antigo')
        self.url = reverse('questoes:editar_simulado', args=[self.simulado.id])

    def test_exige_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('usuarios:login')}?next={self.url}")

    def test_mostra_o_formulario_com_o_nome_atual(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, 'value="Nome antigo"')
        self.assertContains(resposta, 'Salvar nome')

    def test_renomeia_e_volta_para_o_simulado(self):
        resposta = self.client.post(self.url, {'nome': '  Revisão nova  '})
        # Sem buscar a página do redirecionamento: ela consumiria a mensagem antes de eu conferi-la
        self.assertRedirects(
            resposta, reverse('questoes:simulado_detalhe', args=[self.simulado.id]), fetch_redirect_response=False,
        )
        self.simulado.refresh_from_db()
        self.assertEqual(self.simulado.nome, 'Revisão nova')
        self.assertContains(self.client.get(resposta.url), 'Nome do simulado atualizado.')

    def test_renomear_nao_mexe_nas_questoes_nem_nas_respostas(self):
        self.responder(self.usuario, self.q1, True, simulado=self.simulado)
        descricao = self.simulado.descricao
        self.client.post(self.url, {'nome': 'Outro nome'})
        self.simulado.refresh_from_db()
        self.assertEqual(set(self.simulado.questoes.all()), {self.q1, self.q2})
        self.assertEqual(self.simulado.descricao, descricao)
        self.assertEqual(self.simulado.resolucoes.count(), 1)

    def test_nome_vazio_ou_grande_demais_e_recusado(self):
        for nome in ('', '   ', 'x' * 101):
            with self.subTest(nome=nome[:10]):
                resposta = self.client.post(self.url, {'nome': nome})
                self.assertEqual(resposta.status_code, 200)
                self.assertTrue(resposta.context['form'].errors)
                self.simulado.refresh_from_db()
                self.assertEqual(self.simulado.nome, 'Nome antigo')

    def test_nome_invalido_nao_troca_o_nome_mostrado_na_pagina(self):
        resposta = self.client.post(self.url, {'nome': ''})
        self.assertContains(resposta, 'Dê um nome ao simulado.')
        self.assertContains(resposta, 'Você pode mudar o nome de "Nome antigo"')

    def test_so_o_dono_edita(self):
        alheio = self.criar_simulado(self.q1, usuario=self.outro, nome='Do outro')
        url = reverse('questoes:editar_simulado', args=[alheio.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {'nome': 'Invadido'}).status_code, 404)
        alheio.refresh_from_db()
        self.assertEqual(alheio.nome, 'Do outro')

    def test_metodo_nao_permitido(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    def test_ha_link_para_editar_no_painel_e_no_simulado(self):
        self.assertContains(self.client.get(reverse('usuarios:dashboard')), f'href="{self.url}"')
        self.assertContains(self.client.get(reverse('questoes:simulado_detalhe', args=[self.simulado.id])), f'href="{self.url}"')


class ApagarSimuladoTests(BaseSimuladosTestCase):
    def setUp(self):
        super().setUp()
        self.simulado = self.criar_simulado(self.q1, self.q2, nome='Para apagar')
        self.url = reverse('questoes:apagar_simulado', args=[self.simulado.id])

    def test_exige_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('usuarios:login')}?next={self.url}")
        self.assertTrue(Simulado.objects.filter(pk=self.simulado.pk).exists())

    def test_get_so_pede_confirmacao_e_nao_apaga(self):
        resposta = self.client.get(self.url)
        # As aspas estão escritas no template (não vêm de variável), então não são escapadas
        self.assertContains(resposta, 'Apagar "Para apagar"?')
        self.assertContains(resposta, 'Sim, apagar')
        self.assertContains(resposta, 'Cancelar')
        self.assertTrue(Simulado.objects.filter(pk=self.simulado.pk).exists())

    def test_confirmacao_avisa_que_as_respostas_ficam(self):
        self.responder(self.usuario, self.q1, True, simulado=self.simulado)
        self.responder(self.usuario, self.q2, False, simulado=self.simulado)
        resposta = self.client.get(self.url)
        self.assertContains(resposta, 'As 2 respostas dadas nele continuam')
        # Sem respostas, o aviso não faz sentido
        self.simulado.resolucoes.all().delete()
        self.assertNotContains(self.client.get(self.url), 'continuam')

    def test_post_apaga_e_volta_para_o_painel_com_mensagem(self):
        resposta = self.client.post(self.url)
        self.assertRedirects(resposta, reverse('usuarios:dashboard'), fetch_redirect_response=False)
        self.assertFalse(Simulado.objects.filter(pk=self.simulado.pk).exists())
        self.assertContains(self.client.get(resposta.url), 'Simulado &quot;Para apagar&quot; apagado.')

    def test_apagar_mantem_as_questoes_e_as_respostas_no_historico(self):
        self.responder(self.usuario, self.q1, True, simulado=self.simulado)
        self.client.post(self.url)
        self.assertEqual(Questao.objects.count(), 3)
        historico = HistoricoResolucao.objects.get()
        self.assertIsNone(historico.simulado)
        # Continua contando no painel de desempenho
        self.assertEqual(self.client.get(reverse('usuarios:dashboard')).context['total'], 1)

    def test_so_apaga_o_simulado_escolhido(self):
        outro_meu = self.criar_simulado(self.q3, nome='Fica')
        self.client.post(self.url)
        self.assertEqual(list(Simulado.objects.all()), [outro_meu])

    def test_so_o_dono_apaga(self):
        alheio = self.criar_simulado(self.q1, usuario=self.outro, nome='Do outro')
        url = reverse('questoes:apagar_simulado', args=[alheio.id])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(Simulado.objects.filter(pk=alheio.pk).exists())

    def test_metodo_nao_permitido(self):
        self.assertEqual(self.client.delete(self.url).status_code, 405)
        self.assertTrue(Simulado.objects.filter(pk=self.simulado.pk).exists())

    def test_simulado_apagado_some_da_lista_e_da_url(self):
        self.client.post(self.url)
        resposta = self.client.get(reverse('usuarios:dashboard'))
        # (a mensagem "apagado" ainda cita o nome, por isso confere a lista, não o texto da página)
        self.assertEqual(list(resposta.context['simulados']), [])
        self.assertNotContains(resposta, 'simulado-card')
        self.assertEqual(
            self.client.get(reverse('questoes:simulado_detalhe', args=[self.simulado.id])).status_code, 404,
        )

    def test_ha_link_para_apagar_no_painel_e_no_simulado(self):
        self.assertContains(self.client.get(reverse('usuarios:dashboard')), f'href="{self.url}"')
        self.assertContains(self.client.get(reverse('questoes:simulado_detalhe', args=[self.simulado.id])), f'href="{self.url}"')

    def test_questoes_do_simulado_apagado_voltam_a_poder_entrar_em_outro(self):
        # Apagar não deixa rastros nas questões: dá para criar outro simulado com elas
        self.client.post(self.url)
        self.client.post(reverse('questoes:criar_simulado'), {})
        self.assertEqual(Simulado.objects.get().questoes.count(), 3)


class SimuladoAdminTests(BaseSimuladosTestCase):
    def test_admin_lista_e_abre_o_simulado(self):
        admin = get_user_model().objects.create_superuser('admin', password='senha-forte-123')
        self.client.force_login(admin)
        simulado = self.criar_simulado(self.q1, self.q2, nome='Revisão')
        resposta = self.client.get(reverse('admin:questoes_simulado_changelist'))
        self.assertContains(resposta, 'Revisão')
        self.assertEqual(self.client.get(reverse('admin:questoes_simulado_change', args=[simulado.id])).status_code, 200)
