"""
Importação de questões por planilha .csv.

Regras (decididas com o usuário):
- Cada linha da planilha é uma questão completa. Bancas, órgãos, cargos, matérias e tópicos
  são reaproveitados quando já existem e criados quando não existem.
- TUDO OU NADA: primeiro todas as linhas são validadas (sem tocar no banco); se houver
  qualquer erro, nada é gravado e cada erro é apontado com linha, coluna e motivo.
- Um "codigo" que já existe no banco (ou repetido na planilha) é erro.

A numeração das linhas é a mesma do Excel: o cabeçalho é a linha 1.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import date

from django.db import DatabaseError, transaction

from .models import Alternativa, Banca, Cargo, Materia, Orgao, Questao, ResolucaoOficial, Topico

LETRAS = 'ABCDE'
SEPARADOR_TOPICOS = '|'
ANO_MINIMO = 1900


@dataclass(frozen=True)
class Coluna:
    nome: str
    obrigatoria: str  # texto exibido na página: "Sim", "Não", "Recomendada", "Só ME"...
    descricao: str
    exemplo: str
    tamanho_maximo: int | None = None


# Colunas aceitas, na ordem do modelo de planilha. Também alimenta a tabela de ajuda da página.
COLUNAS = [
    Coluna('codigo', 'Recomendada', 'Identificador único da questão; impede importar a mesma questão duas vezes',
           'FGV-TCU-2024-001', 50),
    Coluna('banca_sigla', 'Sim', 'Sigla da banca', 'FGV', 20),
    Coluna('banca_nome', 'Não', 'Nome completo, usado só quando a banca ainda não existe', 'Fundação Getulio Vargas',
           100),
    Coluna('orgao_sigla', 'Sim', 'Sigla do órgão', 'TCU', 20),
    Coluna('orgao_nome', 'Sim', 'Nome completo do órgão', 'Tribunal de Contas da União', 150),
    Coluna('cargo', 'Sim', 'Cargo do concurso', 'Auditor Federal de Controle Externo', 150),
    Coluna('ano', 'Sim', 'Ano de aplicação da prova', '2024'),
    Coluna('tipo', 'Sim', 'ME (múltipla escolha) ou CE (certo/errado)', 'ME'),
    Coluna('materia', 'Sim', 'Matéria (disciplina)', 'Direito Administrativo', 100),
    Coluna('topicos', 'Sim', f'Um ou mais tópicos da matéria, separados por "{SEPARADOR_TOPICOS}"',
           'Licitações|Contratos', 150),
    Coluna('enunciado', 'Sim', 'Texto da questão', 'De acordo com a Lei nº 14.133/2021...'),
    Coluna('alternativa_a', 'Só ME', 'Alternativa A (em questões CE, deixe vazia)', 'convite'),
    Coluna('alternativa_b', 'Só ME', 'Alternativa B', 'tomada de preços'),
    Coluna('alternativa_c', 'Não', 'Alternativa C (as alternativas não podem pular letras)', 'diálogo competitivo'),
    Coluna('alternativa_d', 'Não', 'Alternativa D', 'registro de preços'),
    Coluna('alternativa_e', 'Não', 'Alternativa E', 'credenciamento'),
    Coluna('gabarito', 'Sim', 'Letra da correta (ME) ou CERTO/ERRADO (CE)', 'C'),
    Coluna('resolucao', 'Não', 'Comentário ou resolução oficial da questão', 'A Lei nº 14.133/2021 extinguiu...'),
]
COLUNAS_POR_NOME = {coluna.nome: coluna for coluna in COLUNAS}
# Colunas que precisam existir no cabeçalho (as demais podem ser omitidas)
COLUNAS_OBRIGATORIAS_NO_CABECALHO = [
    'banca_sigla', 'orgao_sigla', 'orgao_nome', 'cargo', 'ano', 'tipo', 'materia', 'topicos', 'enunciado', 'gabarito',
]
GABARITOS_CE = {'CERTO': True, 'C': True, 'ERRADO': False, 'E': False}


# Linhas de exemplo do modelo de planilha (uma questão ME e uma CE)
LINHAS_EXEMPLO = [
    {
        'codigo': 'FGV-TCU-2024-001', 'banca_sigla': 'FGV', 'banca_nome': 'Fundação Getulio Vargas',
        'orgao_sigla': 'TCU', 'orgao_nome': 'Tribunal de Contas da União',
        'cargo': 'Auditor Federal de Controle Externo', 'ano': '2024', 'tipo': 'ME',
        'materia': 'Direito Administrativo', 'topicos': 'Licitações|Modalidades de licitação',
        'enunciado': 'De acordo com a Lei nº 14.133/2021, é modalidade de licitação:',
        'alternativa_a': 'convite', 'alternativa_b': 'tomada de preços', 'alternativa_c': 'diálogo competitivo',
        'alternativa_d': 'registro de preços', 'alternativa_e': 'credenciamento', 'gabarito': 'C',
        'resolucao': 'A Lei nº 14.133/2021 (art. 28) prevê pregão, concorrência, concurso, leilão e diálogo '
                     'competitivo. Convite e tomada de preços foram extintos; registro de preços e '
                     'credenciamento são procedimentos auxiliares (art. 78).',
    },
    {
        'codigo': 'CEBRASPE-TCE-2023-001', 'banca_sigla': 'CEBRASPE',
        'banca_nome': 'Centro Brasileiro de Pesquisa em Avaliação e Seleção e de Promoção de Eventos',
        'orgao_sigla': 'TCE-RJ', 'orgao_nome': 'Tribunal de Contas do Estado do Rio de Janeiro',
        'cargo': 'Analista de Controle Externo', 'ano': '2023', 'tipo': 'CE',
        'materia': 'Direito Constitucional', 'topicos': 'Direitos e garantias fundamentais',
        'enunciado': 'Os direitos e garantias expressos na Constituição Federal de 1988 excluem outros '
                     'decorrentes do regime e dos princípios por ela adotados.',
        'gabarito': 'ERRADO',
        'resolucao': 'Errado. Segundo o art. 5º, § 2º, da CF/1988, os direitos e garantias expressos na '
                     'Constituição não excluem outros decorrentes do regime e dos princípios por ela adotados.',
    },
]


class ErroArquivo(Exception):
    """Problema no arquivo como um todo (codificação, cabeçalho, sem linhas)."""


@dataclass
class ResultadoImportacao:
    erros: list[str] = field(default_factory=list)
    # Quantos registros foram criados em cada tabela, ex: {'Questões': 10, 'Bancas': 1}
    criados: dict[str, int] = field(default_factory=dict)

    @property
    def sucesso(self):
        return not self.erros


def gerar_modelo_csv():
    """Conteúdo do modelo de planilha: cabeçalho + linhas de exemplo, pronto para o Excel."""
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=[c.nome for c in COLUNAS], delimiter=';', lineterminator='\r\n')
    escritor.writeheader()
    escritor.writerows(LINHAS_EXEMPLO)
    # O BOM (﻿) avisa o Excel que o arquivo é UTF-8; sem ele os acentos aparecem trocados
    return '﻿' + saida.getvalue()


def importar_csv(arquivo):
    """Valida todas as linhas e, só se não houver nenhum erro, grava tudo numa transação única."""
    try:
        linhas = _ler_csv(arquivo)
    except ErroArquivo as erro:
        return ResultadoImportacao(erros=[str(erro)])

    validador = _Validador()
    planos = [plano for numero, linha in linhas if (plano := validador.validar(numero, linha))]
    if validador.erros:
        return ResultadoImportacao(erros=validador.erros)

    try:
        with transaction.atomic():
            criados = _Gravador(validador).gravar(planos)
    except DatabaseError as erro:
        # Não deveria acontecer (tudo foi validado antes), mas se acontecer nada fica gravado
        return ResultadoImportacao(erros=[f'Erro ao gravar no banco de dados ({erro}). Nenhum registro foi gravado.'])
    return ResultadoImportacao(criados=criados)


def _ler_csv(arquivo):
    """Devolve [(número da linha no Excel, {coluna: valor}), ...] ou levanta ErroArquivo."""
    conteudo = arquivo.read()
    # "CSV UTF-8" do Excel vem com BOM (utf-8-sig); o "CSV (separado por vírgulas)" vem em cp1252
    for codificacao in ('utf-8-sig', 'cp1252'):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErroArquivo('Não foi possível ler o arquivo: salve a planilha como "CSV UTF-8".')

    primeira_linha = texto.split('\n', 1)[0]
    # O Excel em português usa ";"; se o cabeçalho não tiver ";", aceita ","
    separador = ';' if ';' in primeira_linha else ','
    leitor = csv.reader(io.StringIO(texto, newline=''), delimiter=separador)
    try:
        registros = list(leitor)
    except csv.Error:
        # Ex: campo maior que o limite do leitor de CSV (131.072 caracteres), que costuma ser uma
        # aspa sem fechar "engolindo" o resto do arquivo. line_num é a linha física do arquivo.
        raise ErroArquivo(
            f'Não foi possível ler a planilha perto da linha {leitor.line_num} do arquivo: há um campo '
            'grande demais, geralmente causado por aspas (") abertas e não fechadas. Corrija e envie novamente.'
        )
    if not registros:
        raise ErroArquivo('O arquivo está vazio.')

    cabecalho = [nome.strip().lower() for nome in registros[0]]
    _validar_cabecalho(cabecalho)

    linhas = []
    # enumerate a partir de 2: o cabeçalho é a linha 1 no Excel
    for numero, valores in enumerate(registros[1:], start=2):
        if not any(valor.strip() for valor in valores):
            continue  # linha em branco (comum no fim de planilhas do Excel)
        if len(valores) > len(cabecalho):
            linhas.append((numero, {'__erro__': (
                f'tem {len(valores)} colunas, mas o cabeçalho tem {len(cabecalho)}. Verifique se algum texto '
                f'contém "{separador}" sem estar entre aspas.'
            )}))
            continue
        valores += [''] * (len(cabecalho) - len(valores))
        linhas.append((numero, {nome: valor.strip() for nome, valor in zip(cabecalho, valores)}))

    if not linhas:
        raise ErroArquivo('A planilha não tem nenhuma questão: só o cabeçalho foi encontrado.')
    return linhas


def _validar_cabecalho(cabecalho):
    problemas = []
    faltando = [nome for nome in COLUNAS_OBRIGATORIAS_NO_CABECALHO if nome not in cabecalho]
    if faltando:
        problemas.append('faltam as colunas ' + ', '.join(f'"{nome}"' for nome in faltando))
    desconhecidas = [nome for nome in cabecalho if nome and nome not in COLUNAS_POR_NOME]
    if desconhecidas:
        problemas.append('colunas desconhecidas ' + ', '.join(f'"{nome}"' for nome in desconhecidas))
    repetidas = sorted({nome for nome in cabecalho if nome and cabecalho.count(nome) > 1})
    if repetidas:
        problemas.append('colunas repetidas ' + ', '.join(f'"{nome}"' for nome in repetidas))
    if problemas:
        raise ErroArquivo(
            'Linha 1 (cabeçalho): ' + '; '.join(problemas) + '. Use o modelo de planilha como referência.'
        )


@dataclass
class _Plano:
    """Uma linha já validada, pronta para ser gravada."""
    codigo: str | None
    banca_sigla: str
    banca_nome: str
    orgao_sigla: str
    orgao_nome: str
    cargo: str
    ano: int
    tipo: str
    materia: str
    topicos: list[str]
    enunciado: str
    alternativas: list[tuple[str, bool]]  # [(texto, é a correta?), ...] na ordem
    resolucao: str


class _Validador:
    """Valida linha a linha, acumulando TODOS os erros (sem gravar nada no banco)."""

    def __init__(self):
        self.erros = []
        # Registros existentes, carregados uma vez só (evita uma consulta por linha)
        self.bancas_por_sigla = {b.sigla.lower(): b for b in Banca.objects.exclude(sigla__isnull=True).exclude(sigla='')}
        self.bancas_por_nome = {b.nome.lower(): b for b in Banca.objects.all()}
        self.orgaos_por_nome = {o.nome.lower(): o for o in Orgao.objects.all()}
        self.cargos = {c.nome.lower(): c for c in Cargo.objects.all()}
        self.materias = {m.nome.lower(): m for m in Materia.objects.all()}
        self.topicos = {(t.materia_id, t.nome.lower()): t for t in Topico.objects.all()}
        self.codigos_no_banco = set(Questao.objects.exclude(codigo__isnull=True).values_list('codigo', flat=True))
        # O que já apareceu na planilha: para detectar repetições e informações conflitantes
        self.codigos_na_planilha = {}      # código -> linha
        self.novas_bancas = {}             # sigla -> (nome, linha)
        self.novas_bancas_por_nome = {}    # nome -> (sigla, linha)
        self.novos_orgaos = {}             # nome -> (sigla, linha)

    def erro(self, numero, coluna, mensagem):
        prefixo = f'Linha {numero}, coluna "{coluna}"' if coluna else f'Linha {numero}'
        self.erros.append(f'{prefixo}: {mensagem}')

    def validar(self, numero, linha):
        if '__erro__' in linha:
            self.erro(numero, None, linha['__erro__'])
            return None

        erros_antes = len(self.erros)
        valor = lambda coluna: linha.get(coluna, '')  # noqa: E731 — colunas opcionais podem faltar

        for coluna in ('banca_sigla', 'orgao_sigla', 'orgao_nome', 'cargo', 'ano', 'tipo', 'materia', 'topicos',
                       'enunciado', 'gabarito'):
            if not valor(coluna):
                self.erro(numero, coluna, 'preenchimento obrigatório.')
        for nome, coluna in COLUNAS_POR_NOME.items():
            if coluna.tamanho_maximo and len(valor(nome)) > coluna.tamanho_maximo:
                self.erro(numero, nome, f'tem {len(valor(nome))} caracteres; o máximo é {coluna.tamanho_maximo}.')

        codigo = valor('codigo') or None
        if codigo:
            if codigo in self.codigos_no_banco:
                self.erro(numero, 'codigo', f'a questão "{codigo}" já existe no banco de dados.')
            elif codigo in self.codigos_na_planilha:
                self.erro(numero, 'codigo', f'"{codigo}" repetido (já usado na linha {self.codigos_na_planilha[codigo]}).')
            else:
                self.codigos_na_planilha[codigo] = numero

        ano = self._validar_ano(numero, valor('ano'))
        self._validar_banca(numero, valor('banca_sigla'), valor('banca_nome'))
        self._validar_orgao(numero, valor('orgao_sigla'), valor('orgao_nome'))
        topicos = self._validar_topicos(numero, valor('topicos'))
        tipo = valor('tipo').upper()
        alternativas = None
        if valor('tipo') and tipo not in Questao.TipoQuestao.values:
            self.erro(numero, 'tipo', f'valor "{valor("tipo")}" inválido; use ME ou CE.')
        elif tipo:
            alternativas = self._validar_alternativas(numero, tipo, linha, valor('gabarito'))

        if len(self.erros) > erros_antes:
            return None
        return _Plano(
            codigo=codigo, banca_sigla=valor('banca_sigla'), banca_nome=valor('banca_nome'),
            orgao_sigla=valor('orgao_sigla'), orgao_nome=valor('orgao_nome'), cargo=valor('cargo'), ano=ano,
            tipo=tipo, materia=valor('materia'), topicos=topicos, enunciado=valor('enunciado'),
            alternativas=alternativas, resolucao=valor('resolucao'),
        )

    def _validar_ano(self, numero, texto):
        if not texto:
            return None
        ano_maximo = date.today().year + 1
        try:
            ano = int(texto)
        except ValueError:
            ano = None
        if ano is None or not ANO_MINIMO <= ano <= ano_maximo:
            self.erro(numero, 'ano', f'"{texto}" não é um ano válido (use de {ANO_MINIMO} a {ano_maximo}).')
            return None
        return ano

    def _validar_banca(self, numero, sigla, nome):
        if not sigla:
            return
        existente = self.bancas_por_sigla.get(sigla.lower()) or self.bancas_por_nome.get((nome or sigla).lower())
        if existente:
            if existente.sigla and existente.sigla.lower() != sigla.lower():
                self.erro(numero, 'banca_sigla', f'a banca "{existente.nome}" já está cadastrada com a sigla '
                                                 f'"{existente.sigla}".')
            return
        # Banca nova: todas as linhas com a mesma sigla precisam trazer o mesmo nome,
        # e o nome (único no banco) não pode ser usado por outra sigla nova
        nome_final = nome or sigla
        anterior = self.novas_bancas.setdefault(sigla.lower(), (nome_final, numero))
        if anterior[0].lower() != nome_final.lower():
            self.erro(numero, 'banca_nome', f'"{nome_final}" diverge do nome "{anterior[0]}" informado na linha '
                                            f'{anterior[1]} para a mesma sigla "{sigla}".')
            return
        sigla_do_nome, linha_do_nome = self.novas_bancas_por_nome.setdefault(nome_final.lower(), (sigla, numero))
        if sigla_do_nome.lower() != sigla.lower():
            self.erro(numero, 'banca_sigla', f'o nome "{nome_final}" já foi usado com a sigla "{sigla_do_nome}" '
                                             f'na linha {linha_do_nome}.')

    def _validar_orgao(self, numero, sigla, nome):
        if not (sigla and nome):
            return
        existente = self.orgaos_por_nome.get(nome.lower())
        if existente:
            if existente.sigla.lower() != sigla.lower():
                self.erro(numero, 'orgao_sigla', f'o órgão "{existente.nome}" já está cadastrado com a sigla '
                                                 f'"{existente.sigla}".')
            return
        anterior = self.novos_orgaos.setdefault(nome.lower(), (sigla, numero))
        if anterior[0].lower() != sigla.lower():
            self.erro(numero, 'orgao_sigla', f'"{sigla}" diverge da sigla "{anterior[0]}" informada na linha '
                                             f'{anterior[1]} para o mesmo órgão.')

    def _validar_topicos(self, numero, texto):
        topicos, vistos = [], set()
        for nome in (parte.strip() for parte in texto.split(SEPARADOR_TOPICOS)):
            if nome and nome.lower() not in vistos:
                vistos.add(nome.lower())
                topicos.append(nome)
        if texto and not topicos:
            self.erro(numero, 'topicos', f'informe ao menos um tópico (vários separados por "{SEPARADOR_TOPICOS}").')
        for nome in topicos:
            if len(nome) > COLUNAS_POR_NOME['topicos'].tamanho_maximo:
                self.erro(numero, 'topicos', f'o tópico "{nome[:30]}..." passa de '
                                             f'{COLUNAS_POR_NOME["topicos"].tamanho_maximo} caracteres.')
        return topicos

    def _validar_alternativas(self, numero, tipo, linha, gabarito):
        textos = [linha.get(f'alternativa_{letra.lower()}', '') for letra in LETRAS]
        gabarito = gabarito.upper()

        if tipo == Questao.TipoQuestao.CERTO_ERRADO:
            for letra, texto in zip(LETRAS, textos):
                if texto:
                    self.erro(numero, f'alternativa_{letra.lower()}', 'deve ficar vazia em questões CE '
                                                                      '(as alternativas Certo e Errado são criadas '
                                                                      'automaticamente).')
            if gabarito and gabarito not in GABARITOS_CE:
                self.erro(numero, 'gabarito', f'valor "{gabarito}" inválido para questão CE; use CERTO ou ERRADO.')
                return None
            certo = GABARITOS_CE.get(gabarito, True)
            return [('Certo', certo), ('Errado', not certo)]

        # Múltipla escolha: A e B obrigatórias; C, D e E opcionais, mas sem pular letras
        for letra, texto in zip('AB', textos):
            if not texto:
                self.erro(numero, f'alternativa_{letra.lower()}', 'obrigatória em questões ME.')
        ultima = max((i for i, texto in enumerate(textos) if texto), default=-1)
        for i in range(2, ultima):
            if not textos[i]:
                self.erro(numero, f'alternativa_{LETRAS[i].lower()}',
                          f'está vazia, mas a alternativa {LETRAS[ultima]} está preenchida (não pule letras).')
        if gabarito:
            if gabarito not in LETRAS:
                self.erro(numero, 'gabarito', f'valor "{gabarito}" inválido para questão ME; use uma letra de A a E.')
            elif LETRAS.index(gabarito) > ultima:
                self.erro(numero, 'gabarito', f'aponta para a alternativa {gabarito}, que está vazia.')
        return [(texto, LETRAS[i] == gabarito) for i, texto in enumerate(textos[:ultima + 1])]


class _Gravador:
    """Grava as linhas validadas, reaproveitando ou criando os registros relacionados."""

    def __init__(self, validador):
        self.v = validador
        self.criados = {
            'Questões': 0, 'Alternativas': 0, 'Resoluções': 0, 'Bancas': 0, 'Órgãos': 0, 'Cargos': 0,
            'Matérias': 0, 'Tópicos': 0,
        }

    def gravar(self, planos):
        for plano in planos:
            questao = Questao.objects.create(
                codigo=plano.codigo, enunciado=plano.enunciado, tipo=plano.tipo, ano=plano.ano,
                banca=self._banca(plano), orgao=self._orgao(plano), cargo=self._cargo(plano.cargo),
            )
            materia = self._materia(plano.materia)
            questao.topicos.set([self._topico(materia, nome) for nome in plano.topicos])
            Alternativa.objects.bulk_create([
                Alternativa(questao=questao, ordem=ordem, texto=texto, is_correta=correta)
                for ordem, (texto, correta) in enumerate(plano.alternativas, start=1)
            ])
            self.criados['Questões'] += 1
            self.criados['Alternativas'] += len(plano.alternativas)
            if plano.resolucao:
                ResolucaoOficial.objects.create(questao=questao, texto=plano.resolucao)
                self.criados['Resoluções'] += 1
        return self.criados

    def _banca(self, plano):
        v = self.v
        banca = v.bancas_por_sigla.get(plano.banca_sigla.lower()) or v.bancas_por_nome.get(
            (plano.banca_nome or plano.banca_sigla).lower())
        if banca is None:
            banca = Banca.objects.create(sigla=plano.banca_sigla, nome=plano.banca_nome or plano.banca_sigla)
            v.bancas_por_sigla[banca.sigla.lower()] = v.bancas_por_nome[banca.nome.lower()] = banca
            self.criados['Bancas'] += 1
        return banca

    def _orgao(self, plano):
        orgao = self.v.orgaos_por_nome.get(plano.orgao_nome.lower())
        if orgao is None:
            orgao = Orgao.objects.create(nome=plano.orgao_nome, sigla=plano.orgao_sigla)
            self.v.orgaos_por_nome[orgao.nome.lower()] = orgao
            self.criados['Órgãos'] += 1
        return orgao

    def _cargo(self, nome):
        cargo = self.v.cargos.get(nome.lower())
        if cargo is None:
            cargo = self.v.cargos[nome.lower()] = Cargo.objects.create(nome=nome)
            self.criados['Cargos'] += 1
        return cargo

    def _materia(self, nome):
        materia = self.v.materias.get(nome.lower())
        if materia is None:
            materia = self.v.materias[nome.lower()] = Materia.objects.create(nome=nome)
            self.criados['Matérias'] += 1
        return materia

    def _topico(self, materia, nome):
        chave = (materia.id, nome.lower())
        topico = self.v.topicos.get(chave)
        if topico is None:
            topico = self.v.topicos[chave] = Topico.objects.create(materia=materia, nome=nome)
            self.criados['Tópicos'] += 1
        return topico
