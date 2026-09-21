"""
Filtros de questões (banca, órgão, cargo, matéria, tópico e ano), usados pela lista de questões
e pelo painel "Meu Desempenho" (que filtra o histórico pelas questões respondidas).

Os filtros funcionam em cascata: as opções de cada dropdown são só as que ainda têm questões
com o que foi escolhido nos outros dropdowns (ver FiltrosQuestao.contexto).
"""
from dataclasses import dataclass, field, replace

from django.db.models import Exists, OuterRef, Q, Subquery

from .models import Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Topico

TODOS_OS_CAMPOS = ('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano')

# Situação da questão para o usuário logado. Só a criação de simulados a oferece, porque depende do
# histórico de respostas de quem está logado (por isso não faz parte de TODOS_OS_CAMPOS).
SITUACOES = {
    'erradas': 'Somente questões que errei',
    'nao_resolvidas': 'Questões que ainda não resolvi',
}
# Todos os filtros da tela de novo simulado: os da lista de questões mais a situação
CAMPOS_SIMULADO = TODOS_OS_CAMPOS + ('situacao',)


def parse_int(valor):
    # Converte o parâmetro da URL para inteiro; valores ausentes ou inválidos (ex: ?ano=abc, ?ano=²) viram None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


@dataclass
class FiltrosQuestao:
    banca: int | None = None
    orgao: int | None = None
    cargo: int | None = None
    materia: int | None = None
    topico: int | None = None
    ano: int | None = None
    # Chave de SITUACOES: 'erradas' (a última resposta do usuário à questão foi errada) ou
    # 'nao_resolvidas' (o usuário nunca respondeu a questão)
    situacao: str | None = None
    # Usuário logado, dono do histórico consultado pela situação. Não é um filtro: não entra em
    # 'ativos' nem nas comparações
    usuario: object | None = field(default=None, repr=False, compare=False)

    @classmethod
    def da_requisicao(cls, params, campos=TODOS_OS_CAMPOS, usuario=None):
        """Lê os filtros da URL (ex: ?banca=1&materia=4&topico=5). Só os 'campos' indicados são aceitos.
        A situação só vale com um 'usuario' (sem ele não há histórico a consultar) e com um valor conhecido."""
        valores = {}
        for campo in campos:
            if campo == 'situacao':
                situacao = params.get('situacao')
                valores[campo] = situacao if usuario is not None and situacao in SITUACOES else None
            else:
                valores[campo] = parse_int(params.get(campo))
        filtros = cls(usuario=usuario, **valores)
        # Se o tópico não for da matéria escolhida (ex: o usuário trocou a matéria depois), ele é ignorado
        if filtros.materia is not None and filtros.topico is not None:
            if not Topico.objects.filter(pk=filtros.topico, materia_id=filtros.materia).exists():
                filtros.topico = None
        return filtros

    @property
    def ativos(self):
        """Quantos filtros estão em uso (no celular, o painel de filtros já abre se houver algum)."""
        return sum(getattr(self, campo) is not None for campo in CAMPOS_SIMULADO)

    def parametros(self, campos=TODOS_OS_CAMPOS):
        """Os filtros em uso como {campo: valor} (ex: para reenviá-los num formulário ou numa URL)."""
        return {campo: getattr(self, campo) for campo in campos if getattr(self, campo) is not None}

    def descricao(self):
        """Resumo legível dos filtros em uso (ex: 'Banca: FGV · Ano: 2024'), gravado no simulado."""
        partes = []
        for campo, modelo, rotulo in (
            ('banca', Banca, 'Banca'), ('orgao', Orgao, 'Órgão'), ('cargo', Cargo, 'Cargo'),
            ('materia', Materia, 'Matéria'), ('topico', Topico, 'Tópico'),
        ):
            objeto = modelo.objects.filter(pk=getattr(self, campo)).first() if getattr(self, campo) else None
            if objeto is not None:
                # O __str__ do tópico repete a matéria ("Matéria - Tópico"): aqui só o nome dele
                partes.append(f'{rotulo}: {objeto.nome if campo == "topico" else objeto}')
        if self.ano is not None:
            partes.append(f'Ano: {self.ano}')
        if self.situacao is not None:
            partes.append(SITUACOES[self.situacao])
        return ' · '.join(partes) or 'Sem filtros (todas as questões)'

    def aplicar(self, questoes):
        """Filtra um queryset de Questao."""
        for campo, lookup in (('banca', 'banca_id'), ('orgao', 'orgao_id'), ('cargo', 'cargo_id'), ('ano', 'ano')):
            valor = getattr(self, campo)
            if valor is not None:
                questoes = questoes.filter(**{lookup: valor})
        # Tópico e matéria passam pela relação N:M com Tópico: o distinct evita questões repetidas
        # quando a questão tem mais de um tópico da mesma matéria
        if self.topico is not None:
            # O tópico já pertence à matéria escolhida (validado em da_requisicao)
            questoes = questoes.filter(topicos=self.topico).distinct()
        elif self.materia is not None:
            questoes = questoes.filter(topicos__materia_id=self.materia).distinct()
        if self.situacao is not None and self.usuario is not None:
            questoes = self._da_situacao(questoes)
        return questoes

    def _da_situacao(self, questoes):
        """Restringe às questões na situação escolhida para o usuário (errei / ainda não resolvi)."""
        respostas = HistoricoResolucao.objects.filter(usuario=self.usuario, questao=OuterRef('pk'))
        if self.situacao == 'nao_resolvidas':
            return questoes.filter(~Exists(respostas))
        # 'erradas': só conta a resposta mais recente. Quem errou e depois acertou a questão já a
        # dominou, então ela sai; o id desempata respostas gravadas no mesmo instante.
        ultima = respostas.order_by('-data_resposta', '-id').values('acertou')[:1]
        return questoes.annotate(ultimo_resultado=Subquery(ultima)).filter(ultimo_resultado=False)

    # --- Cascata: opções de cada dropdown ---------------------------------------------------------
    # Regra: o dropdown de um filtro lista só os valores que aparecem nas questões que atendem a
    # TODOS OS OUTROS filtros escolhidos. O próprio filtro fica de fora da conta, senão o usuário
    # não conseguiria trocar de valor. Assim, qualquer opção exibida leva a pelo menos uma questão.

    def _disponiveis(self, campo):
        """Questões que atendem a todos os filtros, menos o de 'campo'."""
        return replace(self, **{campo: None}).aplicar(Questao.objects.order_by())

    def _ou_selecionado(self, campo, condicao, lookup='pk'):
        """Soma à condição o valor já escolhido em 'campo': o dropdown nunca esconde o filtro em uso
        (ex: uma URL antiga com uma combinação que hoje não tem questões)."""
        selecionado = getattr(self, campo)
        return condicao if selecionado is None else condicao | Q(**{lookup: selecionado})

    @staticmethod
    def _topicos_das(questoes):
        """Ids de todos os tópicos das questões dadas."""
        return Questao.topicos.through.objects.filter(questao__in=questoes).values('topico_id')

    def _opcoes_da_questao(self, modelo, campo):
        """Bancas, órgãos ou cargos que aparecem nas questões disponíveis."""
        disponiveis = self._disponiveis(campo).values(f'{campo}_id')
        return modelo.objects.filter(self._ou_selecionado(campo, Q(pk__in=disponiveis)))

    def _materias(self):
        if self.topico is not None:
            # Um tópico pertence a uma só matéria: ela é a única que combina com ele
            return Materia.objects.filter(topicos=self.topico)
        materias_dos_topicos = Topico.objects.filter(
            pk__in=self._topicos_das(self._disponiveis('materia')),
        ).values('materia_id')
        return Materia.objects.filter(self._ou_selecionado('materia', Q(pk__in=materias_dos_topicos)))

    def _topicos(self):
        topicos = Topico.objects.select_related('materia').filter(
            self._ou_selecionado('topico', Q(pk__in=self._topicos_das(self._disponiveis('topico'))))
        )
        if self.materia is not None:
            # Com uma matéria escolhida, o dropdown de tópicos mostra só os tópicos dela
            topicos = topicos.filter(materia_id=self.materia)
        return topicos

    def _anos(self):
        # Do mais novo pro mais velho
        questoes = Questao.objects.filter(
            self._ou_selecionado('ano', Q(pk__in=self._disponiveis('ano')), lookup='ano')
        )
        return questoes.values_list('ano', flat=True).distinct().order_by('-ano')

    def contexto(self, campos=TODOS_OS_CAMPOS):
        """Dados do template questoes/_filtros.html: opções dos dropdowns (em cascata) e valores
        selecionados. Os querysets são preguiçosos: só vão ao banco os dropdowns que o template exibir."""
        return {
            'filtros_campos': campos,
            'filtros_ativos': self.ativos,
            'bancas': self._opcoes_da_questao(Banca, 'banca'),
            'orgaos': self._opcoes_da_questao(Orgao, 'orgao').order_by('sigla'),
            'cargos': self._opcoes_da_questao(Cargo, 'cargo').order_by('nome'),
            'materias': self._materias().order_by('nome'),
            'topicos': self._topicos(),
            'anos': self._anos(),
            'situacoes': SITUACOES.items(),
            'situacao_selecionada': self.situacao,
            'banca_selecionada': self.banca,
            'orgao_selecionado': self.orgao,
            'cargo_selecionado': self.cargo,
            'materia_selecionada': self.materia,
            'topico_selecionado': self.topico,
            'ano_selecionado': self.ano,
        }
