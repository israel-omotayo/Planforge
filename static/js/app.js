// static/js/app.js  — same file as before, replace send_mail section only

document.addEventListener('submit', function (e) {
  const form = e.target;
  const btn  = form.querySelector('[data-spinner]');
  if (btn) {
    btn.classList.add('btn-loading');
    // Keep spinner visible for at least 400ms even on fast responses
    setTimeout(() => {}, 400);
  }
});
