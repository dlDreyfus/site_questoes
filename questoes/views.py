import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_http_methods, require_POST
from .forms import ComentarioForm, ImportarCSVForm, SimuladoForm
from .importacao import COLUNAS, atualizar_csv, exportar_csv, importar_csv
from .filtros import CAMPOS_SIMULADO, FiltrosQuestao, parse_int
from .models import (
    COMENTARIO_TAMANHO_MAXIMO, Comentario, HistoricoResolucao, Questao, ResolucaoOficial, Simulado,
)

# Quantidade de questões exibidas por página (lista e simulado mostram uma questão por vez)
QUESTOES_POR_PAGINA = 1
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


# --- Ordem aleatória ---------------------------------------------------------------------------------
# A ordem aleatória é definida por uma semente (?aleatorio=<número> na URL, ou Simulado.semente): a mesma
# semente embaralha as mesmas questões sempre do mesmo jeito, então "Próxima" segue a ordem sorteada.

def _nova_semente():
    return random.randint(1, 2**31 - 1)


def _semente(params):
    """Semente da ordem aleatória (parâmetro 'aleatorio'); ausente ou inválida = ordem normal."""
    semente = parse_int(params.get('aleatorio'))
    return semente if semente is not None and 0 < semente < 2**31 else None


def _url(caminho, parametros):
    """Caminho com os parâmetros ({campo: [valores]}); sem parâmetros, o endereço fica limpo, sem "?"."""
    consulta = urlencode(parametros, doseq=True)
    return caminho + (f'?{consulta}' if consulta else '')


def _contexto_aleatorio(request, parametros, semente):
    """Botão "Aleatório" de questoes/_filtros.html: liga a ordem aleatória (com uma semente nova) ou, se
    já ligada, volta à ordem normal. Mantém os filtros e recomeça da primeira questão (sem a página)."""
    parametros_do_botao = parametros if semente else {**parametros, 'aleatorio': [_nova_semente()]}
    return {'aleatorio': semente, 'url_aleatorio': _url(request.path, parametros_do_botao)}


def _com_aleatorio(parametros, semente):
    """Os parâmetros dos filtros mais a semente da ordem aleatória, se ligada."""
    return {**parametros, 'aleatorio': [semente]} if semente else parametros


def _comentarios_com_curtidas(usuario):
    # Comentários com o autor, o total de curtidas e se o usuário logado já curtiu (tudo na mesma consulta).
    # order_by explícito: o Count gera GROUP BY, que ignora o Meta.ordering (a conversa sairia fora de ordem).
    curtidas_do_usuario = Comentario.curtidas.through.objects.filter(comentario=OuterRef('pk'), usuario=usuario)
    return (
        Comentario.objects.select_related('usuario')
        .annotate(total_curtidas=Count('curtidas'), curtido=Exists(curtidas_do_usuario))
        .order_by(*Comentario._meta.ordering)
    )


def _acertos_da_questao(questao_id):
    """Quantas pessoas já resolveram a questão e qual percentual delas acertou. Cada usuário conta uma
    vez, pela PRIMEIRA resposta: as seguintes vêm depois de ver o gabarito e inflariam o acerto."""
    primeira_resposta = HistoricoResolucao.objects.filter(
        questao_id=questao_id, usuario=OuterRef('usuario'),
    ).order_by('data_resposta', 'pk').values('pk')[:1]
    resumo = HistoricoResolucao.objects.filter(
        questao_id=questao_id, pk=Subquery(primeira_resposta),
    ).aggregate(pessoas=Count('pk'), acertos=Count('pk', filter=Q(acertou=True)))
    pessoas = resumo['pessoas']
    return {
        'pessoas': pessoas,
        'percentual': round(resumo['acertos'] / pessoas * 100) if pessoas else 0,
    }


def _contexto_das_questoes(request, questoes, semente=None):
    """Prepara um queryset de Questao para exibição (páginas da lista de questões e do simulado):
    fórum, paginação (na ordem normal ou, com 'semente', embaralhada) e resolução oficial. Devolve o
    contexto que questoes/_questao_card.html espera."""
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
    # numero_questao: o número exibido em "Questão X de N" (vazio = o número da página)
    numero_questao = None
    if semente is None:
        pagina = Paginator(questoes, QUESTOES_POR_PAGINA).get_page(request.GET.get('page'))
    else:
        # Ordem aleatória: embaralha os ids (partindo de uma ordem fixa, para a semente sempre dar o
        # mesmo resultado), pagina os ids e só então busca as questões da página
        ids = list(questoes.order_by('pk').values_list('pk', flat=True))
        random.Random(semente).shuffle(ids)
        pagina = Paginator(ids, QUESTOES_POR_PAGINA).get_page(request.GET.get('page'))
        da_pagina = questoes.in_bulk(pagina.object_list)
        pagina.object_list = [da_pagina[pk] for pk in pagina.object_list if pk in da_pagina]
        # "Questão X de N" mostra o número da questão na ordem normal (e não a posição no sorteio):
        # assim "Próxima" salta, por exemplo, da questão 11 para a 15
        if pagina.object_list:
            ordem_normal = list(questoes.values_list('pk', flat=True))
            numero_questao = ordem_normal.index(pagina.object_list[0].pk) + 1

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
        if resolucao_exibida is not None:
            # Ao lado dos votos: percentual de acerto de todos os usuários que já resolveram a questão
            resolucao_exibida.acertos_da_questao = _acertos_da_questao(questao_respondida)
            # Abaixo do Curtir/Descurtir: botões Fácil/Difícil e o percentual de cada classificação
            resolucao_exibida.dificuldade = _dificuldade_da_questao(resolucao_exibida.questao, request.user)

    return {
        'pagina': pagina,
        'numero_questao': numero_questao,
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

    # 2 e 3. Lê os filtros da URL (ex: ?busca=licitação&banca=1&banca=2&materia=4&ano=2024) e os aplica
    # (a mesma lógica é usada pelo painel "Meu Desempenho"; ver questoes/filtros.py)
    filtros = FiltrosQuestao.da_requisicao(request.GET)
    questoes = filtros.aplicar(questoes)

    # Ordem aleatória (botão "Aleatório" ao lado do "Limpar"); vale para os filtros aplicados
    semente = _semente(request.GET)

    context = {
        # 4 e 5. Fórum, paginação e resolução exibida (compartilhados com o simulado)
        **_contexto_das_questoes(request, questoes, semente),
        # Opções dos dropdowns, valores selecionados e quantos filtros estão ativos
        **filtros.contexto(),
        **_contexto_aleatorio(request, filtros.parametros(), semente),
        # Botão "Novo simulado": abre a tela de criação já com os filtros que o usuário escolheu na lista
        # (só os válidos, sem a página) e a ordem aleatória, se ligada
        'url_novo_simulado': _url(reverse('questoes:novo_simulado'), _com_aleatorio(filtros.parametros(), semente)),
    }

    return render(request, 'questoes/lista_questoes.html', context)


# --- Simulados: conjunto fixo de questões escolhido a partir dos filtros ---------------------------

# Tamanho máximo do nome do simulado (o mesmo do campo no banco)
NOME_SIMULADO_MAXIMO = Simulado._meta.get_field('nome').max_length


@login_required
def novo_simulado(request):
    """Tela de criação: os filtros (em cascata, mais a situação) e o botão que cria o simulado."""
    filtros = FiltrosQuestao.da_requisicao(request.GET, campos=CAMPOS_SIMULADO, usuario=request.user)
    # Ordem aleatória: o simulado é criado já embaralhado (a semente vai junto no formulário)
    semente = _semente(request.GET)
    context = {
        # Subcabeçalho (base.html): quantas questões o simulado teria com os filtros escolhidos
        'total_questoes': filtros.aplicar(Questao.objects.all()).count(),
        # Nesta tela os filtros são o assunto principal: o painel não começa recolhido no celular
        'filtros_abertos': True,
        # Aqui não há paginação: o botão "Aleatório" fica junto dos filtros (ver questoes/_filtros.html)
        'aleatorio_nos_filtros': True,
        # Filtros escolhidos (e a ordem aleatória), reenviados junto com o formulário que cria o simulado
        'filtros_parametros': _com_aleatorio(filtros.parametros(CAMPOS_SIMULADO), semente),
        **filtros.contexto(campos=CAMPOS_SIMULADO),
        **_contexto_aleatorio(request, filtros.parametros(CAMPOS_SIMULADO), semente),
    }
    return render(request, 'questoes/novo_simulado.html', context)


@login_required
@require_POST
def criar_simulado(request):
    # Relê os filtros no servidor (nada vem pronto do navegador) e congela as questões que os atendem
    filtros = FiltrosQuestao.da_requisicao(request.POST, campos=CAMPOS_SIMULADO, usuario=request.user)
    ids = list(filtros.aplicar(Questao.objects.order_by()).values_list('pk', flat=True))
    semente = _semente(request.POST)

    if not ids:
        messages.warning(request, 'Nenhuma questão atende aos filtros escolhidos. Ajuste os filtros e tente de novo.')
        parametros = _com_aleatorio(filtros.parametros(CAMPOS_SIMULADO), semente)
        return redirect(_url(reverse('questoes:novo_simulado'), parametros))

    nome = request.POST.get('nome', '').strip()[:NOME_SIMULADO_MAXIMO]
    nome = nome or f'Simulado de {timezone.localtime():%d/%m/%Y %H:%M}'
    with transaction.atomic():
        simulado = Simulado.objects.create(
            usuario=request.user, nome=nome, descricao=filtros.descricao(), semente=semente,
            publico=bool(request.POST.get('publico')),
            # Gravados para o "Atualizar questões" acrescentar depois as questões novas que os atendem
            filtros=filtros.parametros(CAMPOS_SIMULADO),
        )
        simulado.questoes.set(ids)
    return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)


@login_required
def simulado_detalhe(request, simulado_id):
    # Só o dono acessa o simulado (de outro usuário, a resposta é 404, como se ele não existisse)
    simulado = get_object_or_404(
        Simulado.objects.select_related('origem__usuario'), pk=simulado_id, usuario=request.user,
    )

    # A resposta do usuário a cada questão DESTE simulado: define se ela aparece para responder ou já respondida
    respostas = simulado.resolucoes.filter(questao=OuterRef('pk'))
    questoes = simulado.questoes.select_related('banca', 'orgao', 'cargo').prefetch_related('alternativas').annotate(
        resultado=Subquery(respostas.values('acertou')[:1]),
        alternativa_marcada=Subquery(respostas.values('alternativa_escolhida_id')[:1]),
    )
    contexto = _contexto_das_questoes(request, questoes, simulado.semente)

    resumo =simulado.resolucoes.aggregate(respondidas=Count('id'), acertos=Count('id', filter=Q(acertou=True)))
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
@require_POST
def alternar_ordem_simulado(request, simulado_id):
    """Botão "Aleatório" do simulado: embaralha as questões (com uma semente nova) ou, se já estão
    embaralhadas, volta à ordem normal. As respostas dadas no simulado não mudam."""
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)
    simulado.semente = None if simulado.semente else _nova_semente()
    simulado.save(update_fields=['semente'])
    if simulado.semente:
        messages.success(request, 'Questões em ordem aleatória.')
    else:
        messages.success(request, 'Questões de volta à ordem normal.')
    # Recomeça da primeira questão da nova ordem
    return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)


@login_required
@require_POST
def atualizar_simulado(request, simulado_id):
    """Botão "Atualizar questões": aplica de novo os filtros gravados na criação e acrescenta as questões
    cadastradas depois que os atendem. Nenhuma questão sai do simulado e as respostas dadas continuam."""
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)
    if simulado.filtros is None:
        messages.warning(
            request, 'Este simulado foi criado antes de os filtros serem gravados e não pode ser atualizado. '
                     'Crie um novo simulado com os mesmos filtros para incluir as questões novas.',
        )
        return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)

    # A situação ("que errei", "ainda não resolvi") é avaliada agora, com o histórico atual do usuário
    filtros = FiltrosQuestao.da_requisicao(simulado.filtros, campos=CAMPOS_SIMULADO, usuario=request.user)
    novas = list(
        filtros.aplicar(Questao.objects.order_by()).exclude(simulados=simulado).values_list('pk', flat=True)
    )
    if novas:
        simulado.questoes.add(*novas)
        texto = '1 questão nova foi incluída' if len(novas) == 1 else f'{len(novas)} questões novas foram incluídas'
        messages.success(request, f'{texto} no simulado.')
    else:
        messages.info(request, 'Nenhuma questão nova atende aos filtros deste simulado.')
    return redirect('questoes:simulado_detalhe', simulado_id=simulado.pk)


@login_required
@require_http_methods(['GET', 'POST'])
def editar_simulado(request, simulado_id):
    """Renomeia o simulado e o torna público ou privado. As questões e as respostas dadas nele não mudam."""
    simulado = get_object_or_404(Simulado, pk=simulado_id, usuario=request.user)
    # O formulário altera o objeto ao validar: guarda o nome atual para o título da página não mostrar um nome inválido
    nome_atual = simulado.nome
    form = SimuladoForm(request.POST or None, instance=simulado)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Simulado atualizado.')
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


# Quantidade de simulados por página em "Simulados públicos"
SIMULADOS_POR_PAGINA = 20


@login_required
def simulados_publicos(request):
    """Simulados que os usuários marcaram como públicos (de todos, inclusive os do próprio usuário)."""
    # A cópia que o usuário já fez de cada simulado (se fez): o botão vira "Continuar" e leva até ela
    copia_do_usuario = Simulado.objects.filter(origem=OuterRef('pk'), usuario=request.user).order_by('-pk')
    # distinct=True: os dois Count juntos multiplicariam as linhas do JOIN. order_by explícito: o Count
    # gera GROUP BY, que ignora o Meta.ordering (os mais recentes precisam vir primeiro).
    simulados = (
        Simulado.objects.filter(publico=True).select_related('usuario')
        .annotate(
            qtd_questoes=Count('questoes', distinct=True),
            qtd_copias=Count('copias', distinct=True),
            copia_id=Subquery(copia_do_usuario.values('pk')[:1]),
        )
        .order_by(*Simulado._meta.ordering)
    )
    pagina = Paginator(simulados, SIMULADOS_POR_PAGINA).get_page(request.GET.get('page'))
    return render(request, 'questoes/simulados_publicos.html', {'pagina': pagina, 'simulados': pagina.object_list})


@login_required
@require_POST
def fazer_simulado(request, simulado_id):
    """Faz um simulado público de outro usuário: cria uma cópia privada (mesmas questões e ordem) onde as
    respostas são só de quem a fez. Se o usuário já tem uma cópia, volta para ela."""
    original = get_object_or_404(Simulado, pk=simulado_id, publico=True)
    if original.usuario_id == request.user.pk:
        return redirect('questoes:simulado_detalhe', simulado_id=original.pk)

    copia = request.user.simulados.filter(origem=original).order_by('-pk').first()
    if copia is None:
        with transaction.atomic():
            copia = Simulado.objects.create(
                usuario=request.user, nome=original.nome, descricao=original.descricao,
                semente=original.semente, origem=original, filtros=original.filtros,
            )
            copia.questoes.set(original.questoes.all())
        messages.success(request, f'O simulado "{copia.nome}" foi adicionado aos seus simulados.')
    return redirect('questoes:simulado_detalhe', simulado_id=copia.pk)


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


# Votos que a resposta JSON informa ao JavaScript: (campo do model, chave do "já votou"). O total vai
# em total_<campo>. Curtir/descurtir (comentários e resolução) e fácil/difícil (questão).
VOTOS_CURTIDA = (('curtidas', 'curtido'), ('descurtidas', 'descurtido'))
VOTOS_DIFICULDADE = (('avaliacoes_facil', 'facil'), ('avaliacoes_dificil', 'dificil'))


def _alternar_curtida(request, objeto, ancora, manter_aberto, campo='curtidas', oposto=None,
                      votos=VOTOS_CURTIDA, extra=None):
    # Alterna o voto do usuário: clicar marca; clicar de novo desmarca.
    # campo = 'curtidas' (👍) ou 'descurtidas' (👎, só na resolução). oposto = o outro campo, se houver:
    # marcar um tira o usuário do outro (ninguém curte e descurte a mesma resolução ao mesmo tempo).
    # extra = função que devolve mais dados para o JSON (ex: os percentuais de fácil/difícil).
    # Com JavaScript (static/js/forum.js) a resposta é JSON e a página não recarrega; sem JavaScript,
    # o formulário é enviado normalmente e a página volta para o item.
    # manter_aberto = (chave da sessão, id da questão): o que precisa continuar visível após recarregar.
    marcados = getattr(objeto, campo)
    if marcados.filter(pk=request.user.pk).exists():
        marcados.remove(request.user)
    else:
        marcados.add(request.user)
        if oposto:
            getattr(objeto, oposto).remove(request.user)

    if request.headers.get('Accept', '').startswith('application/json'):
        # Devolve o estado de todos os votos do objeto, para o JavaScript atualizar os dois botões
        estado = {}
        for nome, chave in votos:
            if hasattr(objeto, nome):
                relacao = getattr(objeto, nome)
                estado[chave] = relacao.filter(pk=request.user.pk).exists()
                estado[f'total_{nome}'] = relacao.count()
        if extra:
            estado.update(extra())
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


@login_required
@require_POST
def avaliar_facil(request, questao_id):
    return _avaliar_dificuldade(request, questao_id, campo='avaliacoes_facil', oposto='avaliacoes_dificil')


@login_required
@require_POST
def avaliar_dificil(request, questao_id):
    return _avaliar_dificuldade(request, questao_id, campo='avaliacoes_dificil', oposto='avaliacoes_facil')


def _avaliar_dificuldade(request, questao_id, campo, oposto):
    questao = get_object_or_404(Questao, pk=questao_id)
    # Só quem já resolveu a questão a classifica (os botões só aparecem depois de responder)
    if not request.user.historico.filter(questao=questao).exists():
        raise PermissionDenied('Responda a questão antes de classificar a dificuldade.')
    # Sem JavaScript a página recarrega: a resolução desta questão (onde ficam os botões) continua visível
    return _alternar_curtida(
        request, questao, f'dificuldade-{questao.id}', ('questao_respondida', questao.id),
        campo=campo, oposto=oposto, votos=VOTOS_DIFICULDADE,
        extra=lambda: _dificuldade_da_questao(questao),
    )


def _dificuldade_da_questao(questao, usuario=None):
    """Quantas pessoas classificaram a questão e o percentual de "Fácil" e de "Difícil" entre elas.
    Com 'usuario', informa também o voto dele (para marcar o botão)."""
    faceis = questao.avaliacoes_facil.count()
    dificeis = questao.avaliacoes_dificil.count()
    total = faceis + dificeis
    # O difícil é o complemento: os dois percentuais sempre somam 100%
    percentual_facil = round(faceis / total * 100) if total else 0
    dados = {
        'total_avaliacoes': total,
        'percentual_facil': percentual_facil,
        'percentual_dificil': 100 - percentual_facil if total else 0,
    }
    if usuario is not None:
        dados.update({
            'facil': questao.avaliacoes_facil.filter(pk=usuario.pk).exists(),
            'dificil': questao.avaliacoes_dificil.filter(pk=usuario.pk).exists(),
            'total_avaliacoes_facil': faceis,
            'total_avaliacoes_dificil': dificeis,
        })
    return dados


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
    # Dois formulários na mesma página: envio de questões novas e atualização das existentes pelo código.
    # O prefixo separa os campos da atualização ("atualizacao-arquivo"), e o campo 'acao' diz qual foi enviado.
    erros = []
    operacao = None  # 'novas' ou 'atualizacao': qual envio falhou (título da caixa de erros)
    form = ImportarCSVForm()
    form_atualizacao = ImportarCSVForm(prefix='atualizacao')
    if request.method == 'POST':
        operacao = 'atualizacao' if request.POST.get('acao') == 'atualizacao' else 'novas'
        # request.FILES traz o arquivo enviado (o form do template precisa de enctype multipart)
        if operacao == 'atualizacao':
            enviado = form_atualizacao = ImportarCSVForm(request.POST, request.FILES, prefix='atualizacao')
        else:
            enviado = form = ImportarCSVForm(request.POST, request.FILES)
        if enviado.is_valid():
            arquivo = enviado.cleaned_data['arquivo']
            # Tudo ou nada: se houver qualquer erro, nenhum registro é gravado (ver questoes/importacao.py)
            resultado = atualizar_csv(arquivo) if operacao == 'atualizacao' else importar_csv(arquivo)
            if resultado.sucesso:
                resumo = ', '.join(f'{quantidade} {tabela.lower()}' for tabela, quantidade in resultado.criados.items()
                                   if quantidade)
                if operacao == 'atualizacao':
                    messages.success(request, f'Planilha "{arquivo.name}" aplicada com sucesso: {resumo}.')
                else:
                    messages.success(request, f'Planilha "{arquivo.name}" importada com sucesso. Criados: {resumo}.')
                return redirect('questoes:importar_questoes')
            erros = resultado.erros

    # Tabela de questões com os votos da resolução oficial e quantas vezes cada uma foi respondida.
    # Ordem: mais descurtidas, depois mais respondidas, depois mais curtidas, depois o código em ordem
    # alfabética (questões sem código por último; o id desempata).
    # distinct=True: com dois Count na mesma consulta, os JOINs multiplicariam as contagens.
    # Questão sem resolução oficial não tem votos: os dois totais saem 0 (LEFT JOIN).
    # Respostas (de todos os usuários, avulsas ou em simulados) numa subconsulta: um terceiro JOIN
    # multiplicaria as linhas por curtidas x descurtidas x respostas. Sem respostas, a subconsulta
    # não devolve nada e o Coalesce transforma em 0.
    respostas = (
        HistoricoResolucao.objects.filter(questao=OuterRef('pk'))
        .order_by().values('questao').annotate(total=Count('id')).values('total')
    )
    questoes = Questao.objects.annotate(
        total_curtidas=Count('resolucao__curtidas', distinct=True),
        total_descurtidas=Count('resolucao__descurtidas', distinct=True),
        total_respondidas=Coalesce(Subquery(respostas), 0),
    ).order_by(
        '-total_descurtidas', '-total_respondidas', '-total_curtidas', F('codigo').asc(nulls_last=True), 'id',
    )
    pagina = Paginator(questoes, QUESTOES_POR_PAGINA_TABELA).get_page(request.GET.get('page'))

    context = {
        'form': form,
        'form_atualizacao': form_atualizacao,
        'operacao': operacao,
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


# Botão "Baixar csv": todas as questões do banco, com as mesmas colunas da importação
@login_required
@permission_required('questoes.importar_questoes', raise_exception=True)
def exportar_questoes(request):
    resposta = HttpResponse(exportar_csv(), content_type='text/csv; charset=utf-8')
    # attachment: o navegador baixa o arquivo em vez de abrir na tela (o nome leva a data do download)
    resposta['Content-Disposition'] = f'attachment; filename="questoes_{timezone.localdate():%Y-%m-%d}.csv"'
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
