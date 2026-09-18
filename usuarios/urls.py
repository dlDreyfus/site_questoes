from django.urls import path, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views # Importamos as views deste app
from .forms import LoginForm

app_name = 'usuarios'

urlpatterns = [
    # Usamos a view nativa LoginView, mas apontamos para o nosso próprio HTML.
    # redirect_authenticated_user: quem já está logado e abre o login é levado direto ao LOGIN_REDIRECT_URL
    path(
        'login/',
        # authentication_form: LoginForm avisa quando a conta ainda não foi ativada pelo e-mail
        auth_views.LoginView.as_view(
            template_name='usuarios/login.html', authentication_form=LoginForm, redirect_authenticated_user=True,
        ),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(next_page='usuarios:login'), name='logout'),
    # Cadastro de novo usuário (link na tela de login) e ativação da conta por e-mail
    path('cadastro/', views.cadastro, name='cadastro'),
    path('ativacao/enviada/', views.ativacao_enviada, name='ativacao_enviada'),
    path('ativacao/reenviar/', views.reenviar_ativacao, name='reenviar_ativacao'),
    path('ativar/<uidb64>/<token>/', views.ativar_conta, name='ativar_conta'),

    # Recuperação de senha (views nativas do Django), em 4 passos:
    # 1. Usuário informa o e-mail e recebe um link com token de uso único
    path(
        'recuperar-senha/',
        auth_views.PasswordResetView.as_view(
            template_name='usuarios/recuperar_senha.html',
            email_template_name='usuarios/emails/recuperar_senha_email.txt',
            subject_template_name='usuarios/emails/recuperar_senha_assunto.txt',
            success_url=reverse_lazy('usuarios:recuperar_senha_enviado'),
        ),
        name='recuperar_senha',
    ),
    # 2. Aviso de que o e-mail foi enviado (a mesma mensagem aparece mesmo se o e-mail não existir,
    #    para não revelar quais e-mails têm conta no site)
    path(
        'recuperar-senha/enviado/',
        auth_views.PasswordResetDoneView.as_view(template_name='usuarios/recuperar_senha_enviado.html'),
        name='recuperar_senha_enviado',
    ),
    # 3. Link do e-mail: valida o token e pede a nova senha
    path(
        'redefinir-senha/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='usuarios/redefinir_senha.html',
            success_url=reverse_lazy('usuarios:redefinir_senha_concluido'),
        ),
        name='redefinir_senha',
    ),
    # 4. Confirmação de que a senha foi trocada
    path(
        'redefinir-senha/concluido/',
        auth_views.PasswordResetCompleteView.as_view(template_name='usuarios/redefinir_senha_concluido.html'),
        name='redefinir_senha_concluido',
    ),

    # A nova rota do painel
    path('dashboard/', views.dashboard, name='dashboard'),
]