from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render, redirect
from questoes.filtros import FiltrosQuestao
from questoes.models import HistoricoResolucao, Questao, Simulado
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
        # Evita divisão por zero quando o usuário ainda não respondeu nada
        'percentual': round(acertos / total * 100, 1) if total else 0,
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
