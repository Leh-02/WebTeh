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

  // ---------------- Desktop catalogue hierarchy ----------------
  // Keep one root category active while the pointer moves into the second
  // pane. This avoids the disappearing-menu problem caused by hover gaps and
  // makes the hierarchy easier to scan.
  const desktopCatalog = document.querySelector("[data-desktop-catalog]");
  if (desktopCatalog) {
    const roots = [...desktopCatalog.querySelectorAll("[data-catalog-root]")];
    const panels = [...desktopCatalog.querySelectorAll("[data-catalog-panel]")];
    const activateCatalogRoot = index => {
      roots.forEach((item, i) => item.classList.toggle("active", i === index));
      panels.forEach((panel, i) => panel.classList.toggle("active", i === index));
    };
    roots.forEach((root, index) => {
      root.addEventListener("pointerenter", () => activateCatalogRoot(index));
      root.addEventListener("focusin", () => activateCatalogRoot(index));
    });
    if (roots.length) activateCatalogRoot(0);
  }

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

  function syncCatalogGroups({ clearHidden = false } = {}) {
    if (!filterForm) return;
    const select = filterForm.querySelector("[data-category-filter]");
    const kind = select?.selectedOptions?.[0]?.dataset?.kind || "";
    filterForm.querySelectorAll("[data-filter-group]").forEach(group => {
      const active = Boolean(kind) && group.dataset.filterGroup === kind;
      group.classList.toggle("hidden", !active);
      group.querySelectorAll("input, select").forEach(control => {
        if (!(control instanceof HTMLInputElement || control instanceof HTMLSelectElement)) return;
        control.disabled = !active;
        if (clearHidden && !active) control.value = "";
      });
    });
  }

  // Filter values are deliberately NOT submitted while the customer is typing.
  // Category changes only switch the visible parameter group; the request is
  // made by the explicit “Застосувати” button (or Enter in the form).
  const categoryFilter = filterForm?.querySelector("[data-category-filter]");
  const brandFilterWrap = filterForm?.querySelector("[data-brand-filter-wrap]");
  const brandFilter = filterForm?.querySelector("[data-brand-filter]");

  async function refreshBrandOptions(categoryCode) {
    if (!brandFilter || !brandFilterWrap) return;
    const previous = brandFilter.value;
    try {
      const url = new URL("/api/catalog/brands", window.location.origin);
      if (categoryCode) url.searchParams.set("category", categoryCode);
      const response = await fetch(url.toString(), { headers: { Accept: "application/json" }, credentials: "same-origin" });
      if (!response.ok) throw new Error("brands request failed");
      const brands = await response.json();
      brandFilter.replaceChildren(new Option("Усі бренди", ""));
      brands.forEach(brand => brandFilter.add(new Option(brand.name, String(brand.id))));
      if (brands.some(brand => String(brand.id) === previous)) brandFilter.value = previous;
      brandFilterWrap.classList.toggle("hidden", brands.length === 0);
    } catch (_error) {
      // A dependent-filter refresh must never block the main catalogue form.
    }
  }

  categoryFilter?.addEventListener("change", () => {
    syncCatalogGroups({ clearHidden: true });
    refreshBrandOptions(categoryFilter.value);
  });
  syncCatalogGroups();

  document.querySelectorAll("[data-sort-select]").forEach(select => {
    select.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("sort", select.value);
      url.searchParams.delete("page");
      window.location.assign(url.toString());
    });
  });

  document.querySelectorAll("[data-per-page-select]").forEach(select => {
    select.addEventListener("change", () => {
      const url = new URL(window.location.href);
      url.searchParams.set("per_page", select.value);
      url.searchParams.delete("page");
      window.location.assign(url.toString());
    });
  });

  // ---------------- Cart: instant totals + debounced persistence ----------------
  const cartPage = document.querySelector("[data-cart-page]");
  if (cartPage) {
    const csrf = cartPage.dataset.csrfToken || "";
    const saveStatus = cartPage.querySelector("[data-cart-save-status]");
    const timers = new Map();
    const requests = new Map();

    const moneyText = value => `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(Number(value || 0))} грн`;

    function clampQty(value) {
      const parsed = Number.parseInt(String(value), 10);
      if (!Number.isFinite(parsed)) return 1;
      return Math.max(1, Math.min(999, parsed));
    }

    function recalcCart() {
      let subtotal = 0;
      cartPage.querySelectorAll("[data-cart-item]").forEach(item => {
        const input = item.querySelector("[data-cart-qty]");
        const qty = clampQty(input?.value || 1);
        if (input) input.value = String(qty);
        const unitPrice = Number(item.dataset.unitPrice || 0);
        const lineTotal = unitPrice * qty;
        subtotal += lineTotal;
        const line = item.querySelector("[data-line-total]");
        if (line) line.textContent = moneyText(lineTotal);
      });
      cartPage.querySelectorAll("[data-cart-subtotal], [data-cart-total]").forEach(el => { el.textContent = moneyText(subtotal); });
      return subtotal;
    }

    async function persistItem(item) {
      const productId = item.dataset.productId;
      const input = item.querySelector("[data-cart-qty]");
      if (!productId || !input) return;
      const qty = clampQty(input.value);
      input.value = String(qty);
      const body = new FormData();
      body.set("csrf_token", csrf);
      body.set("qty", String(qty));
      if (saveStatus) saveStatus.textContent = "Зберігаємо зміни…";
      const previousRequest = requests.get(productId);
      previousRequest?.abort();
      const controller = new AbortController();
      requests.set(productId, controller);
      try {
        const response = await fetch(`/cart/item/${encodeURIComponent(productId)}`, {
          method: "POST",
          body,
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: controller.signal
        });
        if (!response.ok) throw new Error("cart update failed");
        const data = await response.json();
        input.value = String(data.qty);
        const line = item.querySelector("[data-line-total]");
        if (line) line.textContent = moneyText(data.line_total);
        cartPage.querySelectorAll("[data-cart-subtotal], [data-cart-total]").forEach(el => { el.textContent = moneyText(data.subtotal); });
        document.querySelectorAll("[data-cart-count]").forEach(el => { el.textContent = String(data.cart_count); });
        if (saveStatus) saveStatus.textContent = "Кошик оновлено.";
      } catch (error) {
        if (error?.name === "AbortError") return;
        if (saveStatus) saveStatus.textContent = "Не вдалося зберегти кількість. Оновіть сторінку та спробуйте ще раз.";
      } finally {
        if (requests.get(productId) === controller) requests.delete(productId);
      }
    }

    function schedulePersist(item, delay = 350) {
      const productId = item.dataset.productId;
      if (!productId) return;
      window.clearTimeout(timers.get(productId));
      timers.set(productId, window.setTimeout(() => persistItem(item), delay));
    }

    cartPage.querySelectorAll("[data-cart-item]").forEach(item => {
      const input = item.querySelector("[data-cart-qty]");
      item.querySelector("[data-qty-minus]")?.addEventListener("click", () => {
        if (!input) return;
        input.value = String(Math.max(1, clampQty(input.value) - 1));
        recalcCart();
        schedulePersist(item, 0);
      });
      item.querySelector("[data-qty-plus]")?.addEventListener("click", () => {
        if (!input) return;
        input.value = String(Math.min(999, clampQty(input.value) + 1));
        recalcCart();
        schedulePersist(item, 0);
      });
      input?.addEventListener("input", () => {
        recalcCart();
        schedulePersist(item, 450);
      });
      input?.addEventListener("change", () => {
        recalcCart();
        schedulePersist(item, 0);
      });
      item.querySelector("[data-cart-qty-form]")?.addEventListener("submit", event => {
        event.preventDefault();
        recalcCart();
        schedulePersist(item, 0);
      });
    });
    recalcCart();
  }

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
        brandInput.required = false;
        brandInput.placeholder = "Необов’язково, наприклад FAG";
      }
      if (brandRequiredMark) brandRequiredMark.classList.add("hidden");
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

  // ---------------- Admin category form ----------------
  const categoryForm = document.querySelector("[data-category-admin-form]");
  if (categoryForm) {
    const parentSelect = categoryForm.querySelector("[data-category-parent]");
    const typeSelect = categoryForm.querySelector("[data-category-product-type]");
    const inheritedHint = categoryForm.querySelector("[data-category-type-hint]");
    function syncCategoryType() {
      const option = parentSelect?.selectedOptions?.[0];
      const inherited = option?.dataset?.productType || "";
      if (inherited && typeSelect) typeSelect.value = inherited;
      if (inheritedHint) inheritedHint.hidden = !inherited;
    }
    parentSelect?.addEventListener("change", syncCategoryType);
    syncCategoryType();
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
              ${(product.brand || product.origin) ? `<span class="product-brand">${escapeHtml(product.brand || product.origin)}</span>` : `<span></span>`}
              <button class="favorite-btn active" type="button" data-favorite-button data-product-id="${Number(product.id)}" aria-label="Прибрати з обраного">♥</button>
            </div>
            <a class="product-card-title" href="${escapeHtml(product.url)}">${escapeHtml(product.name)}</a>
            ${product.size_label ? `<div class="product-code">Розмір: ${escapeHtml(product.size_label)}</div>` : ""}
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
