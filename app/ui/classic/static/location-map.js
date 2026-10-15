// Map of the selected shelter location: Leaflet with OpenStreetMap tiles.
// The preset locations come from the page (#map-points, the view model's list);
// picking a location card moves the map there.

(function () {
  const container = document.getElementById("location-map");
  const data = document.getElementById("map-points");
  if (!container || !data || typeof L === "undefined") return;

  const points = Object.fromEntries(JSON.parse(data.textContent).map((p) => [p.id, p]));
  const checked = document.querySelector('input[name="location"]:checked');
  const start = points[checked ? checked.value : Object.keys(points)[0]];

  // Narrow maps (phones) zoom out one step so the area still has some context around it.
  const zoomFor = (p) => p.zoom - (container.clientWidth < 500 ? 1 : 0);

  const map = L.map(container, { scrollWheelZoom: false })
    .setView([start.latitude, start.longitude], zoomFor(start));

  // The grid can settle after the map is created; re-measure so no tiles are missing.
  new ResizeObserver(() => map.invalidateSize()).observe(container);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim() || "#c2410c";

  // A soft circle, not a pin: the shelter is fictional, so we only show an area.
  const area = L.circle([start.latitude, start.longitude], {
    radius: start.shelter_radius_m,
    color: accent,
    weight: 2,
    fillOpacity: 0.15,
  }).addTo(map);
  container.setAttribute("aria-label", `Map of the area around the shelter in ${start.label}`);

  document.querySelectorAll('input[name="location"]').forEach((input) => {
    input.addEventListener("change", () => {
      const p = points[input.value];
      if (!p) return;
      area.setLatLng([p.latitude, p.longitude]).setRadius(p.shelter_radius_m);
      map.flyTo([p.latitude, p.longitude], zoomFor(p), { duration: 1.2 });
      container.setAttribute("aria-label", `Map of the area around the shelter in ${p.label}`);
    });
  });
})();
