// The flyer page's one button: print it. Without scripts, the browser's own print works.
document.querySelectorAll("[data-print]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});
