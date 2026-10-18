// Picking another name option shows the local version as it reads with that name.
// Every value comes from the view model, carried on the option; nothing is built here.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.name !== "local_name") return;
  const version = document.querySelector(".version-local");
  if (!version) return;
  version.querySelector(".name").textContent = input.value;
  const hook = document.querySelector(".version-local .hook");
  if (hook) hook.textContent = input.dataset.hook;
  const source = version.querySelector(".name-source-text");
  if (source) source.textContent = input.dataset.badge;
  const copy = document.getElementById("copy-local");
  if (copy) copy.value = input.dataset.copy;
  document.querySelectorAll("[data-name-detail]").forEach((detail) => {
    detail.hidden = detail.dataset.nameDetail !== input.value;
  });
});

document.querySelector(".edit-link")?.addEventListener("click", (event) => {
  event.preventDefault();
  document.getElementById("approval-editor").open = true;
  document.getElementById("edit-text").focus();
});
