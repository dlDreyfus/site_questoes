from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_http_methods
from questoes.filtros import FiltrosQuestao
from questoes.models import HistoricoResolucao, Questao
from .forms import CadastroUsuarioForm, ReenviarAtivacaoForm
from .models import Usuario
from .tokens import ativacao_token


def _enviar_email_ativacao(request, usuario):
    # Monta o link absoluto (http://dominio/usuarios/ativar/<uid>/<token>/) e envia o e-mail
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    caminho = reverse('usuarios:ativar_conta', kwargs={'uidb64': uid, 'token': ativacao_token.make_token(usuario)})
    contexto = {'usuario': usuario, 'link': request.build_absolute_uri(caminho)}
    assunto = render_to_string('usuarios/emails/ativacao_assunto.txt', contexto).strip()
    corpo = render_to_string('usuarios/emails/ativacao_email.txt', contexto)
    send_mail(assunto, corpo, None, [usuario.email])  # None = usa o DEFAULT_FROM_EMAIL


# Cadastro de novo usuário: cria a conta INATIVA e envia o link de ativação por e-mail
def cadastro(request):
    # Quem já está logado não precisa se cadastrar de novo
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    if request.method == 'POST':
        form = CadastroUsuarioForm(request.POST)
        if form.is_valid():
            usuario = form.save(commit=False)
            # A conta só pode ser usada depois que o dono confirmar o e-mail
            usuario.is_active = False
            usuario.save()
            _enviar_email_ativacao(request, usuario)
            return redirect('usuarios:ativacao_enviada')
    else:
        form = CadastroUsuarioForm()

    return render(request, 'usuarios/cadastro.html', {'form': form})


# Página "verifique seu e-mail", exibida após o cadastro e após o reenvio do link
def ativacao_enviada(request):
    return render(request, 'usuarios/ativacao_enviada.html')


# Link do e-mail, em dois passos:
# - GET (abrir o link): só confere o token e mostra o botão "Ativar minha conta". Abrir o link não
#   muda nada, então filtros de e-mail e antivírus que visitam links sozinhos não ativam a conta.
# - POST (clicar no botão): ativa, faz o login e leva para as questões. Por ser POST com token CSRF,
#   outro site não consegue forçar alguém a entrar numa conta que não é dele (login CSRF).
@require_http_methods(['GET', 'POST'])
def ativar_conta(request, uidb64, token):
    try:
        usuario = Usuario.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        usuario = None

    # check_token falha se o link foi adulterado, expirou ou já foi usado (a conta já está ativa)
    if usuario is None or not ativacao_token.check_token(usuario, token):
        return render(request, 'usuarios/ativacao_invalida.html')

    if request.method == 'GET':
        return render(request, 'usuarios/ativar_conta.html', {'usuario': usuario})

    usuario.is_active = True
    usuario.save(update_fields=['is_active'])
    login(request, usuario)
    messages.success(request, f'Conta ativada com sucesso. Bem-vindo(a), {usuario.username}!')
    return redirect(settings.LOGIN_REDIRECT_URL)


# Envia um novo link de ativação para quem perdeu ou deixou expirar o anterior
def reenviar_ativacao(request):
    if request.method == 'POST':
        form = ReenviarAtivacaoForm(request.POST)
        if form.is_valid():
            usuario = Usuario.objects.filter(email__iexact=form.cleaned_data['email'], is_active=False).first()
            # Só envia para conta pendente de ativação, mas a resposta é sempre a mesma,
            # para não revelar quais e-mails têm conta no site
            if usuario:
                _enviar_email_ativacao(request, usuario)
            return redirect('usuarios:ativacao_enviada')
    else:
        form = ReenviarAtivacaoForm()

    return render(request, 'usuarios/reenviar_ativacao.html', {'form': form})


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
        **filtros.contexto(campos=FILTROS_DASHBOARD),
    }
    return render(request, 'usuarios/dashboard.html', context)
