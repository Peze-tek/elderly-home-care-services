document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".nav");
  const toggle = document.querySelector(".menu-toggle");

  if (toggle && menu) {
    toggle.addEventListener("click", () => {
      const open = menu.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  document.querySelectorAll(".nav a").forEach(link => {
    link.addEventListener("click", () => menu?.classList.remove("open"));
  });

  document.querySelectorAll("#year").forEach(el => {
    el.textContent = new Date().getFullYear();
  });

  const form = document.querySelector("#contactForm");
  if (form) {
    form.addEventListener("submit", event => {
      event.preventDefault();

      const data = new FormData(form);
      const name = String(data.get("name") || "").trim();
      const email = String(data.get("email") || "").trim();
      const phone = String(data.get("phone") || "").trim();
      const service = String(data.get("service") || "").trim();
      const message = String(data.get("message") || "").trim();

      const subject = encodeURIComponent(`Care enquiry from ${name}`);
      const body = encodeURIComponent(
        `Name: ${name}\nEmail: ${email}\nPhone: ${phone}\nService: ${service}\n\nMessage:\n${message}`
      );

      window.location.href =
        `mailto:info@elderlyhomecareservices.com?subject=${subject}&body=${body}`;
    });
  }
});
