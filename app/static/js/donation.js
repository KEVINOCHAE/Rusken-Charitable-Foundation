

document.addEventListener('DOMContentLoaded', () => {
  const donationModal = new bootstrap.Modal(document.getElementById('donationModal'));

  function formatCurrency(value) {
    const num = parseFloat(value);
    return isNaN(num)
      ? '$ 0.00'
      : num.toLocaleString('en-KE', { style: 'currency', currency: 'USD' });
  }

  const tierCards = document.querySelectorAll('.tier-card');
  const generalAmountInput = document.getElementById('general_amount');

  tierCards.forEach(card => {
    card.addEventListener('click', function () {
      tierCards.forEach(c => c.classList.remove('active'));
      this.classList.add('active');
      generalAmountInput.value = this.dataset.amount;
    });
  });

  document.getElementById('openModal').addEventListener('click', () => {
    const amount = generalAmountInput.value.trim();
    const messageEl = document.getElementById('generalDonationMessage');

    if (!amount || isNaN(amount) || parseFloat(amount) < 1) {
      messageEl.textContent = "Please enter a valid amount (minimum $ 1)";
      return;
    }

    messageEl.textContent = '';
    document.getElementById('modal_amount').value = amount;
    document.getElementById('donationAmountPreview').textContent = formatCurrency(amount);
    document.getElementById('footerDonationAmount').textContent = formatCurrency(amount);

    donationModal.show();
  });

  // Animate progress ring & counter
  const progressCircle = document.querySelector('.progress-ring-circle');
  if (progressCircle) {
    gsap.to(progressCircle, { strokeDashoffset: 0, duration: 2, ease: "power2.out" });
  }
  const counter = document.querySelector('.counter');
  if (counter) {
    const target = parseInt(counter.dataset.target);
    gsap.to(counter, { innerText: target, duration: 2, snap: { innerText: 1 }, ease: "power2.out" });
  }

  // Handle form submit and render PayPal button
  document.getElementById('generalDonationForm').addEventListener('submit', function (e) {
    e.preventDefault();

    const name = document.getElementById('modal_name').value.trim();
    const email = document.getElementById('modal_email').value.trim();
    const amount = document.getElementById('modal_amount').value.trim();
    const receipt = document.getElementById('modal_receipt').checked;
    const messageEl = document.getElementById('modal_message');

    messageEl.classList.remove('alert-success', 'alert-danger');
    messageEl.textContent = '';

    if (!name || !email || !amount || isNaN(amount)) {
      messageEl.textContent = "Please fill in all required fields with valid data";
      messageEl.classList.add('alert', 'alert-danger');
      return;
    }

    const buttonContainer = document.getElementById('paypal-button-container');
    buttonContainer.innerHTML = ''; // Clear existing button

    paypal.Buttons({
      createOrder: function (data, actions) {
        return actions.order.create({
          purchase_units: [{
            amount: {
              value: amount
            },
            description: "General Donation"
          }],
          payer: {
            name: { given_name: name },
            email_address: email
          }
        });
      },
      onApprove: function (data, actions) {
        return actions.order.capture().then(async function (details) {
          messageEl.classList.add('alert', 'alert-success');
          messageEl.textContent = "Thank you, " + details.payer.name.given_name + "! Your donation was successful.";

          // Optionally save to your backend
          try {
            await fetch('/paypal/confirm', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
              },
              body: JSON.stringify({
                orderID: data.orderID,
                donor_name: name,
                email: email,
                amount: amount,
                receipt: receipt,
                program_id: null
              })
            });
          } catch (err) {
            console.error("Failed to save donation:", err);
          }

          setTimeout(() => donationModal.hide(), 3000);
        });
      },
      onError: function (err) {
        console.error(err);
        messageEl.classList.add('alert', 'alert-danger');
        messageEl.textContent = "Something went wrong during the payment process.";
      }
    }).render('#paypal-button-container');
  });
});

