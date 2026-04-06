/* StudyMarket — main.js */

// ── Auto-dismiss flash messages ───────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".alert").forEach(el => {
    setTimeout(() => {
      el.style.transition = "opacity .5s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 500);
    }, 4000);
  });

  // ── File drop zone ──────────────────────────────────────────────────────
  const dropZone = document.getElementById("file-drop");
  if (dropZone) {
    const fileInput = dropZone.querySelector("input[type=file]");
    const label     = dropZone.querySelector(".file-label");

    dropZone.addEventListener("click", () => fileInput.click());

    dropZone.addEventListener("dragover", e => {
      e.preventDefault();
      dropZone.classList.add("drag-over");
    });
    dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
    dropZone.addEventListener("drop", e => {
      e.preventDefault();
      dropZone.classList.remove("drag-over");
      if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        updateFileLabel(fileInput.files[0].name);
      }
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files.length) updateFileLabel(fileInput.files[0].name);
    });

    function updateFileLabel(name) {
      if (label) label.textContent = `📎 ${name}`;
    }
  }

  // ── Admin tabs ──────────────────────────────────────────────────────────
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      tabPanels.forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const target = document.getElementById(btn.dataset.tab);
      if (target) target.classList.add("active");
    });
  });

  // Activate first tab by default
  if (tabBtns.length) tabBtns[0].click();

  // ── Mobile hamburger ────────────────────────────────────────────────────
  const hamburger = document.querySelector(".hamburger");
  const navLinks  = document.querySelector(".nav-links");
  if (hamburger && navLinks) {
    hamburger.addEventListener("click", () => navLinks.classList.toggle("open"));
  }

  // ── Star rating interactive UI ──────────────────────────────────────────
  const stars = document.querySelectorAll(".star-input");
  stars.forEach((star, idx) => {
    star.addEventListener("mouseover", () => highlightStars(idx));
    star.addEventListener("mouseout",  () => highlightStars(getSelectedRating() - 1));
    star.addEventListener("click", () => {
      document.getElementById("rating-value").value = idx + 1;
      highlightStars(idx);
    });
  });

  function highlightStars(upTo) {
    stars.forEach((s, i) => {
      s.textContent = i <= upTo ? "★" : "☆";
      s.style.color = i <= upTo ? "#f59e0b" : "#d1d5db";
    });
  }

  function getSelectedRating() {
    const rv = document.getElementById("rating-value");
    return rv ? parseInt(rv.value) || 0 : 0;
  }

  // Initialise star display
  if (stars.length) highlightStars(getSelectedRating() - 1);

  // ── Payment countdown ───────────────────────────────────────────────────
  const countdown = document.getElementById("payment-countdown");
  if (countdown) {
    let secs = parseInt(countdown.dataset.secs || "30");
    const interval = setInterval(() => {
      secs--;
      countdown.textContent = secs;
      if (secs <= 0) {
        clearInterval(interval);
        countdown.closest(".countdown-msg").textContent = "You can now confirm your payment.";
      }
    }, 1000);
  }
});
