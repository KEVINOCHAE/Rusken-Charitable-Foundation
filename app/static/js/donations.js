document.addEventListener('DOMContentLoaded', () => {
  // Initialize elements
  const donationModal = new bootstrap.Modal('#donationModal');
  const tierCards = document.querySelectorAll('.tier-card');
  const generalAmountInput = document.getElementById('general_amount');
  const openBtn = document.getElementById('openModal');
  const form = document.getElementById('generalDonationForm');
  const buttonContainer = document.getElementById('paypal-button-container');
  const modalMessage = document.getElementById('modal_message');

  // Format currency
  function formatCurrency(val) {
    const num = parseFloat(val);
    return isNaN(num) ? '$0.00' : 
      num.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  // Handle tier selection
  tierCards.forEach(card => {
    card.addEventListener('click', () => {
      tierCards.forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      generalAmountInput.value = card.dataset.amount;
    });
  });

  // Open donation modal
  openBtn.addEventListener('click', () => {
    const amt = generalAmountInput.value.trim();
    if (!amt || isNaN(amt) || parseFloat(amt) < 1) {
      document.getElementById('generalDonationMessage').textContent =
        'Please enter a valid amount (minimum $1)';
      return;
    }
    document.getElementById('modal_amount').value = amt;
    document.getElementById('donationAmountPreview').textContent = formatCurrency(amt);
    document.getElementById('footerDonationAmount').textContent = formatCurrency(amt);
    donationModal.show();
  });

  // Initialize PayPal button when modal opens
  donationModal._element.addEventListener('shown.bs.modal', () => {
    // Clear previous button
    buttonContainer.innerHTML = '';
    
    // Get the current amount
    const amount = parseFloat(document.getElementById('modal_amount').value).toFixed(2);
    
    // Initialize PayPal button with direct client-side integration
    paypal.Buttons({
      style: {
        shape: 'pill',
        color: 'blue',
        layout: 'vertical',
        label: 'pay',
        height: 45
      },

      // Create order directly with PayPal 
      createOrder: (data, actions) => {
        return actions.order.create({
          purchase_units: [{
            amount: {
              currency_code: 'USD',
              value: amount
            },
            description: 'Rusken Charitable Donation'
          }],
          application_context: {
            shipping_preference: 'NO_SHIPPING'
          }
        });
      },

      // On approval, show success message
      onApprove: (data, actions) => {
        return actions.order.capture().then(() => {
          // Get form values
          const name = form.modal_name.value.trim();
          
          showSuccess({
            donorName: name,
            amount: amount,
            transactionId: data.orderID
          });
          
          // Optional: Submit form data to your server
          submitDonationData({
            name: name,
            email: form.modal_email.value.trim(),
            amount: amount,
            receipt: form.modal_receipt.checked,
            transactionId: data.orderID
          });
        });
      },

      onError: (err) => {
        console.error('PayPal Error:', err);
        modalMessage.classList.add('alert', 'alert-danger');
        modalMessage.textContent = 'Payment processing failed. Please try again.';
      },

      onCancel: () => {
        modalMessage.classList.add('alert', 'alert-warning');
        modalMessage.textContent = 'Payment was cancelled. You may try again.';
      }

    }).render('#paypal-button-container');
  });

  // Function to submit donation data to your server (optional)
  function submitDonationData(donationData) {
    fetch('/donations/record', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]').content
      },
      body: JSON.stringify(donationData)
    })
    .then(response => response.json())
    .then(data => {
      console.log('Donation recorded:', data);
    })
    .catch(error => {
      console.error('Error recording donation:', error);
    });
  }

  // Show success message
  function showSuccess(result) {
    modalMessage.classList.add('alert', 'alert-success');
    modalMessage.innerHTML = `
      <div class="d-flex align-items-center">
        <i class="fas fa-check-circle me-3 text-success" style="font-size: 2rem;"></i>
        <div>
          <h5 class="mb-1">Thank you, ${result.donorName}!</h5>
          <p class="mb-1">Amount: <strong>${formatCurrency(result.amount)}</strong></p>
          <small class="text-muted">Transaction ID: ${result.transactionId}</small>
        </div>
      </div>
    `;
    
    setTimeout(() => donationModal.hide(), 3000);
    
    // Update UI or analytics
    if (typeof updateDonationCounter === 'function') {
      updateDonationCounter(result.amount);
    }
  }

  // Initialize animations
  const ring = document.querySelector('.progress-ring-circle');
  if (ring) {
    gsap.to(ring, { 
      strokeDashoffset: 0, 
      duration: 2, 
      ease: 'power2.out' 
    });
  }

  const counter = document.querySelector('.counter');
  if (counter) {
    const target = +counter.dataset.target;
    gsap.to(counter, { 
      innerText: target, 
      duration: 2, 
      snap: { innerText: 1 }, 
      ease: 'power2.out' 
    });
  }
});