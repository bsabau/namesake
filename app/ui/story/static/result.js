// Picking another name option shows the local version as it reads with that name, and
// the "Why this name?" pair for it. Every value comes from the view model, carried on
// the option or already in the page; nothing is built here.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.name !== "local_name") return;
  const version = document.querySelector(".version-local");
  if (!version) return;
  version.querySelector("h1").textContent = input.value;
  const hook = version.querySelector(".hook");
  if (hook) hook.textContent = input.dataset.hook;
  const source = version.querySelector(".name-source-text");
  if (source) source.textContent = input.dataset.source;
  const copy = document.getElementById("copy-local");
  if (copy) copy.value = input.dataset.copy;
  const choice = document.querySelector('input[name="variant"][value="local"]');
  const text = choice && choice.parentElement.querySelector(".version-choice-text");
  if (text) text.textContent = input.dataset.choice;
  document.querySelectorAll("[data-name-detail]").forEach((pair) => {
    pair.hidden = pair.dataset.nameDetail !== input.value;
  });
});
