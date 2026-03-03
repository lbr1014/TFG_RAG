/* =========================
   DESPLEGABLE 
   ========================= */
document.addEventListener('click', function (e) {
  const dropdowns = document.querySelectorAll('.dropdown');

  dropdowns.forEach(dropdown => {
    const button = dropdown.querySelector('.dropdown-toggle');

    if (button && button.contains(e.target)) {
      dropdown.classList.toggle('open');
    } else {
      dropdown.classList.remove('open');
    }
  });
});

/* =========================
   EFECTO LUZ 
   ========================= */

document.addEventListener("mousemove", function (e) {
  const btn = e.target.closest(".btn-modelo");
  if (!btn) return;

  const rect = btn.getBoundingClientRect();
  const x = ((e.clientX - rect.left) / rect.width) * 100;
  const y = ((e.clientY - rect.top) / rect.height) * 100;

  btn.style.setProperty("--x", `${x}%`);
  btn.style.setProperty("--y", `${y}%`);
});

