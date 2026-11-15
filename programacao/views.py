from django.contrib.auth.decorators import login_required
from django.shortcuts import render


# Home: barra fixa no topo e barra lateral com os apps, que abrem em abas dentro dela
@login_required
def home(request):
    return render(request, 'home.html')


# Página inicial do app de programação (é a que abre na aba "Programação" da Home).
# Enquanto o app não fica pronto, mostra a página em construção
@login_required
def inicio(request):
    return render(request, 'em_construcao.html')
