/* GoPoint Landing Page - Single-Page App Coordinator & Config */

window.GoPointConfig = {
  // Stripe Payment Link
  stripeCheckoutUrl: 'https://buy.stripe.com/aFa7sN5J82ec7zq99Qdby01',
  
  // Custom domain URL:
  domainUrl: 'https://www.gopoint.store',

  // GitHub Release Download Link
  githubReleaseUrl: 'https://github.com/vicr2245-sys/gopoint/releases/latest/download/GoPoint-Windows-x64.zip'
};

document.addEventListener('DOMContentLoaded', () => {
  // Navbar Scroll Background Toggle
  const navbar = document.querySelector('.navbar');
  window.addEventListener('scroll', () => {
    if (window.scrollY > 40) {
      navbar.classList.add('scrolled');
    } else {
      navbar.classList.remove('scrolled');
    }
  });

  // Global Toast Notification Handler
  window.showToast = function(message) {
    let toast = document.getElementById('toast-notice');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'toast-notice';
      toast.className = 'toast-notice';
      document.body.appendChild(toast);
    }
    toast.innerHTML = `<span>🚀</span> <div>${message}</div>`;
    toast.classList.add('show');

    setTimeout(() => {
      toast.classList.remove('show');
    }, 4000);
  };

  // Stripe & Checkout CTA Handlers
  const checkoutBtns = document.querySelectorAll('.trigger-checkout');
  checkoutBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const checkoutUrl = window.GoPointConfig.stripeCheckoutUrl;

      if (checkoutUrl && !checkoutUrl.includes('your_stripe_payment_link_here')) {
        window.location.href = checkoutUrl;
      } else {
        const planName = btn.getAttribute('data-plan') || 'GoPoint Pro License';
        window.showToast(`Selected <b>${planName}</b>. Update <code>GoPointConfig.stripeCheckoutUrl</code> in <code>website/js/app.js</code>.`);
        setTimeout(() => {
          alert(`🛒 Stripe Checkout Setup\n\nTo connect your Stripe checkout:\nOpen website/js/app.js and replace window.GoPointConfig.stripeCheckoutUrl with your Stripe Payment Link URL.\n\nExample:\nstripeCheckoutUrl: 'https://buy.stripe.com/3cs28x...'`);
        }, 300);
      }
    });
  });
});
