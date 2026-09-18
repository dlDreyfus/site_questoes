"""
Filtros de questões (banca, órgão, cargo, matéria, tópico e ano), usados pela lista de questões
e pelo painel "Meu Desempenho" (que filtra o histórico pelas questões respondidas).
"""
from dataclasses import dataclass, fields

from .models import Banca, Cargo, Materia, Orgao, Questao, Topico

TODOS_OS_CAMPOS = ('banca', 'orgao', 'cargo', 'materia', 'topico', 'ano')


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

    @classmethod
    def da_requisicao(cls, params, campos=TODOS_OS_CAMPOS):
        """Lê os filtros da URL (ex: ?banca=1&materia=4&topico=5). Só os 'campos' indicados são aceitos."""
        filtros = cls(**{campo: parse_int(params.get(campo)) for campo in campos})
        # Se o tópico não for da matéria escolhida (ex: o usuário trocou a matéria depois), ele é ignorado
        if filtros.materia is not None and filtros.topico is not None:
            if not Topico.objects.filter(pk=filtros.topico, materia_id=filtros.materia).exists():
                filtros.topico = None
        return filtros

    @property
    def ativos(self):
        """Quantos filtros estão em uso (no celular, o painel de filtros já abre se houver algum)."""
        return sum(getattr(self, campo.name) is not None for campo in fields(self))

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
        return questoes

    def contexto(self, campos=TODOS_OS_CAMPOS):
        """Dados do template questoes/_filtros.html: opções dos dropdowns e valores selecionados.
        Os querysets são preguiçosos: só vão ao banco os dropdowns que o template exibir."""
        topicos = Topico.objects.select_related('materia')
        if self.materia is not None:
            # Com uma matéria escolhida, o dropdown de tópicos mostra só os tópicos dela
            topicos = topicos.filter(materia_id=self.materia)
        return {
            'filtros_campos': campos,
            'filtros_ativos': self.ativos,
            'bancas': Banca.objects.all(),
            'orgaos': Orgao.objects.order_by('sigla'),
            'cargos': Cargo.objects.order_by('nome'),
            'materias': Materia.objects.order_by('nome'),
            'topicos': topicos,
            # Só os anos que possuem questões cadastradas, do mais novo pro mais velho
            'anos': Questao.objects.values_list('ano', flat=True).distinct().order_by('-ano'),
            'banca_selecionada': self.banca,
            'orgao_selecionado': self.orgao,
            'cargo_selecionado': self.cargo,
            'materia_selecionada': self.materia,
            'topico_selecionado': self.topico,
            'ano_selecionado': self.ano,
        }
