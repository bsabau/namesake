// Result map: the shelter's area plus Qloo map cells coloured by lift.
// Everything drawn comes from the view model in #map-data; no data is computed here.

(function () {
  const container = document.getElementById("result-map");
  const data = document.getElementById("map-data");
  if (!container || !data || typeof L === "undefined") return;

  const view = JSON.parse(data.textContent);
  const map = L.map(container, { scrollWheelZoom: false })
    .setView([view.latitude, view.longitude], view.zoom);

  // The grid can settle after the map is created; re-measure so no tiles are missing.
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const css = getComputedStyle(document.documentElement);
  const colour = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const warm = colour("--lift-up", "#c2410c");
  const cool = colour("--lift-down", "#2563eb");
  const none = colour("--lift-none", "#78716c");

  L.circle([view.latitude, view.longitude], {
    radius: view.shelter_radius_m,
    color: colour("--accent", "#c2410c"),
    weight: 2,
    dashArray: "4 4",
    fill: false,
  }).addTo(map);

  const layers = view.cells.map((cell) => {
    const strength = cell.lift === null ? 0.25 : 0.2 + 0.6 * Math.min(1, Math.abs(cell.lift));
    const fill = cell.lift === null ? none : cell.lift >= 0 ? warm : cool;
    return L.rectangle(
      [[cell.south, cell.west], [cell.north, cell.east]],
      { color: fill, weight: 1, fillColor: fill, fillOpacity: strength },
    ).bindTooltip(cell.label).addTo(map);
  });

  if (layers.length) {
    const group = L.featureGroup(layers);
    map.fitBounds(group.getBounds().pad(0.3), { maxZoom: view.zoom + 1 });
  }
})();
