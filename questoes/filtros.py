"""
Filtros de questões (busca textual, banca, órgão, cargo, matéria, tópico e ano), usados pela lista de
questões, pelo painel "Meu Desempenho" (que filtra o histórico pelas questões respondidas) e pela
criação de simulados.

Cada filtro aceita vários valores ao mesmo tempo (ex: ?banca=1&banca=2): dentro de um filtro vale
qualquer um deles (OU); entre filtros diferentes, todos precisam ser atendidos (E).

Os filtros funcionam em cascata: as opções de cada dropdown são só as que ainda têm questões
com o que foi escolhido nos outros dropdowns (ver FiltrosQuestao.contexto).
"""
from dataclasses import dataclass, field, replace
from functools import reduce
from operator import or_

from django.db.models import Exists, OuterRef, Q, Subquery

from .models import Alternativa, Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Topico

TODOS_OS_CAMPOS = ('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano')

# Situação da questão para o usuário logado. Só a criação de simulados a oferece, porque depende do
# histórico de respostas de quem está logado (por isso não faz parte de TODOS_OS_CAMPOS).
SITUACOES = {
    'erradas': 'Somente questões que errei',
    'nao_resolvidas': 'Questões que ainda não resolvi',
}
# Todos os filtros da tela de novo simulado: os da lista de questões mais a situação
CAMPOS_SIMULADO = TODOS_OS_CAMPOS + ('situacao',)

# Busca textual: aparece em todas as telas com filtros (antes dos dropdowns), por isso não faz parte
# das tuplas de campos acima. Limites evitam consultas enormes vindas de uma URL montada à mão.
BUSCA_TAMANHO_MAXIMO = 200
BUSCA_PALAVRAS_MAXIMO = 10


def parse_int(valor):
    # Converte o parâmetro da URL para inteiro; valores ausentes ou inválidos (ex: ?ano=abc, ?ano=²) viram None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _valores(params, campo):
    """Todos os valores de 'campo' nos parâmetros: QueryDict (request.GET/POST) ou dict (nos testes)."""
    if hasattr(params, 'getlist'):
        return params.getlist(campo)
    valor = params.get(campo)
    if valor is None:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _inteiros(valores):
    """Inteiros válidos, sem repetição e em ordem (os inválidos são ignorados)."""
    return tuple(sorted({numero for numero in map(parse_int, valores) if numero is not None}))


@dataclass
class FiltrosQuestao:
    # Cada filtro guarda os valores escolhidos (tupla vazia = filtro não usado)
    banca: tuple = ()
    orgao: tuple = ()
    cargo: tuple = ()
    materia: tuple = ()
    topico: tuple = ()
    ano: tuple = ()
    # Chaves de SITUACOES: 'erradas' (a última resposta do usuário à questão foi errada) e/ou
    # 'nao_resolvidas' (o usuário nunca respondeu a questão)
    situacao: tuple = ()
    # Texto buscado no enunciado, no código e nas alternativas (cada palavra precisa aparecer)
    busca: str = ''
    # Usuário logado, dono do histórico consultado pela situação. Não é um filtro: não entra em
    # 'ativos' nem nas comparações
    usuario: object | None = field(default=None, repr=False, compare=False)

    @classmethod
    def da_requisicao(cls, params, campos=TODOS_OS_CAMPOS, usuario=None):
        """Lê os filtros da URL (ex: ?busca=licitação&banca=1&banca=2&topico=5). Só os 'campos' indicados
        (e a busca) são aceitos. A situação só vale com um 'usuario' (sem ele não há histórico a
        consultar) e com valores conhecidos."""
        valores = {}
        for campo in campos:
            if campo == 'situacao':
                situacoes = set(_valores(params, 'situacao')) if usuario is not None else set()
                valores[campo] = tuple(chave for chave in SITUACOES if chave in situacoes)
            else:
                valores[campo] = _inteiros(_valores(params, campo))
        # Espaços repetidos viram um só (a busca "  a   b " é a mesma que "a b")
        busca = ' '.join(str(params.get('busca') or '').split())[:BUSCA_TAMANHO_MAXIMO].strip()
        filtros = cls(usuario=usuario, busca=busca, **valores)
        # Tópicos que não são das matérias escolhidas (ex: o usuário desmarcou a matéria deles) são ignorados
        if filtros.materia and filtros.topico:
            filtros.topico = tuple(Topico.objects.filter(
                pk__in=filtros.topico, materia_id__in=filtros.materia,
            ).order_by('pk').values_list('pk', flat=True))
        return filtros

    @property
    def ativos(self):
        """Quantos filtros estão em uso (no celular, o painel de filtros já abre se houver algum)."""
        return bool(self.busca) + sum(bool(getattr(self, campo)) for campo in CAMPOS_SIMULADO)

    def parametros(self, campos=TODOS_OS_CAMPOS):
        """Os filtros em uso como {campo: [valores]} (ex: para reenviá-los num formulário, ou numa URL
        com urlencode(..., doseq=True)). A busca vem primeiro, como na tela."""
        parametros = {'busca': [self.busca]} if self.busca else {}
        parametros.update({campo: list(getattr(self, campo)) for campo in campos if getattr(self, campo)})
        return parametros

    def descricao(self):
        """Resumo legível dos filtros em uso (ex: 'Banca: FGV, CEBRASPE · Ano: 2024'), gravado no simulado."""
        partes = [f'Busca: "{self.busca}"'] if self.busca else []
        for campo, modelo, rotulo in (
            ('banca', Banca, 'Banca'), ('orgao', Orgao, 'Órgão'), ('cargo', Cargo, 'Cargo'),
            ('materia', Materia, 'Matéria'), ('topico', Topico, 'Tópico'),
        ):
            selecionados = getattr(self, campo)
            objetos = modelo.objects.filter(pk__in=selecionados).order_by('pk') if selecionados else []
            # O __str__ do tópico repete a matéria ("Matéria - Tópico"): aqui só o nome dele
            nomes = [objeto.nome if campo == 'topico' else str(objeto) for objeto in objetos]
            if nomes:
                partes.append(f'{rotulo}: {", ".join(nomes)}')
        if self.ano:
            partes.append(f'Ano: {", ".join(str(ano) for ano in sorted(self.ano, reverse=True))}')
        if self.situacao:
            partes.append(' ou '.join(SITUACOES[chave] for chave in self.situacao))
        return ' · '.join(partes) or 'Sem filtros (todas as questões)'

    def aplicar(self, questoes):
        """Filtra um queryset de Questao."""
        for campo, lookup in (('banca', 'banca_id'), ('orgao', 'orgao_id'), ('cargo', 'cargo_id'), ('ano', 'ano')):
            valores = getattr(self, campo)
            if valores:
                questoes = questoes.filter(**{f'{lookup}__in': valores})
        if self.materia or self.topico:
            questoes = questoes.filter(pk__in=self._questoes_das_materias_e_topicos())
        if self.busca:
            questoes = self._da_busca(questoes)
        if self.situacao and self.usuario is not None:
            questoes = self._da_situacao(questoes)
        return questoes

    def _questoes_das_materias_e_topicos(self):
        """Ids das questões que atendem à matéria e ao tópico. Os tópicos marcados refinam a matéria
        deles; uma matéria marcada sem nenhum tópico dela marcado vale inteira. Ex: Administrativo
        (só Licitações) + Constitucional = questões de Licitações ou de qualquer tópico de Constitucional.
        Pela tabela intermediária (subconsulta): uma questão com vários tópicos não aparece repetida."""
        condicoes = []
        if self.topico:
            condicoes.append(Q(topico_id__in=self.topico))
        if self.materia:
            materias = Q(topico__materia_id__in=self.materia)
            if self.topico:
                # Os tópicos já pertencem às matérias escolhidas (validado em da_requisicao)
                refinadas = Topico.objects.filter(pk__in=self.topico).values('materia_id')
                materias &= ~Q(topico__materia_id__in=refinadas)
            condicoes.append(materias)
        return Questao.topicos.through.objects.filter(reduce(or_, condicoes)).values('questao_id')

    def _da_busca(self, questoes):
        """Cada palavra buscada precisa aparecer no enunciado, no código ou em alguma alternativa.
        (No SQLite, maiúsculas e minúsculas só são equivalentes nas letras sem acento.)"""
        for palavra in self.busca.split()[:BUSCA_PALAVRAS_MAXIMO]:
            nas_alternativas = Alternativa.objects.filter(questao=OuterRef('pk'), texto__icontains=palavra)
            questoes = questoes.filter(
                Q(enunciado__icontains=palavra) | Q(codigo__icontains=palavra) | Exists(nas_alternativas)
            )
        return questoes

    def _da_situacao(self, questoes):
        """Restringe às questões numa das situações escolhidas para o usuário (errei / ainda não resolvi)."""
        respostas = HistoricoResolucao.objects.filter(usuario=self.usuario, questao=OuterRef('pk'))
        condicoes = []
        if 'nao_resolvidas' in self.situacao:
            condicoes.append(~Exists(respostas))
        if 'erradas' in self.situacao:
            # Só conta a resposta mais recente. Quem errou e depois acertou a questão já a dominou,
            # então ela sai; o id desempata respostas gravadas no mesmo instante.
            ultima = respostas.order_by('-data_resposta', '-id').values('acertou')[:1]
            questoes = questoes.annotate(ultimo_resultado=Subquery(ultima))
            condicoes.append(Q(ultimo_resultado=False))
        return questoes.filter(reduce(or_, condicoes))

    # --- Cascata: opções de cada dropdown ---------------------------------------------------------
    # Regra: o dropdown de um filtro lista só os valores que aparecem nas questões que atendem a
    # TODOS OS OUTROS filtros escolhidos. O próprio filtro fica de fora da conta, senão o usuário
    # não conseguiria marcar mais valores. Assim, qualquer opção exibida leva a pelo menos uma questão.

    def _disponiveis(self, *campos):
        """Questões que atendem a todos os filtros, menos os de 'campos'."""
        return replace(self, **dict.fromkeys(campos, ())).aplicar(Questao.objects.order_by())

    def _ou_selecionado(self, campo, condicao, lookup='pk'):
        """Soma à condição os valores já escolhidos em 'campo': o dropdown nunca esconde o filtro em uso
        (ex: uma URL antiga com uma combinação que hoje não tem questões)."""
        selecionados = getattr(self, campo)
        return condicao | Q(**{f'{lookup}__in': selecionados}) if selecionados else condicao

    @staticmethod
    def _topicos_das(questoes):
        """Ids de todos os tópicos das questões dadas."""
        return Questao.topicos.through.objects.filter(questao__in=questoes).values('topico_id')

    def _opcoes_da_questao(self, modelo, campo):
        """Bancas, órgãos ou cargos que aparecem nas questões disponíveis."""
        disponiveis = self._disponiveis(campo).values(f'{campo}_id')
        return modelo.objects.filter(self._ou_selecionado(campo, Q(pk__in=disponiveis)))

    def _materias(self):
        if self.topico and not self.materia:
            # Só tópicos marcados: as matérias que combinam são as deles (marcar outra matéria
            # descartaria os tópicos, que precisam pertencer às matérias escolhidas)
            return Materia.objects.filter(topicos__in=self.topico).distinct()
        # Marcar mais uma matéria soma as questões dela: a conta ignora a matéria e o tópico escolhidos
        materias_dos_topicos = Topico.objects.filter(
            pk__in=self._topicos_das(self._disponiveis('materia', 'topico')),
        ).values('materia_id')
        return Materia.objects.filter(self._ou_selecionado('materia', Q(pk__in=materias_dos_topicos)))

    def _topicos(self):
        topicos = Topico.objects.select_related('materia').filter(
            self._ou_selecionado('topico', Q(pk__in=self._topicos_das(self._disponiveis('topico'))))
        )
        if self.materia:
            # Com matérias escolhidas, o dropdown de tópicos mostra só os tópicos delas
            topicos = topicos.filter(materia_id__in=self.materia)
        return topicos

    def _anos(self):
        # Do mais novo pro mais velho
        questoes = Questao.objects.filter(
            self._ou_selecionado('ano', Q(pk__in=self._disponiveis('ano')), lookup='ano')
        )
        return questoes.values_list('ano', flat=True).distinct().order_by('-ano')

    def contexto(self, campos=TODOS_OS_CAMPOS):
        """Dados do template questoes/_filtros.html: busca, opções dos dropdowns (em cascata) e valores
        selecionados. Os querysets são preguiçosos: só vão ao banco os dropdowns que o template exibir."""
        return {
            'filtros_campos': campos,
            'filtros_ativos': self.ativos,
            'busca': self.busca,
            'busca_tamanho_maximo': BUSCA_TAMANHO_MAXIMO,
            'bancas': self._opcoes_da_questao(Banca, 'banca'),
            'orgaos': self._opcoes_da_questao(Orgao, 'orgao').order_by('sigla'),
            'cargos': self._opcoes_da_questao(Cargo, 'cargo').order_by('nome'),
            'materias': self._materias().order_by('nome'),
            'topicos': self._topicos(),
            'anos': self._anos(),
            'situacoes': SITUACOES.items(),
            # Valores marcados de cada filtro: {campo: (valores)}
            'selecionados': {campo: getattr(self, campo) for campo in CAMPOS_SIMULADO},
        }
