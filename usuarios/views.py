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
from questoes.models import HistoricoResolucao
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


# Link do e-mail: confere o token, ativa a conta, faz o login e leva para as questões
def ativar_conta(request, uidb64, token):
    try:
        usuario = Usuario.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist):
        usuario = None

    # check_token falha se o link foi adulterado, expirou ou já foi usado (a conta já está ativa)
    if usuario is None or not ativacao_token.check_token(usuario, token):
        return render(request, 'usuarios/ativacao_invalida.html')

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


# Painel com o desempenho do usuário logado, calculado a partir do histórico de respostas
@login_required
def dashboard(request):
    # Conta o total e os acertos numa única consulta ao banco
    resumo = HistoricoResolucao.objects.filter(usuario=request.user).aggregate(
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
    }
    return render(request, 'usuarios/dashboard.html', context)
