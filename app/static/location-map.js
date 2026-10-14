// Map of the selected shelter location: Leaflet with OpenStreetMap tiles.
// The preset points come from the page (#map-points); picking a location card
// moves the map there.

(function () {
  const container = document.getElementById("location-map");
  const data = document.getElementById("map-points");
  if (!container || !data || typeof L === "undefined") return;

  const points = JSON.parse(data.textContent);
  const checked = document.querySelector('input[name="location"]:checked');
  const start = points[checked ? checked.value : Object.keys(points)[0]];

  // Narrow maps (phones) zoom out one step so the area still has some context around it.
  const zoomFor = (p) => p.zoom - (container.clientWidth < 500 ? 1 : 0);

  const map = L.map(container, { scrollWheelZoom: false })
    .setView([start.latitude, start.longitude], zoomFor(start));

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  const accent = getComputedStyle(document.documentElement)
    .getPropertyValue("--accent").trim() || "#c2410c";

  // A city is shown wider than a neighbourhood, so the circle grows as the zoom drops.
  const radiusFor = (p) => 800 * 2 ** (14 - p.zoom);

  // A soft circle, not a pin: the shelter is fictional, so we only show an area.
  const area = L.circle([start.latitude, start.longitude], {
    radius: radiusFor(start),
    color: accent,
    weight: 2,
    fillOpacity: 0.15,
  }).addTo(map);

  document.querySelectorAll('input[name="location"]').forEach((input) => {
    input.addEventListener("change", () => {
      const p = points[input.value];
      if (!p) return;
      area.setLatLng([p.latitude, p.longitude]).setRadius(radiusFor(p));
      map.flyTo([p.latitude, p.longitude], zoomFor(p), { duration: 1.2 });
      container.setAttribute("aria-label", `Map of the area around the shelter in ${p.label}`);
    });
  });
})();
