// The shelter bar above the animals: it names the chosen area, and its panel holds the
// choice. Kept apart from the map script, so it works even when the map cannot load.

(function () {
  const panel = document.getElementById("shelter");
  const form = document.getElementById("pick");
  const data = document.getElementById("map-points");
  if (!panel || !form) return;
  const name = document.getElementById("shelter-name");
  const region = document.getElementById("shelter-region");
  const points = data ? Object.fromEntries(JSON.parse(data.textContent).map((p) => [p.id, p])) : {};

  // Choosing an area renames the bar (label and region come from the view model).
  document.querySelectorAll('input[name="location"]').forEach((input) => {
    input.addEventListener("change", () => {
      const p = points[input.value];
      if (!p) return;
      if (name) name.textContent = p.label;
      if (region) region.textContent = p.region;
      panel.classList.remove("unchosen");
    });
  });

  // Picking an animal with no area chosen: the required choice sits in the panel, which a
  // browser cannot point at while it is closed, so open it and ask again.
  form.addEventListener(
    "invalid",
    () => {
      if (panel.open) return;
      panel.open = true;
      setTimeout(() => form.reportValidity(), 0);
    },
    true,
  );
})();
