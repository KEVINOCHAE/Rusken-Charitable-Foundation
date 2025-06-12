
document.addEventListener('DOMContentLoaded', () => {
  // Initialize modal
  const donationModal = new bootstrap.Modal(document.getElementById('donationModal'));

  // Format helper
  function formatCurrency(value) {
    const num = parseFloat(value);
    return isNaN(num)
      ? 'KES0.00'
      : num.toLocaleString('en-KE', { style: 'currency', currency: 'KES' });
  }

  // Tier selection
  const tierCards = document.querySelectorAll('.tier-card');
  const generalAmountInput = document.getElementById('general_amount');

  tierCards.forEach(card => {
    card.addEventListener('click', function () {
      tierCards.forEach(c => c.classList.remove('active'));
      this.classList.add('active');
      generalAmountInput.value = this.dataset.amount;
    });
  });

  // Open modal with validation
  document.getElementById('openModal').addEventListener('click', function () {
    const amount = generalAmountInput.value.trim();
    const messageEl = document.getElementById('generalDonationMessage');

    if (!amount || isNaN(amount)) {
      messageEl.textContent = "Please enter a valid donation amount";
      gsap.fromTo(messageEl,
        { x: -10 },
        { x: 0, duration: 0.3, ease: "elastic.out(1, 0.5)" }
      );
      return;
    }

    if (parseFloat(amount) < 1) {
      messageEl.textContent = "Minimum donation is KES 1";
      return;
    }

    messageEl.textContent = "";
    document.getElementById('modal_amount').value = amount;

    const formatted = formatCurrency(amount);
    document.getElementById('donationAmountPreview').textContent = formatted;
    document.getElementById('footerDonationAmount').textContent = formatted;

    donationModal.show();
  });

  // Animate progress circle
  const progressCircle = document.querySelector('.progress-ring-circle');
  if (progressCircle) {
    gsap.to(progressCircle, {
      strokeDashoffset: 0,
      duration: 2,
      ease: "power2.out"
    });
  }

  // Animate counter
  const counter = document.querySelector('.counter');
  if (counter) {
    const target = parseInt(counter.dataset.target);
    gsap.to(counter, {
      innerText: target,
      duration: 2,
      snap: { innerText: 1 },
      ease: "power2.out"
    });
  }

  // Handle form submission
  document.getElementById('generalDonationForm').addEventListener('submit', async function (e) {
    e.preventDefault();

    const formData = {
      name: document.getElementById('modal_name').value.trim(),
      email: document.getElementById('modal_email').value.trim(),
      amount: document.getElementById('modal_amount').value.trim(),
      receipt: document.getElementById('modal_receipt').checked
    };

    const messageEl = document.getElementById('modal_message');

    if (!formData.name || !formData.email || !formData.amount) {
      messageEl.textContent = "Please fill in all required fields";
      messageEl.classList.remove('d-none', 'alert-success');
      messageEl.classList.add('alert-danger');
      return;
    }

    try {
      const submitBtn = document.querySelector('.btn-donate-now');
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Processing...';

      const response = await fetch('/dpo/initialize', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
        },
        body: JSON.stringify({
          email: formData.email,
          amount: formData.amount,
          donor_name: formData.name,
          program_id: null
        })
      });

      const data = await response.json();

      if (data.status && data.authorization_url) {
        window.location.href = data.authorization_url;
      } else {
        throw new Error(data.message || 'Failed to initialize payment');
      }

    } catch (error) {
      messageEl.textContent = error.message || "Payment processing failed";
      messageEl.classList.remove('d-none', 'alert-success');
      messageEl.classList.add('alert-danger');

      const submitBtn = document.querySelector('.btn-donate-now');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = `
          <span class="donate-text">Donate Now</span>
          <span class="donate-amount ms-1">${formatCurrency(formData.amount)}</span>
          <i class="fas fa-arrow-right ms-2"></i>
        `;
      }
    }
  });
});
