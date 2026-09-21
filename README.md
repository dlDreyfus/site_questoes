# Simulado — site de questões de concurso

Aplicação web em Django para resolver questões de concursos públicos, acompanhar o próprio
desempenho e discutir as questões com outros usuários.

## Funcionalidades

- **Resolução de questões** de múltipla escolha (ME) e certo/errado (CE), com correção imediata,
  resolução oficial e paginação.
- **Filtros em cascata** por banca, órgão, cargo, ano, matéria e tópico: ao escolher um filtro, os
  demais dropdowns passam a listar só as opções que ainda têm questões com aquela escolha.
- **Subcabeçalho com o total de questões** cadastradas, no topo de todas as páginas para quem está
  logado. Na lista e no painel, conta só as questões que atendem aos filtros escolhidos.
- **Simulados** (`/simulados/novo/`, a partir do Meu Desempenho ou da lista de questões, que já leva
  os filtros escolhidos): o usuário escolhe os mesmos filtros
  da lista (em cascata) mais a **situação** — "Somente questões que errei" (a última resposta à
  questão foi errada) ou "Questões que ainda não resolvi" — e o site grava um conjunto fixo com as
  questões que atendem. Dentro do simulado cada questão é respondida uma vez, e o progresso e o
  resultado aparecem no simulado e na lista "Meus simulados" do Meu Desempenho. As respostas também
  entram nas estatísticas do painel. Cada simulado pode ser **renomeado** e **apagado** (com página
  de confirmação); apagar mantém as respostas no desempenho do usuário.
- **Painel de desempenho** (`/usuarios/dashboard/`) com total de respostas e taxa de acerto,
  filtrável por banca, cargo, matéria e tópico.
- **Fórum por questão**: comentários, respostas a comentários e curtidas; a resolução oficial
  aceita curtidas e descurtidas.
- **Contas de usuário**: cadastro (a conta já nasce ativa e o usuário entra logado), login, logout
  e recuperação de senha por e-mail.
- **Importação de questões por planilha CSV** (`/importar/`), restrita a quem tem a permissão
  `questoes.importar_questoes`.
- **Admin do Django** (`/admin/`) para cadastrar e editar bancas, órgãos, cargos, matérias,
  tópicos e questões.

## Tecnologias

- Python 3.14 e Django 6.1
- SQLite (banco padrão em desenvolvimento)
- HTML, CSS e JavaScript puros, sem framework de front-end

## Como rodar localmente

```bash
git clone https://github.com/dlDreyfus/site_questoes.git
cd site_questoes

python -m venv venv
source venv/bin/activate          # no Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# gere uma chave e cole em DJANGO_SECRET_KEY no .env:
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse http://127.0.0.1:8000/. Crie uma conta em "Cadastrar Novo Usuário" ou entre com o
superusuário, que também dá acesso ao `/admin/`.

### Variáveis de ambiente

| Variável               | Obrigatória | Descrição                                                        |
|------------------------|-------------|-------------------------------------------------------------------|
| `DJANGO_SECRET_KEY`    | Sim         | Chave secreta do Django                                          |
| `DJANGO_DEBUG`         | Não         | Padrão `False` (produção); use `True` em desenvolvimento (o `.env.example` já traz `True`) |
| `DJANGO_ALLOWED_HOSTS` | Em produção | Domínios do site separados por vírgula (ex: `meusite.pythonanywhere.com`). Sem a variável, usa `dlDreyfus.pythonanywhere.com` |

As variáveis podem ser definidas no ambiente ou no arquivo `.env` na raiz do projeto, que fica
fora do git. As do ambiente têm prioridade.

### E-mails

Só a recuperação de senha envia e-mails. Em `core/settings.py`, `MAILERS` usa o backend `console`
do Django: nenhum e-mail é realmente enviado, e o conteúdo (com o link para redefinir a senha)
aparece no terminal do `runserver` ou no log do servidor.

Isso serve para desenvolvimento, mas em produção a recuperação de senha só funciona de fato depois
de trocar o backend `console` de `MAILERS` por um servidor SMTP real.

## Importação de questões por CSV

A página `/importar/` mostra todas as colunas aceitas e oferece uma planilha modelo para baixar
(`/importar/modelo.csv`). Em resumo:

- Cada linha é uma questão completa. Bancas, órgãos, cargos, matérias e tópicos são
  reaproveitados quando já existem e criados quando não existem.
- `topicos` é obrigatória e aceita vários tópicos separados por `|`.
- `tipo` é `ME` ou `CE`; o `gabarito` é a letra da correta (ME) ou `CERTO`/`ERRADO` (CE).
- **Tudo ou nada**: todas as linhas são validadas antes de gravar. Se houver qualquer erro, nada
  é importado e cada erro aparece com linha, coluna e motivo (a numeração segue a do Excel, com o
  cabeçalho na linha 1).
- Um `codigo` que já existe no banco, ou que se repete na planilha, é erro.

Para liberar a importação a um usuário, dê a ele a permissão "Pode importar questões por planilha
CSV" pelo admin. Se existir um grupo chamado `Administrador`, a migração já concede a permissão a
ele.

## Testes

```bash
python manage.py test
```

## Estrutura

```
core/        configurações do projeto (settings, urls)
questoes/    questões, resolução, filtros, fórum, curtidas e importação CSV
usuarios/    modelo de usuário próprio, cadastro, login, recuperação de senha e painel de desempenho
templates/   base.html compartilhado
static/      CSS e JavaScript
```
