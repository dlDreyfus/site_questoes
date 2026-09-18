from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from .models import Usuario


# Formulário de cadastro: reaproveita o UserCreationForm do Django (valida usuário repetido,
# confirmação de senha e as regras de AUTH_PASSWORD_VALIDATORS), apontando para o model próprio.
class CadastroUsuarioForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # E-mail obrigatório no cadastro (no model ele é opcional)
        self.fields['email'].required = True

    def clean_email(self):
        # O link de ativação vai para este e-mail, então ele não pode pertencer a outra conta
        # (a mesma regra existe no banco, em Usuario.Meta.constraints; aqui a mensagem fica no campo)
        email = self.cleaned_data['email']
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError('Já existe uma conta com este e-mail.')
        return email


# Formulário de login que avisa quando a conta ainda não foi ativada pelo e-mail.
class LoginForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'inactive': 'Sua conta ainda não foi ativada. Clique no link que enviamos para o seu e-mail.',
    }

    def clean(self):
        # O backend padrão do Django recusa contas inativas com o mesmo erro de "usuário ou senha
        # incorretos". Para não confundir quem acabou de se cadastrar, se a senha estiver certa e a
        # conta estiver inativa, mostramos o aviso de ativação pendente (e o template oferece o reenvio).
        # A senha é conferida antes, então isso não revela quais usuários existem.
        self.conta_inativa = False
        try:
            return super().clean()
        except ValidationError:
            usuario = Usuario.objects.filter(username=self.cleaned_data.get('username')).first()
            senha = self.cleaned_data.get('password')
            if usuario and not usuario.is_active and senha and usuario.check_password(senha):
                self.conta_inativa = True
                raise ValidationError(self.error_messages['inactive'], code='inactive')
            raise


# Formulário para pedir um novo link de ativação
class ReenviarAtivacaoForm(forms.Form):
    email = forms.EmailField(label='E-mail', max_length=254)
