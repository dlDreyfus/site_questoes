from django.contrib.auth.tokens import PasswordResetTokenGenerator


# Gera o token do link de ativação da conta. Reaproveita o gerador da recuperação de senha
# (assinado com a SECRET_KEY e com validade de PASSWORD_RESET_TIMEOUT), mudando dois pontos:
class AtivacaoContaTokenGenerator(PasswordResetTokenGenerator):
    # 1. Um "sal" próprio: um token de recuperação de senha não serve para ativar conta, e vice-versa
    key_salt = 'usuarios.tokens.AtivacaoContaTokenGenerator'

    # 2. O estado de ativação entra no hash: quando a conta é ativada, o token deixa de valer (uso único)
    def _make_hash_value(self, user, timestamp):
        return f'{super()._make_hash_value(user, timestamp)}{user.is_active}'


ativacao_token = AtivacaoContaTokenGenerator()
