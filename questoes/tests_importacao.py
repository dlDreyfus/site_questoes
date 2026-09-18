"""Testes das regras de importação por planilha (questoes/importacao.py)."""
import csv
import io
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from .importacao import COLUNAS, LINHAS_EXEMPLO, importar_csv
from .models import Alternativa, Banca, Cargo, Materia, Orgao, Questao, ResolucaoOficial, Topico

LINHA_ME = LINHAS_EXEMPLO[0]
LINHA_CE = LINHAS_EXEMPLO[1]


def planilha(*linhas, colunas=None, separador=';', codificacao='utf-8'):
    """Monta um arquivo .csv em memória a partir de dicts (colunas ausentes ficam vazias)."""
    colunas = colunas or [c.nome for c in COLUNAS]
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=colunas, delimiter=separador, extrasaction='ignore')
    escritor.writeheader()
    escritor.writerows(linhas)
    return SimpleUploadedFile('questoes.csv', saida.getvalue().encode(codificacao), content_type='text/csv')


def linha(base=LINHA_ME, **alteracoes):
    return {**base, **alteracoes}


class ImportacaoSucessoTests(TestCase):
    def test_importa_me_e_ce_criando_todos_os_registros(self):
        resultado = importar_csv(planilha(LINHA_ME, LINHA_CE))
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual(resultado.criados, {
            'Questões': 2, 'Alternativas': 7, 'Resoluções': 2, 'Bancas': 2, 'Órgãos': 2, 'Cargos': 2,
            'Matérias': 2, 'Tópicos': 3,
        })

        me = Questao.objects.get(codigo='FGV-TCU-2024-001')
        self.assertEqual((me.tipo, me.ano, me.banca.sigla, me.orgao.sigla, me.cargo.nome),
                         ('ME', 2024, 'FGV', 'TCU', 'Auditor Federal de Controle Externo'))
        self.assertEqual([t.nome for t in me.topicos.order_by('nome')], ['Licitações', 'Modalidades de licitação'])
        self.assertEqual({t.materia.nome for t in me.topicos.all()}, {'Direito Administrativo'})
        alternativas = list(me.alternativas.all())
        self.assertEqual([a.ordem for a in alternativas], [1, 2, 3, 4, 5])
        self.assertEqual([a.texto for a in alternativas if a.is_correta], ['diálogo competitivo'])
        self.assertTrue(me.resolucao.texto.startswith('A Lei nº 14.133/2021'))

        ce = Questao.objects.get(codigo='CEBRASPE-TCE-2023-001')
        self.assertEqual([(a.texto, a.is_correta) for a in ce.alternativas.all()], [('Certo', False), ('Errado', True)])

    def test_reaproveita_registros_existentes_sem_diferenciar_maiusculas(self):
        banca = Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV')
        orgao = Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU')
        cargo = Cargo.objects.create(nome='Auditor Federal de Controle Externo')
        materia = Materia.objects.create(nome='Direito Administrativo')
        topico = Topico.objects.create(nome='Licitações', materia=materia)

        resultado = importar_csv(planilha(linha(banca_sigla='fgv', orgao_nome='TRIBUNAL DE CONTAS DA UNIÃO',
                                                materia='direito administrativo', topicos='licitações')))
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual(resultado.criados['Bancas'] + resultado.criados['Órgãos'] + resultado.criados['Cargos']
                         + resultado.criados['Matérias'] + resultado.criados['Tópicos'], 0)
        questao = Questao.objects.get()
        self.assertEqual((questao.banca, questao.orgao, questao.cargo), (banca, orgao, cargo))
        self.assertEqual(list(questao.topicos.all()), [topico])

    def test_varias_linhas_com_a_mesma_banca_nova_criam_uma_so(self):
        resultado = importar_csv(planilha(linha(codigo='A1'), linha(codigo='A2')))
        self.assertTrue(resultado.sucesso, resultado.erros)
        self.assertEqual((resultado.criados['Questões'], resultado.criados['Bancas']), (2, 1))

    def test_me_com_quatro_alternativas_e_colunas_opcionais_ausentes(self):
        colunas = ['banca_sigla', 'orgao_sigla', 'orgao_nome', 'cargo', 'ano', 'tipo', 'materia', 'topicos',
                   'enunciado', 'alternativa_a', 'alternativa_b', 'alternativa_c', 'alternativa_d', 'gabarito']
        resultado = importar_csv(planilha(linha(gabarito='d'), colunas=colunas))
        self.assertTrue(resultado.sucesso, resultado.erros)
        questao = Questao.objects.get()
        self.assertIsNone(questao.codigo)
        self.assertEqual(questao.alternativas.count(), 4)
        self.assertEqual(questao.alternativas.get(is_correta=True).texto, 'registro de preços')
        self.assertFalse(ResolucaoOficial.objects.exists())

    def test_aceita_excel_antigo_cp1252_e_separador_virgula(self):
        for opcoes in ({'codificacao': 'cp1252'}, {'separador': ','}):
            with self.subTest(**opcoes):
                Questao.objects.all().delete()
                resultado = importar_csv(planilha(linha(codigo=None), **opcoes))
                self.assertTrue(resultado.sucesso, resultado.erros)
                self.assertEqual(Questao.objects.get().alternativas.get(is_correta=True).texto, 'diálogo competitivo')

    def test_ignora_linhas_em_branco(self):
        arquivo = planilha(LINHA_ME)
        conteudo = arquivo.read() + b';;;;\r\n\r\n'
        resultado = importar_csv(SimpleUploadedFile('q.csv', conteudo))
        self.assertTrue(resultado.sucesso, resultado.erros)


class ImportacaoErrosTests(TestCase):
    def assertErro(self, arquivo, *esperados):
        resultado = importar_csv(arquivo)
        self.assertFalse(resultado.sucesso)
        for esperado in esperados:
            self.assertIn(esperado, resultado.erros)
        # Tudo ou nada: nada foi gravado em nenhuma tabela
        for model in (Questao, Alternativa, Banca, Orgao, Cargo, Materia, Topico, ResolucaoOficial):
            self.assertFalse(model.objects.exists(), model.__name__)
        return resultado

    def test_uma_linha_errada_impede_toda_a_importacao(self):
        self.assertErro(
            planilha(LINHA_ME, linha(LINHA_CE, ano='20224')),
            f'Linha 3, coluna "ano": "20224" não é um ano válido (use de 1900 a {date.today().year + 1}).',
        )

    def test_aponta_todos_os_erros_de_uma_vez(self):
        resultado = self.assertErro(planilha(
            linha(codigo='X1', gabarito='F'),
            linha(codigo='X2', tipo='ZZ'),
            linha(codigo='X3', enunciado='', topicos=''),
        ))
        self.assertEqual(resultado.erros, [
            'Linha 2, coluna "gabarito": valor "F" inválido para questão ME; use uma letra de A a E.',
            'Linha 3, coluna "tipo": valor "ZZ" inválido; use ME ou CE.',
            'Linha 4, coluna "topicos": preenchimento obrigatório.',
            'Linha 4, coluna "enunciado": preenchimento obrigatório.',
        ])

    def test_codigo_ja_existente_ou_repetido(self):
        importar_csv(planilha(LINHA_ME))
        resultado = importar_csv(planilha(LINHA_ME, linha(LINHA_CE, codigo='NOVO'), linha(LINHA_CE, codigo='NOVO')))
        self.assertEqual(resultado.erros, [
            'Linha 2, coluna "codigo": a questão "FGV-TCU-2024-001" já existe no banco de dados.',
            'Linha 4, coluna "codigo": "NOVO" repetido (já usado na linha 3).',
        ])
        self.assertEqual(Questao.objects.count(), 1)

    def test_alternativas_de_questao_me(self):
        self.assertErro(
            planilha(linha(alternativa_b='', alternativa_d='', gabarito='B')),
            'Linha 2, coluna "alternativa_b": obrigatória em questões ME.',
            'Linha 2, coluna "alternativa_d": está vazia, mas a alternativa E está preenchida (não pule letras).',
        )
        self.assertErro(
            planilha(linha(alternativa_d='', alternativa_e='', gabarito='E')),
            'Linha 2, coluna "gabarito": aponta para a alternativa E, que está vazia.',
        )

    def test_alternativas_e_gabarito_de_questao_ce(self):
        self.assertErro(
            planilha(linha(LINHA_CE, alternativa_a='Certo', gabarito='TALVEZ')),
            'Linha 2, coluna "alternativa_a": deve ficar vazia em questões CE (as alternativas Certo e Errado são '
            'criadas automaticamente).',
            'Linha 2, coluna "gabarito": valor "TALVEZ" inválido para questão CE; use CERTO ou ERRADO.',
        )

    def test_conflito_com_registros_existentes(self):
        Banca.objects.create(nome='Fundação Getulio Vargas', sigla='FGV-RJ')
        Orgao.objects.create(nome='Tribunal de Contas da União', sigla='TCU-DF')
        resultado = importar_csv(planilha(LINHA_ME))
        self.assertEqual(resultado.erros, [
            'Linha 2, coluna "banca_sigla": a banca "Fundação Getulio Vargas" já está cadastrada com a sigla "FGV-RJ".',
            'Linha 2, coluna "orgao_sigla": o órgão "Tribunal de Contas da União" já está cadastrado com a sigla '
            '"TCU-DF".',
        ])

    def test_dados_conflitantes_dentro_da_planilha(self):
        self.assertErro(
            planilha(
                linha(codigo='A'),
                linha(codigo='B', banca_nome='Outro Nome'),
                linha(codigo='C', orgao_sigla='TCU2'),
                linha(codigo='D', banca_sigla='FGV2'),
            ),
            'Linha 3, coluna "banca_nome": "Outro Nome" diverge do nome "Fundação Getulio Vargas" informado na '
            'linha 2 para a mesma sigla "FGV".',
            'Linha 4, coluna "orgao_sigla": "TCU2" diverge da sigla "TCU" informada na linha 2 para o mesmo órgão.',
            'Linha 5, coluna "banca_sigla": o nome "Fundação Getulio Vargas" já foi usado com a sigla "FGV" na '
            'linha 2.',
        )

    def test_texto_maior_que_o_limite(self):
        self.assertErro(
            planilha(linha(banca_sigla='X' * 21)),
            'Linha 2, coluna "banca_sigla": tem 21 caracteres; o máximo é 20.',
        )

    def test_problemas_no_cabecalho(self):
        self.assertErro(
            planilha(LINHA_ME, colunas=[c.nome for c in COLUNAS if c.nome != 'gabarito'] + ['observacao']),
            'Linha 1 (cabeçalho): faltam as colunas "gabarito"; colunas desconhecidas "observacao". Use o modelo de '
            'planilha como referência.',
        )

    def test_linha_com_colunas_a_mais(self):
        arquivo = planilha(LINHA_ME)
        conteudo = arquivo.read() + b'a;' * 20 + b'z\r\n'  # 21 colunas numa linha
        resultado = importar_csv(SimpleUploadedFile('q.csv', conteudo))
        self.assertTrue(any(e.startswith('Linha 3: tem 21 colunas, mas o cabeçalho tem 18.') for e in resultado.erros),
                        resultado.erros)

    def test_campo_grande_demais_ou_aspas_sem_fechar(self):
        # Antes gerava erro 500 (csv.Error não tratado)
        cabecalho = ';'.join(c.nome for c in COLUNAS)
        for nome, conteudo in {
            'campo gigante': f'{cabecalho}\r\n"{"x" * 140_000}"\r\n',
            'aspa sem fechar': f'{cabecalho}\r\nFGV;"começo sem fim;' + 'x' * 140_000 + '\r\n',
        }.items():
            with self.subTest(caso=nome):
                resultado = self.assertErro(SimpleUploadedFile('q.csv', conteudo.encode()))
                self.assertEqual(len(resultado.erros), 1)
                self.assertIn('Não foi possível ler a planilha perto da linha', resultado.erros[0])

    def test_planilha_so_com_cabecalho(self):
        self.assertErro(planilha(), 'A planilha não tem nenhuma questão: só o cabeçalho foi encontrado.')
