
import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega as variáveis do arquivo .env (fora do git) sem sobrescrever as já definidas no ambiente
_arquivo_env = BASE_DIR / '.env'
if _arquivo_env.exists():
    for _linha in _arquivo_env.read_text(encoding='utf-8').splitlines():
        _linha = _linha.strip()
        if _linha and not _linha.startswith('#') and '=' in _linha:
            _chave, _valor = _linha.split('=', 1)
            os.environ.setdefault(_chave.strip(), _valor.strip().strip('\'"'))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# Definida no .env (veja .env.example); sem ela o projeto não sobe
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

# SECURITY WARNING: don't run with debug turned on in production!
# Padrão False (seguro para produção); em desenvolvimento defina DJANGO_DEBUG=True no .env
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

# Domínios que podem servir o site (ex: "meusite.pythonanywhere.com"), separados por vírgula.
# Sem a variável DJANGO_ALLOWED_HOSTS, usa o domínio do deploy no PythonAnywhere.
# Com DEBUG=True, localhost/127.0.0.1 já funcionam mesmo com a lista vazia.
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get('DJANGO_ALLOWED_HOSTS', 'dlDreyfus.pythonanywhere.com').split(',')
    if host.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Apps do projeto
    'questoes',
    'usuarios',

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Pasta templates/ na raiz do projeto: base.html e templates compartilhados por todos os apps
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Total de questões do subcabeçalho (templates/base.html)
                'questoes.context_processors.total_questoes',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'pt-br'

TIME_ZONE = 'America/Recife'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = '/static/'

# Pasta static/ na raiz do projeto: CSS, JS e imagens compartilhados por todos os apps
# (os apps continuam podendo ter a própria pasta <app>/static/, que o Django encontra sozinho)
STATICFILES_DIRS = [BASE_DIR / 'static']

# Pasta onde o comando collectstatic reúne todos os arquivos estáticos (usada em produção)
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

# Com EMAIL_HOST definido (no .env ou no ambiente), os e-mails saem de verdade pelo servidor SMTP.
# Sem ele (o normal em desenvolvimento), o backend "console" não envia nada: o e-mail (ex: link de
# recuperação de senha) é impresso no terminal do runserver. Veja .env.example.
if os.environ.get('EMAIL_HOST'):
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
            'OPTIONS': {
                'host': os.environ['EMAIL_HOST'],
                'port': int(os.environ.get('EMAIL_PORT', 587)),
                'username': os.environ.get('EMAIL_HOST_USER', ''),
                'password': os.environ.get('EMAIL_HOST_PASSWORD', ''),
                # STARTTLS na porta 587 (Gmail e a maioria dos serviços)
                'use_tls': True,
                # Segundos até desistir: sem isso, um servidor que não responde travaria a página
                'timeout': 10,
            },
        },
    }
else:
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend',
        },
    }

# Remetente dos e-mails enviados pelo site (ex: recuperação de senha). No Gmail, precisa ser a
# própria conta de EMAIL_HOST_USER
DEFAULT_FROM_EMAIL = os.environ.get('DJANGO_DEFAULT_FROM_EMAIL', 'Simulado <nao-responda@simulado.local>')

# Validade do link de recuperação de senha, em segundos (1 dia; o padrão do Django é 3 dias)
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24

# Model de usuário próprio do projeto (usuarios/models.py)
AUTH_USER_MODEL = 'usuarios.Usuario'

# Direciona o usuário após ele logar ou deslogar

LOGIN_REDIRECT_URL = 'questoes:lista_questoes'
LOGIN_URL = 'usuarios:login'