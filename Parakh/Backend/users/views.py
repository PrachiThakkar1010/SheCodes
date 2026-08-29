from django.shortcuts import render

from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from products.models import ProductScan


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful!')
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserCreationForm()

    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {username}!')
                return redirect('dashboard')
        messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()

    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('login')


def forgot_password_view(request):
    return render(request, 'forgot-password.html')


@login_required(login_url='login')
def dashboard_view(request):
    recent_scans = ProductScan.objects.filter(user=request.user).order_by('-scanned_at')[:5]
    total_scans = ProductScan.objects.filter(user=request.user).count()
    compliant_scans = ProductScan.objects.filter(user=request.user, status='COMPLIANT').count()

    context = {
        'recent_scans': recent_scans,
        'total_scans': total_scans,
        'compliant_scans': compliant_scans,
    }
    return render(request, 'dashboard.html', context)