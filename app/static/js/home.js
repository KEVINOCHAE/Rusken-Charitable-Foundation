document.addEventListener('DOMContentLoaded', () => {
    // Animate elements using Intersection Observer
    const animateOnScroll = (elements) => {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            entry.target.classList.add('fade-in');
          }
        });
      }, { threshold: 0.1 });
  
      elements.forEach(el => observer.observe(el));
    };
  
    // Animate cards
    animateOnScroll(document.querySelectorAll('.card'));
    
    // Animate stats
    animateOnScroll(document.querySelectorAll('.glass-effect'));
  });


  document.addEventListener("DOMContentLoaded", () => {
    fetch('/categories')
      .then(res => res.json())
      .then(categories => {
        // Desktop menu
        const desktopMenu = document.getElementById('category-menu');
        desktopMenu.innerHTML = '';  // clear "Loading…"
  
        // 1️⃣ Add "All Programs" at the top
        desktopMenu.insertAdjacentHTML('beforeend', `
          <li>
            <a class="dropdown-item fw-semibold" href="/programs">
               All Projects
            </a>
          </li>
          <li><hr class="dropdown-divider"></li>
        `);
  
        // 2️⃣ Then inject each category
        categories.forEach(cat => {
          const li = document.createElement('li');
          li.innerHTML = `
            <a class="dropdown-item" href="/programs/category/${cat.slug}">
              ${cat.name}
            </a>
          `;
          desktopMenu.appendChild(li);
        });
  
        // Mobile menu
        const mobileMenu = document.getElementById('mobileCategoryMenu');
        mobileMenu.innerHTML = '';   // clear "Loading…"
  
        // 1️⃣ All Programs for mobile
        mobileMenu.insertAdjacentHTML('beforeend', `
          <li>
            <a class="nav-link ps-0 fw-semibold" href="/programs">
              All Programs
            </a>
          </li>
          <li><hr class="dropdown-divider"></li>
        `);
  
        // 2️⃣ Then each category
        categories.forEach(cat => {
          const li = document.createElement('li');
          li.innerHTML = `
            <a class="nav-link ps-0" href="/programs/category/${cat.slug}">
              ${cat.name}
            </a>
          `;
          mobileMenu.appendChild(li);
        });
  
      })
      .catch(err => {
        console.error('Failed to load categories:', err);
      });
  });
  

document.addEventListener('DOMContentLoaded', () => {
  // only on desktop widths
  if (window.innerWidth >= 992) {
    document.querySelectorAll('.navbar .dropdown').forEach(dropdown => {
      const toggle = dropdown.querySelector('[data-bs-toggle="dropdown"]');
      const bsDropdown = bootstrap.Dropdown.getOrCreateInstance(toggle);

      dropdown.addEventListener('mouseenter', () => bsDropdown.show());
      dropdown.addEventListener('mouseleave', () => bsDropdown.hide());
    });
  }
});




  