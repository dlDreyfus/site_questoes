from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower


# Model de usuário próprio do projeto (recomendação oficial do Django para todo projeto novo).
# Por enquanto é idêntico ao User padrão; novos campos (ex: foto, cargo pretendido) podem ser
# adicionados aqui no futuro sem precisar refazer as migrações.
class Usuario(AbstractUser):
    class Meta:
        verbose_name = 'usuário'
        verbose_name_plural = 'usuários'
        constraints = [
            # Um e-mail só pode pertencer a uma conta (sem diferenciar maiúsculas de minúsculas),
            # porque a recuperação de senha é feita por ele.
            # Contas sem e-mail (ex: criadas pelo admin) continuam permitidas.
            models.UniqueConstraint(
                Lower('email'),
                condition=~models.Q(email=''),
                name='email_unico_por_usuario',
                violation_error_message='Já existe uma conta com este e-mail.',
            ),
        ]
