from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from products.models import ProductScan
from .models import UserProfile, CompanyProfile

from django.utils.http import url_has_allowed_host_and_scheme


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        user_type = request.POST.get('user_type', 'consumer').strip()
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

        if user_type == 'company':
            company_name = request.POST.get('company_name', '').strip()
            gst_number = request.POST.get('gst_number', '').strip()
            if not company_name or not gst_number:
                messages.error(request, 'Company name and GSTIN are required.')
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

        # Create user (adjust user_type storage if stored on custom User or profile)
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name if user_type == 'consumer' else ''
        )

        # If user_type is stored on user model attribute:
        if hasattr(user, 'user_type'):
            user.user_type = user_type
            user.save()

        # Create profile types
        if user_type == 'company':
            CompanyProfile.objects.create(
                user=user,
                company_name=request.POST.get('company_name', '').strip(),
                gst_number=request.POST.get('gst_number', '').strip()
            )
        else:
            UserProfile.objects.create(user=user, mobile_number=mobile)

        # Log in and redirect
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f'Welcome to Parakh, {user.username}!')

        return redirect('company_dashboard' if user_type == 'company' else 'dashboard')

    return render(request, 'register.html')


def login_view(request):
    if request.user.is_authenticated:
        if (
            hasattr(request.user, 'companyprofile')
            or getattr(request.user, 'user_type', None) == 'company'
        ):
            return redirect('company_dashboard')
        return redirect('dashboard')

    next_url = request.GET.get('next', '').strip()

    if request.method == 'POST':
        next_url = request.POST.get('next', next_url).strip()

        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')

            user = authenticate(
                request,
                username=username,
                password=password
            )

            if user is not None:
                login(request, user)

                messages.success(
                    request,
                    f'Login successful, {username}!'
                )

                # Redirect to the requested page if it is safe
                if next_url and url_has_allowed_host_and_scheme(
                    url=next_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    return redirect(next_url)

                # Redirect company users to company dashboard
                is_company = (
                    hasattr(user, 'companyprofile')
                    or getattr(user, 'user_type', None) == 'company'
                )

                if is_company:
                    return redirect('company_dashboard')

                # Normal users
                return redirect('dashboard')

        messages.error(
            request,
            'Invalid username or password.'
        )

    else:
        form = AuthenticationForm()

    return render(
        request,
        'login.html',
        {
            'form': form,
            'next_url': next_url,
        }
    )


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
    profile, _ = UserProfile.objects.get_or_create(user=user)

    next_url = request.GET.get('next', '').strip()

    if request.method == 'POST':
        next_url = request.POST.get('next', next_url).strip()

        first_name = request.POST.get('first_name', '').strip()
        email = request.POST.get('email', '').strip()
        mobile = request.POST.get('mobile_number', '').strip()

        if not email:
            messages.error(request, 'Email address is required.')

            return render(
                request,
                'profile.html',
                {
                    'profile': profile,
                    'next_url': next_url,
                },
            )

        if not mobile:
            messages.error(request, 'Mobile number is required.')

            return render(
                request,
                'profile.html',
                {
                    'profile': profile,
                    'next_url': next_url,
                },
            )

        user.first_name = first_name
        user.email = email
        user.save()

        profile.mobile_number = mobile
        profile.save()

        messages.success(
            request,
            'Profile updated successfully!'
        )

        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)

        return redirect('profile')

    return render(
        request,
        'profile.html',
        {
            'profile': profile,
            'next_url': next_url,
        },
    )

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

@login_required(login_url='login')
def company_dashboard(request):
    is_company = hasattr(request.user, 'companyprofile') or getattr(request.user, 'user_type', None) == 'company'
    if not is_company:
        return redirect('home')
    return render(request, 'company_dashboard.html')