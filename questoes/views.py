from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_http_methods, require_POST
from .forms import ComentarioForm, ImportarCSVForm, SimuladoForm
from .importacao import COLUNAS, gerar_modelo_csv, importar_csv
from .filtros import CAMPOS_SIMULADO, FiltrosQuestao, parse_int
from .models import (
    COMENTARIO_TAMANHO_MAXIMO, Comentario, HistoricoResolucao, Questao, ResolucaoOficial, Simulado,
)

# Quantidade de questões exibidas por página
QUESTOES_POR_PAGINA = 10
# Quantidade máxima de erros de importação listados na tela
MAX_ERROS_EXIBIDOS = 100
# Quantidade de questões por página na tabela de curtidas da tela de importação
QUESTOES_POR_PAGINA_TABELA = 50
# Grupo dos usuários "admin" (o mesmo que recebe a permissão de importar, ver migração 0004)
GRUPO_ADMINISTRADOR = 'Administrador'


def pode_gerenciar_questoes(usuario):
    # Editar e apagar questões é restrito ao superusuário e ao grupo "Administrador".
    # Não basta ter a permissão de importar: ela pode ser dada avulsa a qualquer usuário.
    return usuario.is_superuser or usuario.groups.filter(name=GRUPO_ADMINISTRADOR).exists()


def _comentarios_com_curtidas(usuario):
    # Comentários com o autor, o total de curtidas e se o usuário logado já curtiu (tudo na mesma consulta).
    # order_by explícito: o Count gera GROUP BY, que ignora o Meta.ordering (a conversa sairia fora de ordem).
    curtidas_do_usuario = Comentario.curtidas.through.objects.filter(comentario=OuterRef('pk'), usuario=usuario)
    return (
        Comentario.objects.select_related('usuario')
        .annotate(total_curtidas=Count('curtidas'), curtido=Exists(curtidas_do_usuario))
        .order_by(*Comentario._meta.ordering)
    )


def _contexto_das_questoes(request, questoes):
    """Prepara um queryset de Questao para exibição (páginas da lista de questões e do simulado):
    fórum, paginação e resolução oficial. Devolve o contexto que questoes/_questao_card.html espera."""
    # Fórum: total de comentários de cada questão e as conversas (comentários principais com suas
    # respostas), carregados em poucas consultas para a página inteira.
    # distinct=True: os filtros por tópico/matéria fazem JOIN e, sem ele, a contagem sairia duplicada.
    # order_by explícito: consultas com Count (GROUP BY) ignoram o Meta.ordering do model, e a
    # paginação ficaria em ordem imprevisível.
    comentarios = _comentarios_com_curtidas(request.user)
    questoes = questoes.annotate(total_comentarios=Count('comentarios', distinct=True)).order_by(
        *Questao._meta.ordering
    ).prefetch_related(
        Prefetch(
            'comentarios',
            queryset=comentarios.filter(resposta_a__isnull=True).prefetch_related(
                Prefetch('respostas', queryset=comentarios),
            ),
            to_attr='comentarios_principais',
        )
    )

    # 4. Paginação: get_page trata sozinho números de página inválidos ou fora do intervalo
    pagina = Paginator(questoes, QUESTOES_POR_PAGINA).get_page(request.GET.get('page'))

    # Resolução oficial: só a da questão que o usuário acabou de responder é exibida (antes de
    # responder, ela entregaria o gabarito). Vem com o total de curtidas e se o usuário já curtiu.
    questao_respondida = request.session.pop('questao_respondida', None)
    resolucao_exibida = None
    if questao_respondida is not None:
        def voto_do_usuario(campo):
            return Exists(getattr(ResolucaoOficial, campo).through.objects.filter(
                resolucaooficial=OuterRef('pk'), usuario=request.user,
            ))

        # distinct=True: com dois Count na mesma consulta, os JOINs multiplicariam as contagens
        resolucao_exibida = (
            ResolucaoOficial.objects.filter(questao_id=questao_respondida)
            .annotate(
                total_curtidas=Count('curtidas', distinct=True), curtido=voto_do_usuario('curtidas'),
                total_descurtidas=Count('descurtidas', distinct=True), descurtido=voto_do_usuario('descurtidas'),
            )
            .first()
        )

    return {
        'pagina': pagina,
        'questoes': pagina.object_list,
        # Subcabeçalho (base.html): total de questões da lista, contado pelo paginador
        'total_questoes': pagina.paginator.count,
        # Questão cujo fórum acabou de receber um comentário: a seção dela já abre expandida
        'comentarios_abertos': request.session.pop('comentarios_abertos', None),
        # Questão que o usuário acabou de responder e a resolução dela (se houver)
        'questao_respondida': questao_respondida,
        'resolucao_exibida': resolucao_exibida,
        'comentario_tamanho_maximo': COMENTARIO_TAMANHO_MAXIMO,
    }


# Só usuários logados acessam as questões; os demais são levados ao LOGIN_URL (usuarios:login)
@login_required
def lista_questoes(request):
    # 1. Pega a QuerySet base (ainda não bateu no banco, é preguiçosa/lazy)
    # A ordem (ano mais recente primeiro) vem do Meta.ordering de Questao
    questoes = Questao.objects.select_related('banca', 'orgao', 'cargo').prefetch_related('alternativas')

    # 2 e 3. Lê os filtros da URL (ex: ?banca=1&orgao=2&cargo=3&materia=4&topico=5&ano=2024) e os aplica
    # (a mesma lógica é usada pelo painel "Meu Desempenho"; ver questoes/filtros.py)
    filtros = FiltrosQuestao.da_requisicao(request.GET)
    questoes = filtros.aplicar(questoes)

    # Botão "Novo simulado": abre a tela de criação já com os filtros que o usuário escolheu na lista
    # (só os válidos, sem a página). Sem filtros, o endereço fica limpo, sem "?" sobrando.
    parametros = urlencode(filtros.parametros())
    url_novo_simulado = reverse('questoes:novo_simulado') + (f'?{parametros}' if parametros else '')

    context = {
        # 4 e 5. Fórum, paginação e resolução exibida (compartilhados com o simulado)
        **_contexto_das_questoes(request, questoes),
        # Opções dos dropdowns, valores selecionados e quantos filtros estão ativos
        **filtros.contexto(),
        'url_novo_simulado': url_novo_simulado,
    }

    return render(request, 'questoes/lista_questoes.html', context)


# --- Simulados: conjunto fixo de questões escolhido a partir dos filtros ---------------------------

# Tamanho máximo do nome do simulado (o mesmo do campo no banco)
NOME_SIMULADO_MAXIMO = Simulado._meta.get_field('nome').max_length


@login_required
def novo_simulado(request):
    """Tela de criação: os filtros (em cascata, mais a situação) e o botão que cria o simulado."""
    filtros = FiltrosQuestao.da_requisicao(request.GET, campos=CAMPOS_SIMULADO, usuario=request.user)
    context = {
        # Subcabeçalho (base.html): quantas questões o simulado teria com os filtros escolhidos
        'total_questoes': filtros.aplicar(Questao.objects.all()).count(),
        # Nesta tela os filtros são o assunto principal: o painel não começa recolhido no celular
        'filtros_abertos': True,
        # Filtros escolhidos, reenviados junto com o formulário que cria o simulado
        'filtros_parametros': filtros.parametros(CAMPOS_SIMULADO),
        **filtros.contexto(campos=CAMPOS_SIMULADO),
    }
    return render(request, 'questoes/novo_simulado.html', context)


@login_required
@require_POST
def criar_simulado(request):
    # Relê os filtros no servidor (nada vem pronto do navegador) e congela as questões que os atendem
    filtros = FiltrosQuestao.da_requisicao(request.POST, campos=CAMPOS_SIMULADO, usuario=request.user)
    ids = list(filtros.aplicar(Questao.objects.order_by()).values_list('pk', flat=True))

    if not ids:
        messages.warning(request, 'Nenhuma questão atende aos filtros escolhidos. Ajuste os filtros e tente de novo.')
        parametros = urlencode(filtros.parametros(CAMPOS_SIMULADO))
        return redirect(f"{reverse('questoes:novo_simulado')}?{parametros}")

    nome = request.POST.get('nome', '').strip()[:NOME_SIMULADO_MAXIMO]
    nome = nome or f'Simulado de {timezone.localtime():%d/%m/%Y %H:%M}'
    with transaction.atomic():
        simulado = Simulado.objects.create(usuario=request.user, nome=nome, descricao=filtros.descricao())
        simulado.questoes.set(ids)
    return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)


@login_required
def simulado_detalhe(request, simulado_id):
    # Só o dono acessa o simulado (de outro usuário, a resposta é 404, como se ele não existisse)
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)

    # A resposta do usuário a cada questão DESTE simulado: define se ela aparece para responder ou já respondida
    respostas = simulado.resolucoes.filter(questao=OuterRef('pk'))
    questoes = simulado.questoes.select_related('banca', 'orgao', 'cargo').prefetch_related('alternativas').annotate(
        resultado=Subquery(respostas.values('acertou')[:1]),
        alternativa_marcada=Subquery(respostas.values('alternativa_escolhida_id')[:1]),
    )
    contexto = _contexto_das_questoes(request, questoes)

    resumo = simulado.resolucoes.aggregate(respondidas=Count('id'), acertos=Count('id', filter=Q(acertou=True)))
    total = contexto['pagina'].paginator.count
    context = {
        **contexto,
        'simulado': simulado,
        'respondidas': resumo['respondidas'],
        'acertos': resumo['acertos'],
        'erros': resumo['respondidas'] - resumo['acertos'],
        # Percentual sobre o que já foi respondido (evita divisão por zero no simulado recém-criado)
        'percentual': round(resumo['acertos'] / resumo['respondidas'] * 100, 1) if resumo['respondidas'] else 0,
        'concluido': total > 0 and resumo['respondidas'] >= total,
        # Subcabeçalho (base.html): "N questões cadastradas neste simulado"
        'subcabecalho_sufixo': 'neste simulado',
    }
    return render(request, 'questoes/simulado_detalhe.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def editar_simulado(request, simulado_id):
    """Renomeia o simulado. As questões e as respostas dadas nele não mudam."""
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)
    # O formulário altera o objeto ao validar: guarda o nome atual para o título da página não mostrar um nome inválido
    nome_atual = simulado.nome
    form = SimuladoForm(request.POST or None, instance=simulado)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Nome do simulado atualizado.')
        return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)
    return render(request, 'questoes/editar_simulado.html', {'form': form, 'simulado': simulado, 'nome_atual': nome_atual})


@login_required
@require_http_methods(['GET', 'POST'])
def apagar_simulado(request, simulado_id):
    """GET pede a confirmação (funciona sem JavaScript); o POST apaga de fato."""
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)
    if request.method == 'POST':
        nome = simulado.nome
        # As respostas dadas no simulado continuam no histórico do usuário (só perdem o vínculo com ele)
        simulado.delete()
        messages.success(request, f'Simulado "{nome}" apagado.')
        return redirect('usuarios:dashboard')
    return render(request, 'questoes/apagar_simulado.html', {
        'simulado': simulado,
        'respondidas': simulado.resolucoes.count(),
    })


# Publica um comentário (ou uma resposta) no fórum da questão
@login_required
@require_POST
def comentar_questao(request, questao_id):
    questao = get_object_or_404(Questao, pk=questao_id)
    form = ComentarioForm(request.POST)
    ancora = f'comentarios-{questao.id}'

    # Resposta: o comentário respondido precisa ser DESTA questão. Se for uma resposta a outra
    # resposta, a nova entra na mesma conversa (um só nível de aninhamento).
    resposta_a = None
    resposta_a_id = parse_int(request.POST.get('resposta_a'))
    if resposta_a_id is not None:
        resposta_a = questao.comentarios.filter(pk=resposta_a_id).first()
        if resposta_a is None:
            form.add_error(None, 'O comentário que você tentou responder não existe mais.')
        elif resposta_a.resposta_a_id:
            resposta_a = resposta_a.resposta_a

    if form.is_valid():
        comentario = form.save(commit=False)
        comentario.questao = questao
        comentario.usuario = request.user
        comentario.resposta_a = resposta_a
        comentario.save()
        ancora = f'comentario-{comentario.id}'
    else:
        # Mesmo esquema das respostas às questões: extra_tags leva a mensagem para o card certo
        erros = ' '.join(erro for lista in form.errors.values() for erro in lista)
        messages.warning(request, f'Comentário não publicado: {erros}', extra_tags=str(questao.id))

    # Ao voltar para a lista, o fórum desta questão já aparece aberto
    request.session['comentarios_abertos'] = questao.id
    destino = request.POST.get('next')
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = reverse('questoes:lista_questoes')
    return redirect(f'{destino}#{ancora}')


def _alternar_curtida(request, objeto, ancora, manter_aberto, campo='curtidas', oposto=None):
    # Alterna o voto do usuário: clicar marca; clicar de novo desmarca.
    # campo = 'curtidas' (👍) ou 'descurtidas' (👎, só na resolução). oposto = o outro campo, se houver:
    # marcar um tira o usuário do outro (ninguém curte e descurte a mesma resolução ao mesmo tempo).
    # Com JavaScript (static/js/forum.js) a resposta é JSON e a página não recarrega; sem JavaScript,
    # o formulário é enviado normalmente e a página volta para o item.
    # manter_aberto = (chave da sessão, id da questão): o que precisa continuar visível após recarregar.
    votos = getattr(objeto, campo)
    if votos.filter(pk=request.user.pk).exists():
        votos.remove(request.user)
    else:
        votos.add(request.user)
        if oposto:
            getattr(objeto, oposto).remove(request.user)

    if request.headers.get('Accept', '').startswith('application/json'):
        # Devolve o estado de todos os votos do objeto, para o JavaScript atualizar os dois botões
        estado = {}
        for nome, chave in (('curtidas', 'curtido'), ('descurtidas', 'descurtido')):
            if hasattr(objeto, nome):
                relacao = getattr(objeto, nome)
                estado[chave] = relacao.filter(pk=request.user.pk).exists()
                estado[f'total_{nome}'] = relacao.count()
        return JsonResponse(estado)

    chave, questao_id = manter_aberto
    request.session[chave] = questao_id
    destino = request.POST.get('next')
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = reverse('questoes:lista_questoes')
    return redirect(f'{destino}#{ancora}')


@login_required
@require_POST
def curtir_comentario(request, comentario_id):
    comentario = get_object_or_404(Comentario, pk=comentario_id)
    # Sem JavaScript a página recarrega: o fórum desta questão volta aberto
    return _alternar_curtida(
        request, comentario, f'comentario-{comentario.id}', ('comentarios_abertos', comentario.questao_id),
    )


@login_required
@require_POST
def curtir_resolucao(request, resolucao_id):
    return _votar_resolucao(request, resolucao_id, campo='curtidas', oposto='descurtidas')


@login_required
@require_POST
def descurtir_resolucao(request, resolucao_id):
    return _votar_resolucao(request, resolucao_id, campo='descurtidas', oposto='curtidas')


def _votar_resolucao(request, resolucao_id, campo, oposto):
    resolucao = get_object_or_404(ResolucaoOficial, pk=resolucao_id)
    # Sem JavaScript a página recarrega: a resolução desta questão continua visível
    return _alternar_curtida(
        request, resolucao, f'resolucao-{resolucao.id}', ('questao_respondida', resolucao.questao_id),
        campo=campo, oposto=oposto,
    )


# Recebe a alternativa marcada no formulário, grava a tentativa no histórico e informa se o usuário acertou
@login_required
@require_POST
def responder_questao(request, questao_id):
    questao = get_object_or_404(Questao, pk=questao_id)

    # A mensagem leva o id da questão em extra_tags para aparecer dentro do card certo no template
    tag = str(questao.id)
    alternativa_id = parse_int(request.POST.get('alternativa'))
    # Filtra pela questão para impedir que uma alternativa de outra questão seja enviada
    alternativa = questao.alternativas.filter(pk=alternativa_id).first() if alternativa_id else None

    # Resposta dada dentro de um simulado: só vale se o simulado for do usuário e tiver esta questão
    # (um id de outro usuário, ou de outra questão, é ignorado e a resposta segue como avulsa)
    simulado = None
    simulado_id = parse_int(request.POST.get('simulado'))
    if simulado_id is not None:
        simulado = request.user.simulados.filter(pk=simulado_id, questoes=questao).first()

    if alternativa is None:
        messages.warning(request, 'Você precisa selecionar uma alternativa!', extra_tags=tag)
    elif simulado is not None and simulado.resolucoes.filter(questao=questao).exists():
        messages.warning(request, 'Você já respondeu esta questão neste simulado.', extra_tags=tag)
    else:
        # Salva a tentativa no histórico do usuário
        try:
            # atomic: se a constraint do banco recusar (duplo clique, duas abas), a transação não fica quebrada
            with transaction.atomic():
                HistoricoResolucao.objects.create(
                    usuario=request.user,
                    questao=questao,
                    alternativa_escolhida=alternativa,
                    acertou=alternativa.is_correta,
                    simulado=simulado,
                )
        except IntegrityError:
            messages.warning(request, 'Você já respondeu esta questão neste simulado.', extra_tags=tag)
        else:
            # Ao voltar para a lista, esta questão exibe a resolução oficial (se houver)
            request.session['questao_respondida'] = questao.id
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


# Página de upload da planilha .csv de importação (só superusuários e o grupo "Administrador").
# raise_exception=True: usuário logado sem a permissão recebe 403 (Acesso negado), em vez de
# ser mandado para o login.
@login_required
@permission_required('questoes.importar_questoes', raise_exception=True)
def importar_questoes(request):
    erros = []
    if request.method == 'POST':
        # request.FILES traz o arquivo enviado (o form do template precisa de enctype multipart)
        form = ImportarCSVForm(request.POST, request.FILES)
        if form.is_valid():
            arquivo = form.cleaned_data['arquivo']
            # Tudo ou nada: se houver qualquer erro, nenhum registro é gravado (ver questoes/importacao.py)
            resultado = importar_csv(arquivo)
            if resultado.sucesso:
                resumo = ', '.join(f'{quantidade} {tabela.lower()}' for tabela, quantidade in resultado.criados.items()
                                   if quantidade)
                messages.success(request, f'Planilha "{arquivo.name}" importada com sucesso. Criados: {resumo}.')
                return redirect('questoes:importar_questoes')
            erros = resultado.erros
    else:
        form = ImportarCSVForm()

    # Tabela de questões com os votos da resolução oficial. Ordem: mais descurtidas, depois mais
    # curtidas, depois o código em ordem alfabética (questões sem código por último; o id desempata).
    # distinct=True: com dois Count na mesma consulta, os JOINs multiplicariam as contagens.
    # Questão sem resolução oficial não tem votos: os dois totais saem 0 (LEFT JOIN).
    questoes = Questao.objects.annotate(
        total_curtidas=Count('resolucao__curtidas', distinct=True),
        total_descurtidas=Count('resolucao__descurtidas', distinct=True),
    ).order_by('-total_descurtidas', '-total_curtidas', F('codigo').asc(nulls_last=True), 'id')
    pagina = Paginator(questoes, QUESTOES_POR_PAGINA_TABELA).get_page(request.GET.get('page'))

    context = {
        'form': form,
        'colunas': COLUNAS,
        # Muitos erros (ex: planilha inteira no formato errado) poluem a tela: mostra os primeiros
        'erros': erros[:MAX_ERROS_EXIBIDOS],
        'total_erros': len(erros),
        'erros_ocultos': max(len(erros) - MAX_ERROS_EXIBIDOS, 0),
        'pagina': pagina,
        # Colunas de ações da tabela: só para o superusuário e o grupo "Administrador"
        'pode_gerenciar': pode_gerenciar_questoes(request.user),
        # O admin do Django exige is_staff além da permissão; sem ela o link só levaria ao login do admin
        'pode_editar_no_admin': request.user.is_staff and request.user.has_perm('questoes.change_questao'),
    }
    return render(request, 'questoes/importar_questoes.html', context)


# Download do modelo de planilha (cabeçalho + uma questão ME e uma CE de exemplo)
@login_required
@permission_required('questoes.importar_questoes', raise_exception=True)
def modelo_planilha(request):
    resposta = HttpResponse(gerar_modelo_csv(), content_type='text/csv; charset=utf-8')
    # attachment: o navegador baixa o arquivo em vez de abrir na tela
    resposta['Content-Disposition'] = 'attachment; filename="modelo_importacao_questoes.csv"'
    return resposta


# Apaga uma questão (e, em cascata, alternativas, resolução, histórico de respostas e comentários).
# GET pede a confirmação (funciona sem JavaScript); o POST apaga de fato. Só superusuário e "Administrador".
@login_required
@require_http_methods(['GET', 'POST'])
def apagar_questao(request, questao_id):
    if not pode_gerenciar_questoes(request.user):
        raise PermissionDenied
    questao = get_object_or_404(Questao, pk=questao_id)
    rotulo = questao.codigo or f'Questão {questao.pk}'
    if request.method == 'POST':
        questao.delete()
        messages.success(request, f'Questão "{rotulo}" apagada.')
        return redirect('questoes:importar_questoes')
    return render(request, 'questoes/apagar_questao.html', {
        'questao': questao,
        'rotulo': rotulo,
        # O que vai junto com a questão, para o admin decidir com todos os fatos
        'total_alternativas': questao.alternativas.count(),
        'total_respostas': questao.historico.count(),
        'total_comentarios': questao.comentarios.count(),
    })
