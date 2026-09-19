document.addEventListener('DOMContentLoaded', () => {
    const toasts = document.querySelectorAll('.toast-popup');
    toasts.forEach(toast => {
        setTimeout(() => {
            toast.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 400);
        }, 4000);
    });
});