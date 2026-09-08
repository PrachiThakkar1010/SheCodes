from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from products.models import ProductScan
from .models import UserProfile


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        name = request.POST.get('name', '').strip()
        mobile = request.POST.get('mobile', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Validations
        if not username or not email or not password:
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'register.html')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username is already taken.')
            return render(request, 'register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email is already registered.')
            return render(request, 'register.html')

        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name
        )

        # Create profile with mobile number
        UserProfile.objects.create(user=user, mobile_number=mobile)

        # Log in and redirect to dashboard
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'Welcome to Parakh, {user.username}!')
        return redirect('dashboard')

    return render(request, 'register.html')


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
                messages.success(request, f'Login successful, {username}!')
                return redirect('dashboard')
        messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()

    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been successfully logged out.')
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

@login_required(login_url='login')
def profile_view(request):
    user = request.user
    # Ensure profile exists
    profile, _ = UserProfile.objects.get_or_create(user=user)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        email = request.POST.get('email', '').strip()
        mobile = request.POST.get('mobile_number', '').strip()

        # Update User model
        user.first_name = first_name
        user.email = email
        user.save()

        # Update UserProfile model
        profile.mobile_number = mobile
        profile.save()

        messages.success(request, 'Profile updated successfully!')
        return redirect('profile')

    return render(request, 'profile.html', {'profile': profile})


@login_required(login_url='login')
def history_view(request):
    status_filter = request.GET.get('status', '').strip()

    scans = ProductScan.objects.filter(user=request.user).order_by('-scanned_at')

    if status_filter:
        scans = scans.filter(status=status_filter)

    context = {
        'scans': scans,
        'selected_status': status_filter,
        'total_scans_count': ProductScan.objects.filter(user=request.user).count(),
    }
    return render(request, 'history.html', context)