(() => {
  const cityInput = document.querySelector("[data-np-city]");
  const warehouseInput = document.querySelector("[data-np-warehouse]");
  const cityList = document.getElementById("np-city-list");
  const warehouseList = document.getElementById("np-warehouse-list");

  if (!cityInput || !warehouseInput || !cityList || !warehouseList) return;

  let timer = null;
  let cityRows = [];

  const clearWarehouses = () => {
    warehouseList.innerHTML = "";
    warehouseInput.dataset.cityRef = "";
  };

  cityInput.addEventListener("input", () => {
    clearTimeout(timer);
    clearWarehouses();

    const query = cityInput.value.trim();
    if (query.length < 2) {
      cityList.innerHTML = "";
      cityRows = [];
      return;
    }

    timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/nova-poshta/cities?q=${encodeURIComponent(query)}`, {
          headers: { Accept: "application/json" },
        });
        if (!response.ok) return;

        cityRows = await response.json();
        cityList.innerHTML = "";

        cityRows.forEach((row) => {
          const option = document.createElement("option");
          option.value = row.name || "";
          option.label = row.region ? `${row.name} — ${row.region}` : (row.name || "");
          cityList.appendChild(option);
        });
      } catch (_) {
        // Manual input remains available if Nova Poshta API is unavailable.
      }
    }, 250);
  });

  cityInput.addEventListener("change", async () => {
    const selected = cityRows.find((row) => row.name === cityInput.value.trim());
    clearWarehouses();
    if (!selected?.ref) return;

    warehouseInput.dataset.cityRef = selected.ref;
    try {
      const response = await fetch(
        `/api/nova-poshta/warehouses?city_ref=${encodeURIComponent(selected.ref)}`,
        { headers: { Accept: "application/json" } }
      );
      if (!response.ok) return;

      const rows = await response.json();
      rows.forEach((row) => {
        const option = document.createElement("option");
        option.value = row.name || row.short_address || "";
        warehouseList.appendChild(option);
      });
    } catch (_) {
      // Keep manual warehouse entry as a safe fallback.
    }
  });
})();
