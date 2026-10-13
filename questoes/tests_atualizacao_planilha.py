"""Planilha de atualização de questões existentes pelo código (questoes/importacao.py, atualizar_csv)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .importacao import atualizar_csv, importar_csv
from .models import HistoricoResolucao, Questao
from .tests_importacao import LINHA_CE, LINHA_ME, planilha

ME = LINHA_ME['codigo']
CE = LINHA_CE['codigo']


def planilha_bytes(conteudo):
    return SimpleUploadedFile('atualizacao.csv', conteudo, content_type='text/csv')


class AtualizacaoTestCase(TestCase):
    def setUp(self):
        # As duas questões do modelo de planilha, cadastradas pela importação de questões novas
        self.assertTrue(importar_csv(planilha(LINHA_ME, LINHA_CE)).sucesso)
        self.me = Questao.objects.get(codigo=ME)
        self.ce = Questao.objects.get(codigo=CE)

    def atualizar(self, *linhas, **kwargs):
        return atualizar_csv(planilha(*linhas, **kwargs))


class AtualizacaoSucessoTests(AtualizacaoTestCase):
    def test_celula_vazia_mantem_o_valor_atual(self):
        resultado = self.atualizar({'codigo': ME, 'ano': '2022'})
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual(resultado.criados['Questões atualizadas'], 1)
        self.me.refresh_from_db()
        self.assertEqual(self.me.ano, 2022)
        # O resto não mudou
        self.assertEqual((self.me.banca.sigla, self.me.cargo.nome), ('FGV', 'Auditor Federal de Controle Externo'))
        self.assertEqual(self.me.enunciado, LINHA_ME['enunciado'])
        self.assertEqual(self.me.alternativas.get(is_correta=True).texto, 'diálogo competitivo')

    def test_so_a_coluna_codigo_e_obrigatoria_no_cabecalho(self):
        resultado = self.atualizar({'codigo': ME, 'enunciado': 'Novo enunciado'}, colunas=['codigo', 'enunciado'])
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.me.refresh_from_db()
        self.assertEqual(self.me.enunciado, 'Novo enunciado')

    def test_altera_banca_orgao_cargo_materia_e_topicos_criando_os_novos(self):
        resultado = self.atualizar({
            'codigo': ME, 'banca_sigla': 'CESGRANRIO', 'banca_nome': 'Fundação Cesgranrio',
            'orgao_sigla': 'TCE-SP', 'orgao_nome': 'Tribunal de Contas do Estado de São Paulo',
            'cargo': 'Agente de Fiscalização', 'materia': 'Direito Administrativo', 'topicos': 'Contratos',
        })
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual((resultado.criados['Bancas'], resultado.criados['Órgãos'], resultado.criados['Cargos'],
                          resultado.criados['Tópicos']), (1, 1, 1, 1))
        self.me.refresh_from_db()
        self.assertEqual((self.me.banca.sigla, self.me.orgao.sigla, self.me.cargo.nome),
                         ('CESGRANRIO', 'TCE-SP', 'Agente de Fiscalização'))
        self.assertEqual([t.nome for t in self.me.topicos.all()], ['Contratos'])

    def test_altera_gabarito_e_texto_de_alternativas_no_lugar(self):
        ids = list(self.me.alternativas.values_list('pk', flat=True))
        resposta = HistoricoResolucao.objects.create(
            usuario=get_user_model().objects.create_user('aluno', password='senha-forte-123'),
            questao=self.me, alternativa_escolhida_id=ids[1], acertou=False,
        )
        resultado = self.atualizar({'codigo': ME, 'alternativa_b': 'tomada de preços (extinta)', 'gabarito': 'A'})
        self.assertTrue(resultado.sucesso, resultado.erros)
        alternativas = list(self.me.alternativas.all())
        # Mesmas alternativas (mesmos ids): a resposta já dada continua ligada a ela
        self.assertEqual([a.pk for a in alternativas], ids)
        self.assertEqual(alternativas[1].texto, 'tomada de preços (extinta)')
        self.assertEqual([a.ordem for a in alternativas if a.is_correta], [1])
        resposta.refresh_from_db()
        self.assertEqual(resposta.alternativa_escolhida_id, ids[1])

    def test_acrescenta_alternativa_no_fim(self):
        self.assertTrue(importar_csv(planilha({**LINHA_ME, 'codigo': 'ME-4', 'alternativa_e': ''})).sucesso)
        resultado = self.atualizar({'codigo': 'ME-4', 'alternativa_e': 'nova alternativa', 'gabarito': 'E'})
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual(resultado.criados['Alternativas novas'], 1)
        questao = Questao.objects.get(codigo='ME-4')
        self.assertEqual([a.texto for a in questao.alternativas.all() if a.is_correta], ['nova alternativa'])

    def test_gabarito_de_questao_ce(self):
        resultado = self.atualizar({'codigo': CE, 'gabarito': 'CERTO'})
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual([(a.texto, a.is_correta) for a in self.ce.alternativas.all()],
                         [('Certo', True), ('Errado', False)])

    def test_cria_ou_altera_a_resolucao(self):
        self.ce.resolucao.delete()
        resultado = self.atualizar({'codigo': ME, 'resolucao': 'Texto novo.'}, {'codigo': CE, 'resolucao': 'Criada.'})
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual(resultado.criados['Resoluções novas'], 1)
        self.me.refresh_from_db()
        self.ce.refresh_from_db()
        self.assertEqual((self.me.resolucao.texto, self.ce.resolucao.texto), ('Texto novo.', 'Criada.'))

    def test_tipo_igual_ao_atual_e_aceito(self):
        self.assertTrue(self.atualizar({'codigo': ME, 'tipo': 'me', 'ano': '2021'}).sucesso)


class AtualizacaoErrosTests(AtualizacaoTestCase):
    def assertErro(self, resultado, trecho):
        self.assertFalse(resultado.sucesso)
        self.assertTrue(any(trecho in erro for erro in resultado.erros), resultado.erros)

    def test_tudo_ou_nada(self):
        resultado = self.atualizar({'codigo': ME, 'ano': '2020'}, {'codigo': CE, 'ano': 'abc'})
        self.assertErro(resultado, 'Linha 3, coluna "ano"')
        self.me.refresh_from_db()
        self.assertEqual(self.me.ano, 2024)

    def test_codigo_obrigatorio_existente_e_sem_repeticao(self):
        resultado = self.atualizar({'ano': '2020'}, {'codigo': 'NAO-EXISTE', 'ano': '2020'},
                                   {'codigo': ME, 'ano': '2020'}, {'codigo': ME, 'ano': '2021'})
        self.assertErro(resultado, 'Linha 2, coluna "codigo": preenchimento obrigatório')
        self.assertErro(resultado, 'a questão "NAO-EXISTE" não existe no banco de dados')
        self.assertErro(resultado, f'Linha 5, coluna "codigo": "{ME}" repetido (já usado na linha 4)')

    def test_cabecalho_sem_codigo_ou_com_coluna_desconhecida(self):
        self.assertErro(self.atualizar({'ano': '2020'}, colunas=['ano']), 'faltam as colunas "codigo"')
        self.assertErro(atualizar_csv(planilha({'codigo': ME}, colunas=['codigo', 'xyz'])), 'colunas desconhecidas "xyz"')

    def test_codigo_nao_pode_ser_alterado_pela_planilha(self):
        # O código só localiza a questão: um código diferente é tratado como outra questão (inexistente),
        # e não como um código novo para a mesma questão. Nada é renomeado nem criado.
        resultado = self.atualizar({'codigo': f'{ME}-NOVO', 'ano': '2020'})
        self.assertErro(resultado, f'a questão "{ME}-NOVO" não existe no banco de dados')
        self.assertTrue(Questao.objects.filter(codigo=ME).exists())
        self.assertFalse(Questao.objects.filter(codigo=f'{ME}-NOVO').exists())
        # Numa atualização bem-sucedida, o código continua o mesmo
        self.assertTrue(self.atualizar({'codigo': ME, 'enunciado': 'Outro enunciado'}).sucesso)
        self.assertEqual(Questao.objects.get(pk=self.me.pk).codigo, ME)
        self.assertEqual(Questao.objects.count(), 2)

    def test_linha_so_com_o_codigo(self):
        self.assertErro(self.atualizar({'codigo': ME}), 'nada a atualizar')

    def test_nao_muda_o_tipo(self):
        self.assertErro(self.atualizar({'codigo': ME, 'tipo': 'CE'}), 'não é possível mudar o tipo')

    def test_colunas_que_mudam_juntas(self):
        self.assertErro(self.atualizar({'codigo': ME, 'topicos': 'Contratos'}), 'coluna "materia": preencha também')
        self.assertErro(self.atualizar({'codigo': ME, 'orgao_sigla': 'TCU'}), 'coluna "orgao_nome": preencha também')
        self.assertErro(self.atualizar({'codigo': ME, 'banca_nome': 'Outra'}), 'coluna "banca_sigla"')

    def test_mesmas_validacoes_da_importacao(self):
        resultado = self.atualizar(
            {'codigo': ME, 'ano': '1800', 'gabarito': 'X', 'cargo': 'x' * 151},
            {'codigo': CE, 'alternativa_a': 'não pode', 'gabarito': 'TALVEZ'},
        )
        self.assertErro(resultado, 'Linha 2, coluna "ano"')
        self.assertErro(resultado, 'Linha 2, coluna "gabarito": valor "X" inválido para questão ME')
        self.assertErro(resultado, 'Linha 2, coluna "cargo": tem 151 caracteres')
        self.assertErro(resultado, 'Linha 3, coluna "alternativa_a": deve ficar vazia em questões CE')
        self.assertErro(resultado, 'Linha 3, coluna "gabarito": valor "TALVEZ" inválido para questão CE')

    def test_alternativa_nova_sem_pular_letras(self):
        self.assertTrue(importar_csv(planilha({**LINHA_ME, 'codigo': 'ME-3', 'alternativa_d': '', 'alternativa_e': ''})).sucesso)
        self.assertErro(self.atualizar({'codigo': 'ME-3', 'alternativa_e': 'quinta'}), 'coluna "alternativa_d": está vazia')

    def test_conflito_de_banca_com_registro_existente(self):
        self.assertErro(self.atualizar({'codigo': ME, 'banca_sigla': 'FGV2', 'banca_nome': 'Fundação Getulio Vargas'}),
                        'já está cadastrada com a sigla "FGV"')


class AtualizacaoPaginaTests(TestCase):
    url = reverse('questoes:importar_questoes')

    def setUp(self):
        grupo = Group.objects.create(name='Administrador')
        grupo.permissions.add(Permission.objects.get(codename='importar_questoes'))
        admin = get_user_model().objects.create_user('admin', password='senha-forte-123')
        admin.groups.add(grupo)
        self.client.force_login(admin)
        importar_csv(planilha(LINHA_ME, LINHA_CE))

    def enviar(self, arquivo):
        return self.client.post(self.url, {'acao': 'atualizacao', 'atualizacao-arquivo': arquivo}, follow=True)

    def test_painel_de_atualizacao_sem_modelo_proprio(self):
        resposta = self.client.get(self.url)
        html = resposta.content.decode()
        self.assertContains(resposta, 'Somente questões já cadastradas')
        self.assertContains(resposta, 'name="atualizacao-arquivo"')
        # Logo depois do envio de novas questões, sem o painel do modelo de atualização
        self.assertLess(html.index('Envio de novas questões'), html.index('Atualização de questões existentes'))
        self.assertNotContains(resposta, 'modelo de atualização')

    def test_csv_baixado_serve_de_base_para_a_atualizacao(self):
        exportado = self.client.get(reverse('questoes:exportar_questoes')).content.decode('utf-8')
        exportado = exportado.replace(';2024;', ';2021;')
        resposta = self.enviar(planilha_bytes(exportado.encode('utf-8')))
        self.assertContains(resposta, 'aplicada com sucesso: 2 questões atualizadas')
        self.assertEqual(Questao.objects.get(codigo=ME).ano, 2021)

    def test_erro_na_atualizacao(self):
        resposta = self.enviar(planilha_bytes(b'codigo;ano\r\nNAO-EXISTE;2020\r\n'))
        self.assertContains(resposta, 'Atualização cancelada: 1 erro encontrado. Nenhuma questão foi alterada.')
        self.assertContains(resposta, 'a questão &quot;NAO-EXISTE&quot; não existe no banco de dados')

    def test_lista_todos_os_erros_com_linha_coluna_e_motivo(self):
        conteudo = (
            'codigo;ano;tipo;gabarito\r\n'
            f'{ME};1800;;\r\n'
            f'{CE};;ME;\r\n'
            f'{ME};2020;;\r\n'
            'NAO-EXISTE;2020;;\r\n'
        ).encode('utf-8')
        resposta = self.enviar(planilha_bytes(conteudo))
        self.assertContains(resposta, 'Atualização cancelada: 4 erros encontrados. Nenhuma questão foi alterada.')
        for trecho in (
            'Linha 2, coluna &quot;ano&quot;: &quot;1800&quot; não é um ano válido',
            'Linha 3, coluna &quot;tipo&quot;: não é possível mudar o tipo',
            f'Linha 4, coluna &quot;codigo&quot;: &quot;{ME}&quot; repetido (já usado na linha 2)',
            'Linha 5, coluna &quot;codigo&quot;: a questão &quot;NAO-EXISTE&quot; não existe no banco de dados',
        ):
            with self.subTest(trecho=trecho):
                self.assertContains(resposta, trecho)
        self.assertEqual(Questao.objects.get(codigo=ME).ano, 2024)

    def test_erros_do_arquivo_inteiro(self):
        casos = (
            (b'ano\r\n2020\r\n', 'Linha 1 (cabeçalho): faltam as colunas &quot;codigo&quot;'),
            (b'codigo;ano\r\n', 'A planilha não tem nenhuma questão: só o cabeçalho foi encontrado.'),
            (b'codigo;ano;xyz\r\nA;1;2\r\n', 'colunas desconhecidas &quot;xyz&quot;'),
        )
        for conteudo, mensagem in casos:
            with self.subTest(mensagem=mensagem):
                resposta = self.enviar(planilha_bytes(conteudo))
                self.assertContains(resposta, 'Atualização cancelada')
                self.assertContains(resposta, mensagem)

    def test_arquivo_invalido_mostra_o_erro_no_formulario_de_atualizacao(self):
        resposta = self.client.post(self.url, {
            'acao': 'atualizacao',
            'atualizacao-arquivo': SimpleUploadedFile('planilha.xlsx', b'abc', content_type='application/octet-stream'),
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context['form_atualizacao'].errors)
        self.assertFalse(resposta.context['form'].errors)
        self.assertContains(resposta, 'xlsx')
        vazio = self.client.post(self.url, {
            'acao': 'atualizacao', 'atualizacao-arquivo': SimpleUploadedFile('vazio.csv', b'', content_type='text/csv'),
        })
        self.assertTrue(vazio.context['form_atualizacao'].errors)

    def test_envio_de_novas_continua_igual(self):
        resposta = self.client.post(self.url, {'acao': 'novas', 'arquivo': planilha(LINHA_ME)}, follow=True)
        self.assertContains(resposta, 'Importação cancelada')
        self.assertContains(resposta, 'já existe no banco de dados')

    def test_exige_a_permissao_de_importar(self):
        self.client.force_login(get_user_model().objects.create_user('aluno', password='senha-forte-123'))
        self.assertEqual(self.enviar(planilha_bytes(b'codigo;ano\r\n')).status_code, 403)
