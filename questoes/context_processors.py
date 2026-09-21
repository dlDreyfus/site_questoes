from .models import Questao


def total_questoes(request):
    """Total de questões cadastradas, para o subcabeçalho de templates/base.html.

    É o valor de páginas sem filtros (ex: importar planilha). A lista de questões e o painel de
    desempenho enviam a própria contagem, já respeitando os filtros escolhidos, e ela prevalece
    sobre esta. Devolve o método (sem chamá-lo): o template só vai ao banco se usar o valor.
    """
    # getattr: requisições que não passaram pelo middleware de autenticação não têm 'user'
    usuario = getattr(request, 'user', None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    return {'total_questoes': Questao.objects.count}
