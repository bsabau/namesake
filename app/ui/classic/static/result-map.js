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

  // The shelter's area: around the spot the visitor picked, when they picked one.
  const shelter = view.pin ? [view.pin.latitude, view.pin.longitude] : [view.latitude, view.longitude];
  L.circle(shelter, {
    radius: view.shelter_radius_m,
    color: colour("--accent", "#c2410c"),
    weight: 2,
    dashArray: "4 4",
    fill: false,
  }).addTo(map);
  if (view.pin) {
    L.circleMarker(shelter, {
      radius: 8, color: "#fff", weight: 2, fillColor: colour("--accent", "#c2410c"), fillOpacity: 1,
    }).bindTooltip("The spot you picked for the shelter").addTo(map);
  }

  const layers = view.cells.map((cell) => {
    const strength = cell.lift === null ? 0.25 : 0.2 + 0.6 * Math.min(1, Math.abs(cell.lift));
    const fill = cell.lift === null ? none : cell.lift >= 0 ? warm : cool;
    return L.rectangle(
      [[cell.south, cell.west], [cell.north, cell.east]],
      { color: fill, weight: 1, fillColor: fill, fillOpacity: strength },
    ).bindTooltip(cell.label).addTo(map);
  });

  // A short key on the map itself (the view model's note); the caption says the rest.
  if (view.note) {
    const key = L.control({ position: "bottomleft" });
    key.onAdd = () => {
      const box = L.DomUtil.create("div", "map-key");
      const heading = L.DomUtil.create("strong", "", box);
      heading.textContent = view.note_heading;
      const text = L.DomUtil.create("p", "", box);
      text.textContent = view.note;
      L.DomEvent.disableClickPropagation(box);
      return box;
    };
    key.addTo(map);
  }

  // The cells, and the visitor's pin with them, so it is never off the edge.
  if (view.pin) layers.push(L.circleMarker(shelter, { radius: 0, opacity: 0 }));
  if (layers.length) {
    const group = L.featureGroup(layers);
    map.fitBounds(group.getBounds().pad(0.3), { maxZoom: view.zoom + 1 });
  }
})();
