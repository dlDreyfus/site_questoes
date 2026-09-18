from django.contrib.auth.forms import UserCreationForm
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
        # A recuperação de senha é feita por este e-mail, então ele não pode pertencer a outra conta
        # (a mesma regra existe no banco, em Usuario.Meta.constraints; aqui a mensagem fica no campo)
        email = self.cleaned_data['email']
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError('Já existe uma conta com este e-mail.')
        return email

