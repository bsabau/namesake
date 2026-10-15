// Working page: follow the run's server-sent events and show each step as it lands.
// On "done", go to the result. The steps rendered by the server are replaced, since
// the stream replays every step from the start.

(function () {
  const root = document.querySelector('[data-role="working"]');
  if (!root || typeof EventSource === "undefined") return;
  const list = root.querySelector('[data-role="steps"]');
  const status = root.querySelector('[data-role="status"]');
  const source = new EventSource(root.dataset.eventsUrl);
  let first = true;

  source.addEventListener("step", (event) => {
    if (first) { list.innerHTML = ""; first = false; }
    const step = JSON.parse(event.data);
    const item = document.createElement("li");
    item.className = `step step-${step.kind}`;
    item.textContent = step.text;
    list.appendChild(item);
  });

  source.addEventListener("done", (event) => {
    source.close();
    const outcome = JSON.parse(event.data);
    if (outcome.failed) {
      status.textContent = "The run stopped before it finished. The steps above show where.";
      return;
    }
    status.textContent = "Finished. Opening the result…";
    setTimeout(() => { window.location.href = root.dataset.resultUrl; }, 800);
  });

  source.onerror = () => {
    status.textContent = "Lost the connection to the run. Reload to catch up.";
    source.close();
  };
})();
