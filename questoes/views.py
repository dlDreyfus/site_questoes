from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .models import Banca, Cargo, HistoricoResolucao, Materia, Orgao, Questao, Topico

# Quantidade de questões exibidas por página
QUESTOES_POR_PAGINA = 10


def _parse_int(valor):
    # Converte o parâmetro da URL para inteiro; valores ausentes ou inválidos (ex: ?ano=abc, ?ano=²) viram None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


# Só usuários logados acessam as questões; os demais são levados ao LOGIN_URL (usuarios:login)
@login_required
def lista_questoes(request):
    # 1. Pega a QuerySet base (ainda não bateu no banco, é preguiçosa/lazy)
    # A ordem (ano mais recente primeiro) vem do Meta.ordering de Questao
    questoes = Questao.objects.select_related('banca', 'orgao', 'cargo').prefetch_related('alternativas')

    # 2. Captura e valida os parâmetros da URL (ex: ?banca=1&orgao=2&cargo=3&materia=4&topico=5&ano=2024)
    banca_id = _parse_int(request.GET.get('banca'))
    orgao_id = _parse_int(request.GET.get('orgao'))
    cargo_id = _parse_int(request.GET.get('cargo'))
    materia_id = _parse_int(request.GET.get('materia'))
    topico_id = _parse_int(request.GET.get('topico'))
    ano = _parse_int(request.GET.get('ano'))

    # Com uma matéria escolhida, o dropdown de tópicos mostra só os tópicos dela.
    # Se o tópico da URL não for dessa matéria (ex: o usuário trocou a matéria depois), ele é ignorado.
    topicos = Topico.objects.select_related('materia')
    if materia_id is not None:
        topicos = topicos.filter(materia_id=materia_id)
        if topico_id is not None and not topicos.filter(pk=topico_id).exists():
            topico_id = None

    # 3. Aplica os filtros dinamicamente usando o ORM
    if banca_id is not None:
        questoes = questoes.filter(banca_id=banca_id)
    if orgao_id is not None:
        questoes = questoes.filter(orgao_id=orgao_id)
    if cargo_id is not None:
        questoes = questoes.filter(cargo_id=cargo_id)
    if ano is not None:
        questoes = questoes.filter(ano=ano)
    if topico_id is not None:
        # O tópico já pertence à matéria escolhida (validado acima), então basta filtrar por ele
        questoes = questoes.filter(topicos=topico_id).distinct()
    elif materia_id is not None:
        # Como a relação é N:M (Muitos para Muitos) com Tópico e Tópico pertence à Matéria:
        questoes = questoes.filter(topicos__materia_id=materia_id).distinct()

    # 4. Paginação: get_page trata sozinho números de página inválidos ou fora do intervalo
    pagina = Paginator(questoes, QUESTOES_POR_PAGINA).get_page(request.GET.get('page'))

    # 5. Prepara os dados para as caixas de seleção (dropdowns)
    # Busca apenas os anos que possuem questões cadastradas, sem repetição, do mais novo pro mais velho
    anos = Questao.objects.values_list('ano', flat=True).distinct().order_by('-ano')

    context = {
        'pagina': pagina,
        'questoes': pagina.object_list,
        'bancas': Banca.objects.all(),
        'orgaos': Orgao.objects.order_by('sigla'),
        'cargos': Cargo.objects.order_by('nome'),
        'materias': Materia.objects.order_by('nome'),
        'topicos': topicos,
        'anos': anos,
        'banca_selecionada': banca_id,
        'orgao_selecionado': orgao_id,
        'cargo_selecionado': cargo_id,
        'materia_selecionada': materia_id,
        'topico_selecionado': topico_id,
        'ano_selecionado': ano,
        # Quantos filtros estão em uso: no celular, o painel de filtros já abre se houver algum
        'filtros_ativos': sum(
            valor is not None for valor in (banca_id, orgao_id, cargo_id, materia_id, topico_id, ano)
        ),
    }

    return render(request, 'questoes/lista_questoes.html', context)


# Recebe a alternativa marcada no formulário, grava a tentativa no histórico e informa se o usuário acertou
@login_required
@require_POST
def responder_questao(request, questao_id):
    questao = get_object_or_404(Questao, pk=questao_id)

    # A mensagem leva o id da questão em extra_tags para aparecer dentro do card certo no template
    tag = str(questao.id)
    alternativa_id = _parse_int(request.POST.get('alternativa'))
    # Filtra pela questão para impedir que uma alternativa de outra questão seja enviada
    alternativa = questao.alternativas.filter(pk=alternativa_id).first() if alternativa_id else None

    if alternativa is None:
        messages.warning(request, 'Você precisa selecionar uma alternativa!', extra_tags=tag)
    else:
        # Salva a tentativa no histórico do usuário
        HistoricoResolucao.objects.create(
            usuario=request.user,
            questao=questao,
            alternativa_escolhida=alternativa,
            acertou=alternativa.is_correta,
        )
        if alternativa.is_correta:
            messages.success(request, 'Resposta Correta! Excelente.', extra_tags=tag)
        else:
            correta = questao.alternativas.filter(is_correta=True).first()
            texto = f'Resposta Incorreta. A correta é: {correta.texto}' if correta else 'Resposta Incorreta.'
            messages.error(request, texto, extra_tags=tag)

    # Volta para a mesma página (mantendo filtros e página) e rola até a questão respondida
    destino = request.POST.get('next')
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = reverse('questoes:lista_questoes')
    return redirect(f'{destino}#questao-{questao.id}')
