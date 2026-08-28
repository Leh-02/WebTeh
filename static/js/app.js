(() => {
  "use strict";

  const body = document.body;

  // ---------------- Mobile hamburger menu ----------------
  const menu = document.querySelector("[data-mobile-menu]");
  const menuBackdrop = document.querySelector("[data-menu-backdrop]");
  function setMenu(open) {
    if (!menu) return;
    menu.classList.toggle("open", open);
    menu.setAttribute("aria-hidden", String(!open));
    if (menuBackdrop) {
      menuBackdrop.hidden = !open;
      menuBackdrop.classList.toggle("visible", open);
    }
    body.classList.toggle("no-scroll", open || Boolean(document.querySelector("[data-filter-panel].open")));
  }
  document.querySelector("[data-menu-open]")?.addEventListener("click", () => setMenu(true));
  document.querySelector("[data-menu-close]")?.addEventListener("click", () => setMenu(false));
  menuBackdrop?.addEventListener("click", () => setMenu(false));

  // ---------------- Catalog filter drawer + sticky bar ----------------
  const filterPanel = document.querySelector("[data-filter-panel]");
  const filterBackdrop = document.querySelector("[data-filter-backdrop]");
  function setFilter(open) {
    if (!filterPanel) return;
    filterPanel.classList.toggle("open", open);
    if (filterBackdrop) {
      filterBackdrop.hidden = !open;
      filterBackdrop.classList.toggle("visible", open);
    }
    body.classList.toggle("no-scroll", open || Boolean(menu?.classList.contains("open")));
  }
  document.querySelector("[data-filter-open]")?.addEventListener("click", () => setFilter(true));
  document.querySelector("[data-filter-close]")?.addEventListener("click", () => setFilter(false));
  filterBackdrop?.addEventListener("click", () => setFilter(false));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") { setMenu(false); setFilter(false); }
  });

  const filterForm = document.querySelector("[data-filter-form]");
  function syncCatalogGroups() {
    if (!filterForm) return;
    const select = filterForm.querySelector("[data-category-filter]");
    const kind = select?.selectedOptions?.[0]?.dataset?.kind || "";
    filterForm.querySelectorAll("[data-filter-group]").forEach(group => {
      group.classList.toggle("hidden", !kind || group.dataset.filterGroup !== kind);
    });
  }
  filterForm?.querySelector("[data-category-filter]")?.addEventListener("change", syncCatalogGroups);
  syncCatalogGroups();

  document.querySelectorAll("[data-sort-select]").forEach(select => {
    select.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("sort", select.value);
      url.searchParams.delete("page");
      window.location.assign(url.toString());
    });
  });

  // ---------------- Admin product form ----------------
  const productForm = document.querySelector("[data-product-admin-form]");
  if (productForm) {
    const categorySelect = productForm.querySelector("[data-admin-category]");
    const brandInput = productForm.querySelector("input[name=brand_name]");
    const brandRequiredMark = productForm.querySelector("[data-brand-required]");
    const description = productForm.querySelector("textarea[name=description]");
    const descriptionHint = productForm.querySelector("[data-description-hint]");
    const stockTracked = productForm.querySelector("[data-stock-tracked]");
    const stockQtyWrap = productForm.querySelector("[data-stock-qty]");
    const stockStatusWrap = productForm.querySelector("[data-stock-status]");

    const requiredByKind = {
      bearings: ["inner_diameter_mm", "outer_diameter_mm", "width_mm"],
      belts: ["profile", "length_mm"],
      seals: ["seal_inner_diameter_mm", "seal_outer_diameter_mm", "seal_width_mm"],
      lubricants: ["lubricant_type", "package_size", "description"],
      accessories: ["description"]
    };

    function currentKind() {
      return categorySelect?.selectedOptions?.[0]?.dataset?.kind || "";
    }
    function syncCategory() {
      const kind = currentKind();
      productForm.querySelectorAll("[data-category-section]").forEach(section => {
        section.classList.toggle("hidden", section.dataset.categorySection !== kind);
      });
      productForm.querySelectorAll("input, textarea, select").forEach(el => {
        if (el.dataset.baseRequired !== undefined) el.required = el.dataset.baseRequired === "1";
      });
      (requiredByKind[kind] || []).forEach(name => {
        const input = productForm.querySelector(`[name="${name}"]`);
        if (input) input.required = true;
      });
      if (brandInput) {
        brandInput.required = kind !== "accessories";
        brandInput.placeholder = kind === "accessories" ? "Необов’язково" : "Наприклад FAG";
      }
      if (brandRequiredMark) brandRequiredMark.classList.toggle("hidden", kind === "accessories");
      if (descriptionHint) {
        descriptionHint.textContent = (kind === "lubricants" || kind === "accessories")
          ? "— обов’язковий для цієї категорії"
          : "— необов’язковий; характеристики важливіші";
      }
      if (description) description.required = kind === "lubricants" || kind === "accessories";
    }
    // Mark the statically required common fields so category changes do not unset them.
    productForm.querySelectorAll("input[required], textarea[required], select[required]").forEach(el => el.dataset.baseRequired = "1");

    function syncStock() {
      const tracked = Boolean(stockTracked?.checked);
      stockQtyWrap?.classList.toggle("hidden", !tracked);
      stockStatusWrap?.classList.toggle("hidden", tracked);
      const qtyInput = stockQtyWrap?.querySelector("input");
      const statusSelect = stockStatusWrap?.querySelector("select");
      if (qtyInput) qtyInput.required = tracked;
      if (statusSelect) statusSelect.required = !tracked;
    }
    categorySelect?.addEventListener("change", syncCategory);
    stockTracked?.addEventListener("change", syncStock);
    syncCategory();
    syncStock();
  }

  // ---------------- Product image gallery ----------------
  const mainImageBox = document.querySelector("[data-gallery-main]");
  document.querySelectorAll("[data-gallery-thumb]").forEach(button => {
    button.addEventListener("click", () => {
      const src = button.dataset.src;
      const mainImage = mainImageBox?.querySelector("img");
      if (src && mainImage) mainImage.src = src;
      document.querySelectorAll("[data-gallery-thumb]").forEach(x => x.classList.remove("active"));
      button.classList.add("active");
    });
  });

  // ---------------- Checkout delivery form ----------------
  const checkout = document.querySelector("[data-checkout-form]");
  if (checkout) {
    function syncDelivery() {
      const selected = checkout.querySelector("input[name=delivery_service]:checked")?.value || "nova_poshta";
      const common = checkout.querySelector("[data-delivery-common]");
      const np = checkout.querySelector("[data-delivery-np]");
      const ukr = checkout.querySelectorAll("[data-delivery-ukr]");
      const cityInput = common?.querySelector("input");
      const npInput = np?.querySelector("input");
      common?.classList.toggle("hidden", selected === "pickup");
      np?.classList.toggle("hidden", selected !== "nova_poshta");
      ukr.forEach(el => el.classList.toggle("hidden", selected !== "ukrposhta"));
      if (cityInput) cityInput.required = selected !== "pickup";
      if (npInput) npInput.required = selected === "nova_poshta";
      // Ukrposhta accepts either index or branch/address, so backend validates the OR condition.
    }
    checkout.querySelectorAll("input[name=delivery_service]").forEach(radio => radio.addEventListener("change", syncDelivery));
    syncDelivery();
  }

  // ---------------- Favorites: guest-compatible localStorage ----------------
  const FAVORITES_KEY = "topbearing-favorites-v1";
  function readFavorites() {
    try {
      const value = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
      return [...new Set((Array.isArray(value) ? value : []).map(Number).filter(Number.isInteger))];
    } catch (_) { return []; }
  }
  function writeFavorites(ids) {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...new Set(ids)]));
    syncFavoriteButtons();
  }
  function syncFavoriteButtons() {
    const favorites = readFavorites();
    const set = new Set(favorites);
    document.querySelectorAll("[data-favorite-button]").forEach(button => {
      const id = Number(button.dataset.productId);
      const active = set.has(id);
      button.classList.toggle("active", active);
      button.textContent = active ? "♥" : "♡";
      button.setAttribute("aria-pressed", String(active));
      button.setAttribute("aria-label", active ? "Прибрати з обраного" : "Додати в обране");
    });
    document.querySelectorAll("[data-favorites-count]").forEach(el => el.textContent = String(favorites.length));
  }
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-favorite-button]");
    if (!button) return;
    event.preventDefault();
    const id = Number(button.dataset.productId);
    let favorites = readFavorites();
    favorites = favorites.includes(id) ? favorites.filter(x => x !== id) : [...favorites, id];
    writeFavorites(favorites);
    if (document.querySelector("[data-favorites-grid]")) loadFavoritesPage();
  });

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
  }
  function formatMoney(value) {
    return new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(Number(value || 0));
  }
  async function loadFavoritesPage() {
    const grid = document.querySelector("[data-favorites-grid]");
    const empty = document.querySelector("[data-favorites-empty]");
    if (!grid || !empty) return;
    const ids = readFavorites();
    if (!ids.length) {
      grid.innerHTML = "";
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    grid.innerHTML = `<div class="empty-inline">Завантажуємо…</div>`;
    try {
      const response = await fetch(`/api/products/batch?ids=${encodeURIComponent(ids.join(","))}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("HTTP error");
      const products = await response.json();
      if (!products.length) {
        grid.innerHTML = "";
        empty.hidden = false;
        return;
      }
      grid.innerHTML = products.map(product => `
        <article class="product-card" data-product-card data-product-id="${Number(product.id)}">
          <a class="product-card-image" href="${escapeHtml(product.url)}">
            ${product.image ? `<img src="${escapeHtml(product.image)}" alt="${escapeHtml(product.name)}" loading="lazy">` : `<span class="image-placeholder">TB</span>`}
          </a>
          <div class="product-card-body">
            <div class="product-card-topline">
              ${product.brand ? `<span class="product-brand">${escapeHtml(product.brand)}</span>` : `<span></span>`}
              <button class="favorite-btn active" type="button" data-favorite-button data-product-id="${Number(product.id)}" aria-label="Прибрати з обраного">♥</button>
            </div>
            <a class="product-card-title" href="${escapeHtml(product.url)}">${escapeHtml(product.name)}</a>
            ${product.manufacturer_code ? `<div class="product-code">Арт. ${escapeHtml(product.manufacturer_code)}</div>` : ""}
            <div class="availability availability-${escapeHtml(product.availability_code)}">${escapeHtml(product.availability)}</div>
            <div class="product-card-bottom"><strong class="product-price">${formatMoney(product.price)} грн</strong><a class="small-primary" href="${escapeHtml(product.url)}">Переглянути</a></div>
          </div>
        </article>`).join("");
      syncFavoriteButtons();
    } catch (_) {
      grid.innerHTML = `<div class="empty-state"><h2>Не вдалося завантажити обране</h2><p>Оновіть сторінку та спробуйте ще раз.</p></div>`;
    }
  }

  syncFavoriteButtons();
  loadFavoritesPage();
})();
