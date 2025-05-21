


document.addEventListener('DOMContentLoaded', () => {
  const donationModal      = new bootstrap.Modal('#donationModal');
  const tierCards          = document.querySelectorAll('.tier-card');
  const generalAmountInput = document.getElementById('general_amount');
  const openBtn            = document.getElementById('openModal');
  const form               = document.getElementById('generalDonationForm');
  const buttonContainer    = document.getElementById('paypal-button-container');
  const modalMessage       = document.getElementById('modal_message');
  const csrfToken          = document.querySelector('meta[name="csrf-token"]').content;

  // Format currency for display
  function formatCurrency(val) {
    const num = parseFloat(val);
    return isNaN(num)
      ? '$ 0.00'
      : num.toLocaleString('en-KE', { style: 'currency', currency: 'USD' });
  }

  // Tier selection
  tierCards.forEach(card => {
    card.addEventListener('click', () => {
      tierCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      generalAmountInput.value = card.dataset.amount;
    });
  });

  // Open modal and preview amount
  openBtn.addEventListener('click', () => {
    const amt = generalAmountInput.value.trim();
    if (!amt || isNaN(amt) || parseFloat(amt) < 1) {
      document.getElementById('generalDonationMessage').textContent =
        'Please enter a valid amount (minimum $ 1)';
      return;
    }
    document.getElementById('modal_amount').value = amt;
    document.getElementById('donationAmountPreview').textContent = formatCurrency(amt);
    document.getElementById('footerDonationAmount').textContent = formatCurrency(amt);
    donationModal.show();
  });

  // Initialize PayPal button only once per amount
  form.addEventListener('submit', e => {
    e.preventDefault();
    modalMessage.className = '';
    modalMessage.textContent = '';

    const name   = form.modal_name.value.trim();
    const email  = form.modal_email.value.trim();
    const amount = form.modal_amount.value.trim();
    const recpt  = form.modal_receipt.checked;

    if (!name || !email || !amount || isNaN(amount)) {
      modalMessage.classList.add('alert', 'alert-danger');
      modalMessage.textContent = 'Please fill in all required fields correctly.';
      return;
    }

    // Clear any existing button instance
    buttonContainer.innerHTML = '';

    paypal.Buttons({
      // Delegate Order Creation
      createOrder: () => fetch('/paypal/initialize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ name, email, amount, receipt: recpt, program_id: null })
      })
      .then(res => res.json())
      .then(json => {
        if (!json.status) throw new Error(json.message);
        return json.orderID;       // your backend returns orderID
      }),

      // Delegate Capture
      onApprove: data => fetch('/paypal/confirm', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ orderID: data.orderID })
      })
      .then(res => res.json())
      .then(details => {
        modalMessage.classList.add('alert', 'alert-success');
        modalMessage.textContent = `Thank you, ${details.payer.name.given_name}! Your donation was successful.`;
        setTimeout(() => donationModal.hide(), 3000);
      }),

      onError: err => {
        console.error('PayPal Error:', err);
        modalMessage.classList.add('alert', 'alert-danger');
        modalMessage.textContent = 'Payment failed. Please try again or contact support.';
      }

    }).render('#paypal-button-container');
  });

  // Optional: progress ring & counter animation
  const ring = document.querySelector('.progress-ring-circle');
  if (ring) gsap.to(ring, { strokeDashoffset: 0, duration: 2, ease: 'power2.out' });

  const counter = document.querySelector('.counter');
  if (counter) {
    const target = +counter.dataset.target;
    gsap.to(counter, { innerText: target, duration: 2, snap: { innerText: 1 }, ease: 'power2.out' });
  }
});
