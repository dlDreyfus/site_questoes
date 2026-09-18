from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import ComentarioForm, ImportarCSVForm
from .importacao import COLUNAS, gerar_modelo_csv, importar_csv
from .filtros import FiltrosQuestao, parse_int
from .models import COMENTARIO_TAMANHO_MAXIMO, Comentario, HistoricoResolucao, Questao, ResolucaoOficial

# Quantidade de questões exibidas por página
QUESTOES_POR_PAGINA = 10
# Quantidade máxima de erros de importação listados na tela
MAX_ERROS_EXIBIDOS = 100


def _comentarios_com_curtidas(usuario):
    # Comentários com o autor, o total de curtidas e se o usuário logado já curtiu (tudo na mesma consulta).
    # order_by explícito: o Count gera GROUP BY, que ignora o Meta.ordering (a conversa sairia fora de ordem).
    curtidas_do_usuario = Comentario.curtidas.through.objects.filter(comentario=OuterRef('pk'), usuario=usuario)
    return (
        Comentario.objects.select_related('usuario')
        .annotate(total_curtidas=Count('curtidas'), curtido=Exists(curtidas_do_usuario))
        .order_by(*Comentario._meta.ordering)
    )


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

    context = {
        'pagina': pagina,
        'questoes': pagina.object_list,
        # 5. Opções dos dropdowns, valores selecionados e quantos filtros estão ativos
        **filtros.contexto(),
        # Questão cujo fórum acabou de receber um comentário: a seção dela já abre expandida
        'comentarios_abertos': request.session.pop('comentarios_abertos', None),
        # Questão que o usuário acabou de responder e a resolução dela (se houver)
        'questao_respondida': questao_respondida,
        'resolucao_exibida': resolucao_exibida,
        'comentario_tamanho_maximo': COMENTARIO_TAMANHO_MAXIMO,
    }

    return render(request, 'questoes/lista_questoes.html', context)


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

    context = {
        'form': form,
        'colunas': COLUNAS,
        # Muitos erros (ex: planilha inteira no formato errado) poluem a tela: mostra os primeiros
        'erros': erros[:MAX_ERROS_EXIBIDOS],
        'total_erros': len(erros),
        'erros_ocultos': max(len(erros) - MAX_ERROS_EXIBIDOS, 0),
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
