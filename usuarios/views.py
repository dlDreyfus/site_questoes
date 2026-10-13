import unicodedata

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render, redirect
from questoes.filtros import FiltrosQuestao
from questoes.models import HistoricoResolucao, Materia, Questao, Simulado, Topico
from .forms import CadastroUsuarioForm


# Cadastro de novo usuário: cria a conta já ativa, faz o login e leva para as questões
def cadastro(request):
    # Quem já está logado não precisa se cadastrar de novo
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    if request.method == 'POST':
        form = CadastroUsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)
            messages.success(request, f'Conta criada com sucesso. Bem-vindo(a), {usuario.username}!')
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = CadastroUsuarioForm()

    return render(request, 'usuarios/cadastro.html', {'form': form})


# Filtros disponíveis no painel de desempenho (a lista de questões tem também órgão e ano)
FILTROS_DASHBOARD = ('banca', 'cargo', 'materia', 'topico')


def _percentual(acertos, total):
    # Evita divisão por zero quando não há respostas
    return round(acertos / total * 100, 1) if total else 0


def _ordem_alfabetica(nome):
    # "Ética" entre "Economia" e "Finanças", e não depois de "Z" (a ordem do banco compara bytes)
    return unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode().casefold()


def _respostas_por(historico, campo):
    """{id: (total, acertos)} das respostas agrupadas por 'campo' (matéria ou tópico da questão).
    distinct=True: uma questão com dois tópicos da mesma matéria aparece duas vezes no JOIN, e a
    resposta não pode contar em dobro para a matéria."""
    linhas = historico.order_by().values(campo).annotate(
        total=Count('id', distinct=True),
        acertos=Count('id', filter=Q(acertou=True), distinct=True),
    )
    return {linha[campo]: (linha['total'], linha['acertos']) for linha in linhas if linha[campo] is not None}


def _topicos_dos_filtros(filtros):
    """Tópicos que podem aparecer no detalhamento. Com matéria ou tópico nos filtros, só os escolhidos:
    um tópico marcado vale sozinho; uma matéria marcada sem tópico dela marcado vale com todos os tópicos
    (a mesma regra de FiltrosQuestao). Sem esses filtros, todos."""
    topicos = Topico.objects.all()
    if not (filtros.materia or filtros.topico):
        return topicos
    refinadas = Topico.objects.filter(pk__in=filtros.topico).values('materia_id')
    return topicos.filter(Q(pk__in=filtros.topico) | (Q(materia_id__in=filtros.materia) & ~Q(materia_id__in=refinadas)))


def _desempenho_por_materia(historico, filtros):
    """Matérias que o usuário já resolveu, em ordem alfabética, cada uma com os tópicos dela (também em
    ordem alfabética). Cada linha traz o total de respostas, os percentuais de acerto e de erro do usuário
    e o percentual de acerto de todos os usuários (nas mesmas questões dos filtros)."""
    topicos = {topico.pk: topico for topico in _topicos_dos_filtros(filtros).select_related('materia')}
    do_usuario_materia = _respostas_por(historico, 'questao__topicos__materia')
    do_usuario_topico = {
        pk: valores for pk, valores in _respostas_por(historico, 'questao__topicos').items() if pk in topicos
    }
    materias_permitidas = {topico.materia_id for topico in topicos.values()}
    do_usuario_materia = {pk: valores for pk, valores in do_usuario_materia.items() if pk in materias_permitidas}
    if not do_usuario_materia:
        return []

    # Todos os usuários (inclusive o logado), só nas questões das matérias que aparecem no painel
    geral = HistoricoResolucao.objects.filter(
        questao__in=Questao.objects.filter(topicos__materia__in=do_usuario_materia),
    )
    if filtros.ativos:
        geral = geral.filter(questao__in=filtros.aplicar(Questao.objects.all()))
    geral_materia = _respostas_por(geral, 'questao__topicos__materia')
    geral_topico = _respostas_por(geral, 'questao__topicos')

    def linha(nome, do_usuario, geral):
        total, acertos = do_usuario
        return {
            'nome': nome,
            'total': total,
            'acerto': _percentual(acertos, total),
            'erro': _percentual(total - acertos, total),
            'acerto_geral': _percentual(geral[1], geral[0]),
        }

    materias = {}
    for pk, valores in do_usuario_topico.items():
        materias.setdefault(topicos[pk].materia_id, []).append(
            linha(topicos[pk].nome, valores, geral_topico.get(pk, (0, 0))),
        )
    nomes = dict(Materia.objects.filter(pk__in=do_usuario_materia).values_list('pk', 'nome'))
    resultado = []
    for pk, valores in do_usuario_materia.items():
        materia = linha(nomes[pk], valores, geral_materia.get(pk, (0, 0)))
        materia['topicos'] = sorted(materias.get(pk, []), key=lambda item: _ordem_alfabetica(item['nome']))
        resultado.append(materia)
    return sorted(resultado, key=lambda item: _ordem_alfabetica(item['nome']))


# Painel com o desempenho do usuário logado, calculado a partir do histórico de respostas.
# Os filtros (banca, cargo, matéria, tópico) restringem as estatísticas às questões que os atendem.
@login_required
def dashboard(request):
    filtros = FiltrosQuestao.da_requisicao(request.GET, campos=FILTROS_DASHBOARD)
    historico = HistoricoResolucao.objects.filter(usuario=request.user)
    if filtros.ativos:
        # Mesmo filtro da lista de questões, aplicado às questões respondidas. Filtrar por
        # "questão está entre as filtradas" (subconsulta) evita contar a mesma resposta duas vezes
        # quando a questão tem mais de um tópico da matéria escolhida.
        historico = historico.filter(questao__in=filtros.aplicar(Questao.objects.all()))

    # Conta o total e os acertos numa única consulta ao banco
    resumo = historico.aggregate(
        total=Count('id'),
        acertos=Count('id', filter=Q(acertou=True)),
    )
    total = resumo['total']
    acertos = resumo['acertos']

    context = {
        'total': total,
        'acertos': acertos,
        'erros': total - acertos,
        'percentual': _percentual(acertos, total),
        # Acerto e erro por matéria e, dentro dela, por tópico (com o acerto de todos os usuários)
        'desempenho_materias': _desempenho_por_materia(historico, filtros) if total else [],
        # Subcabeçalho (base.html): questões cadastradas que atendem aos filtros (não só as respondidas)
        'total_questoes': filtros.aplicar(Questao.objects.all()).count(),
        # Simulados do usuário com o progresso de cada um. Não dependem dos filtros do painel.
        # distinct=True: os Count juntos multiplicariam as linhas do JOIN. order_by explícito: o Count
        # gera GROUP BY, que ignora o Meta.ordering (os mais recentes precisam vir primeiro).
        'simulados': request.user.simulados.annotate(
            qtd_questoes=Count('questoes', distinct=True),
            qtd_respondidas=Count('resolucoes', distinct=True),
            qtd_acertos=Count('resolucoes', filter=Q(resolucoes__acertou=True), distinct=True),
        ).order_by(*Simulado._meta.ordering),
        **filtros.contexto(campos=FILTROS_DASHBOARD),
    }
    return render(request, 'usuarios/dashboard.html', context)
