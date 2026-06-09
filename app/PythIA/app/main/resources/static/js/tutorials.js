(() => {
  const startButtonId = "pythia-tour-start";
  const floatingButtonId = "pythia-tour-fab";
  let activeDriver = null;

  function t(key, params) {
    try {
      return window.pythiaTranslate ? window.pythiaTranslate(key, params) : key;
    } catch {
      return key;
    }
  }

  function getEndpoint() {
    return document.body?.dataset?.endpoint || "";
  }

  function isAdmin() {
    return document.body?.dataset?.isAdmin === "1";
  }

  function elementExists(selector) {
    try {
      return Boolean(document.querySelector(selector));
    } catch {
      return false;
    }
  }

  function showToast(message, variant = "warning") {
    const container = document.getElementById("pythia-toast-container");
    if (!container) return;

    const toastEl = document.createElement("div");
    toastEl.className = `toast align-items-center text-bg-${variant} border-0`;
    toastEl.setAttribute("role", "alert");
    toastEl.setAttribute("aria-live", "assertive");
    toastEl.setAttribute("aria-atomic", "true");

    toastEl.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${String(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="${t("common.close")}"></button>
      </div>
    `;

    container.appendChild(toastEl);
    const toast = window.bootstrap?.Toast ? window.bootstrap.Toast.getOrCreateInstance(toastEl, { delay: 5000 }) : null;
    toast?.show();
    if (!toast) {
      toastEl.classList.add("show");
      setTimeout(() => toastEl.remove(), 5500);
    }
  }

  function stepWithScroll(step) {
    return {
      ...step,
      onHighlightStarted: () => {
        try {
          const el = document.querySelector(step.element);
          el?.scrollIntoView?.({ block: "center", inline: "nearest", behavior: "instant" });
        } catch {
          // noop
        }
      },
    };
  }

  function showTab(tabButtonSelector) {
    const tabBtn = document.querySelector(tabButtonSelector);
    if (!tabBtn) return;
    try {
      if (window.bootstrap?.Tab) {
        window.bootstrap.Tab.getOrCreateInstance(tabBtn).show();
      } else {
        tabBtn.click();
      }
    } catch {
      // noop
    }
  }

  function stepWithTab(step, tabButtonSelector) {
    return {
      ...stepWithScroll(step),
      onHighlightStarted: () => {
        showTab(tabButtonSelector);
        try {
          const el = document.querySelector(step.element);
          el?.scrollIntoView?.({ block: "center", inline: "nearest", behavior: "instant" });
        } catch {
          // noop
        }
      },
    };
  }

  function ensureCollapseShown(collapseId, toggleSelector) {
    const collapseEl = document.getElementById(collapseId);
    if (!collapseEl) return;
    if (collapseEl.classList.contains("show")) return;

    try {
      const instance = window.bootstrap?.Collapse?.getOrCreateInstance(collapseEl, { toggle: false });
      instance?.show();
      return;
    } catch {
      // noop
    }

    try {
      const toggle = toggleSelector ? document.querySelector(toggleSelector) : null;
      toggle?.click?.();
    } catch {
      // noop
    }
  }

  function moveNextFromPopoverArgs(maybeOptions) {
    const driver =
      (maybeOptions && typeof maybeOptions.moveNext === "function" && maybeOptions) ||
      (maybeOptions && maybeOptions.driver && typeof maybeOptions.driver.moveNext === "function" && maybeOptions.driver) ||
      null;
    driver?.moveNext?.();
  }

  function advanceTour(...args) {
    const candidates = [];
    if (activeDriver && typeof activeDriver.moveNext === "function") candidates.push(activeDriver);
    for (const arg of args) {
      if (arg && typeof arg.moveNext === "function") candidates.push(arg);
      if (arg && arg.driver && typeof arg.driver.moveNext === "function") candidates.push(arg.driver);
    }

    const unique = Array.from(new Set(candidates));
    for (const candidate of unique) {
      try {
        candidate.moveNext();
        return;
      } catch {
        // keep trying
      }
    }

    try {
      document.querySelector(".driver-popover-next-btn")?.click?.();
    } catch {
      // noop
    }
  }

  function advanceAfterUiUpdate(...args) {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        setTimeout(() => advanceTour(...args), 120);
      });
    });
  }

  function buildMenuSteps() {
    const steps = [
      {
        element: `#${startButtonId}`,
        popover: { title: t("tutorial.start.title"), description: t("tutorial.start.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-home",
        popover: { title: t("tutorial.nav.home.title"), description: t("tutorial.nav.home.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-history",
        popover: { title: t("tutorial.nav.history.title"), description: t("tutorial.nav.history.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-profile",
        popover: { title: t("tutorial.nav.profile.title"), description: t("tutorial.nav.profile.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-stats",
        popover: { title: t("tutorial.nav.stats.title"), description: t("tutorial.nav.stats.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-docs",
        popover: { title: t("tutorial.nav.docs.title"), description: t("tutorial.nav.docs.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-users",
        popover: { title: t("tutorial.nav.users.title"), description: t("tutorial.nav.users.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-theme",
        popover: { title: t("tutorial.nav.theme.title"), description: t("tutorial.nav.theme.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-i18n",
        popover: { title: t("tutorial.nav.i18n.title"), description: t("tutorial.nav.i18n.desc"), side: "left", align: "start" },
      },
      {
        element: "#nav-logout",
        popover: { title: t("tutorial.nav.logout.title"), description: t("tutorial.nav.logout.desc"), side: "left", align: "start" },
      },
    ];

    return steps.filter((step) => elementExists(step.element));
  }

  function buildPageSteps(endpoint) {
    const perPage = {
      "main.historial": [
        {
          element: "#history-filter-toggle",
          popover: {
            title: t("tutorial.history.filter.title"),
            description: t("tutorial.history.filter.desc"),
            side: "bottom",
            align: "start",
            onNextClick: (_el, _step, options) => {
              ensureCollapseShown("historyFilterCollapse", "#history-filter-toggle");
              advanceAfterUiUpdate(options);
            },
          },
        },
        {
          element: "#history-filter-apply",
          popover: { title: t("tutorial.history.apply.title"), description: t("tutorial.history.apply.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#history-bulk-delete",
          popover: { title: t("tutorial.history.delete.title"), description: t("tutorial.history.delete.desc"), side: "bottom", align: "start" },
        },
      ],
      "main.stats_page": [
        {
          element: "#stats_usage_scope",
          popover: {
            title: t("tutorial.stats.user_vs_global.title"),
            description: isAdmin()
              ? t("tutorial.stats.user_vs_global.desc_admin")
              : t("tutorial.stats.user_vs_global.desc_user"),
            side: "bottom",
            align: "start",
          },
        },
        {
          element: "#chart-monthly-bars",
          popover: { title: t("tutorial.stats.chart_monthly.title"), description: t("tutorial.stats.chart_monthly.desc"), side: "top", align: "start" },
        },
        {
          element: "#chart-monthly-calendar",
          popover: { title: t("tutorial.stats.chart_calendar.title"), description: t("tutorial.stats.chart_calendar.desc"), side: "top", align: "start" },
        },
        {
          element: "#chart-monthly-avg-time",
          popover: { title: t("tutorial.stats.chart_avg_time.title"), description: t("tutorial.stats.chart_avg_time.desc"), side: "top", align: "start" },
        },
        {
          element: "#chart-weekdays",
          popover: { title: t("tutorial.stats.chart_weekdays.title"), description: t("tutorial.stats.chart_weekdays.desc"), side: "top", align: "start" },
        },
        {
          element: "#chart-hours",
          popover: { title: t("tutorial.stats.chart_hours.title"), description: t("tutorial.stats.chart_hours.desc"), side: "top", align: "start" },
        },
        {
          element: "#stats-hours-heatmap",
          popover: { title: t("tutorial.stats.chart_hours_heatmap.title"), description: t("tutorial.stats.chart_hours_heatmap.desc"), side: "top", align: "start" },
        },
        {
          element: "#chart-user-comparison",
          popover: { title: t("tutorial.stats.chart_user_compare.title"), description: t("tutorial.stats.chart_user_compare.desc"), side: "top", align: "start" },
        },
        {
          element: "#stats-comparison-apply",
          popover: { title: t("tutorial.stats.compare.title"), description: t("tutorial.stats.compare.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#chart-user-locations",
          popover: { title: t("tutorial.stats.chart_locations.title"), description: t("tutorial.stats.chart_locations.desc"), side: "top", align: "start" },
        },
      ],
      "main.edit_user": [
        {
          element: "#profile-save",
          popover: { title: t("tutorial.profile.save.title"), description: t("tutorial.profile.save.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#profile-delete-account",
          popover: { title: t("tutorial.profile.delete.title"), description: t("tutorial.profile.delete.desc"), side: "bottom", align: "start" },
        },
      ],
      "rag.rag_page": [
        {
          element: "#rag-model-selector",
          popover: { title: t("tutorial.rag.models.title"), description: t("tutorial.rag.models.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#rag-compare-models",
          popover: { title: t("tutorial.rag.compare.title"), description: t("tutorial.rag.compare.desc"), side: "bottom", align: "start" },
        },
        stepWithScroll({
          element: "#rag-chat-tab",
          popover: {
            title: t("tutorial.rag.chat_tab.title"),
            description: t("tutorial.rag.chat_tab.desc"),
            side: "bottom",
            align: "start",
            onNextClick: (_el, _step, options) => {
              showTab("#rag-chat-tab");
              advanceAfterUiUpdate(options);
            },
          },
        }),
        stepWithTab({
          element: "#rag-chat-form",
          popover: { title: t("tutorial.rag.chat.title"), description: t("tutorial.rag.chat.desc"), side: "top", align: "start" },
        }, "#rag-chat-tab"),
        stepWithTab({
          element: "#rag-chat-ask",
          popover: { title: t("tutorial.rag.ask.title"), description: t("tutorial.rag.chat.ask.desc"), side: "top", align: "start" },
        }, "#rag-chat-tab"),
        stepWithTab({
          element: "#rag-chat-pane .rag-answer-box",
          popover: { title: t("tutorial.rag.answer.title"), description: t("tutorial.rag.chat.answer.desc"), side: "top", align: "start" },
        }, "#rag-chat-tab"),
        stepWithTab({
          element: "#rag-chat-pane .rag-chunk",
          popover: { title: t("tutorial.rag.fragments.title"), description: t("tutorial.rag.chat.fragments.desc"), side: "top", align: "start" },
        }, "#rag-chat-tab"),
        stepWithTab({
          element: "#rag-view-all-fragments-chat",
          popover: { title: t("tutorial.rag.view_all.title"), description: t("tutorial.rag.view_all.desc"), side: "left", align: "start" },
        }, "#rag-chat-tab"),

        stepWithScroll({
          element: "#rag-form-tab",
          popover: {
            title: t("tutorial.rag.form_tab.title"),
            description: t("tutorial.rag.form_tab.desc"),
            side: "bottom",
            align: "start",
            onNextClick: (_el, _step, options) => {
              showTab("#rag-form-tab");
              advanceAfterUiUpdate(options);
            },
          },
        }),
        stepWithTab({
          element: "#rag-default-form",
          popover: { title: t("tutorial.rag.guided_form.title"), description: t("tutorial.rag.guided_form.desc"), side: "top", align: "start" },
        }, "#rag-form-tab"),
        stepWithTab({
          element: "#ask-button",
          popover: { title: t("tutorial.rag.ask.title"), description: t("tutorial.rag.form.ask.desc"), side: "top", align: "start" },
        }, "#rag-form-tab"),
        stepWithTab({
          element: "#rag-form-pane .rag-answer-box",
          popover: { title: t("tutorial.rag.answer.title"), description: t("tutorial.rag.form.answer.desc"), side: "top", align: "start" },
        }, "#rag-form-tab"),
        stepWithTab({
          element: "#rag-form-pane .rag-chunk",
          popover: { title: t("tutorial.rag.fragments.title"), description: t("tutorial.rag.form.fragments.desc"), side: "top", align: "start" },
        }, "#rag-form-tab"),
        stepWithTab({
          element: "#rag-view-all-fragments-form",
          popover: { title: t("tutorial.rag.view_all.title"), description: t("tutorial.rag.view_all.desc"), side: "left", align: "start" },
        }, "#rag-form-tab"),
      ],
      "rag.model_comparison_page": [
        {
          element: "#model-stats-back",
          popover: { title: t("tutorial.model_stats.back.title"), description: t("tutorial.model_stats.back.desc"), side: "bottom", align: "start" },
        },
      ],
      "admin.documents_list_page": [
        {
          element: "#docs-choose-files",
          popover: { title: t("tutorial.docs.choose.title"), description: t("tutorial.docs.choose.desc"), side: "right", align: "start" },
        },
        {
          element: "#docs-upload-button",
          popover: { title: t("tutorial.docs.upload.title"), description: t("tutorial.docs.upload.desc"), side: "right", align: "start" },
        },
        {
          element: "#docs-scraping-button",
          popover: { title: t("tutorial.docs.scraping.title"), description: t("tutorial.docs.scraping.desc"), side: "right", align: "start" },
        },
        {
          element: "#docs-markdown-button",
          popover: { title: t("tutorial.docs.markdown.title"), description: t("tutorial.docs.markdown.desc"), side: "right", align: "start" },
        },
        {
          element: "#docs-vector-button",
          popover: { title: t("tutorial.docs.vector.title"), description: t("tutorial.docs.vector.desc"), side: "right", align: "start" },
        },
        {
          element: "#docs-filter-toggle",
          popover: {
            title: t("tutorial.docs.filter.title"),
            description: t("tutorial.docs.filter.desc"),
            side: "bottom",
            align: "start",
            onNextClick: (_el, _step, options) => {
              ensureCollapseShown("documentsFilterCollapse", "#docs-filter-toggle");
              advanceAfterUiUpdate(options);
            },
          },
        },
        {
          element: "#docs-filter-apply",
          popover: { title: t("tutorial.docs.apply.title"), description: t("tutorial.docs.apply.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#docs-bulk-delete",
          popover: { title: t("tutorial.docs.delete.title"), description: t("tutorial.docs.delete.desc"), side: "bottom", align: "start" },
        },
      ],
      "admin.users": [
        {
          element: "#users-filter-toggle",
          popover: {
            title: t("tutorial.users.filter.title"),
            description: t("tutorial.users.filter.desc"),
            side: "bottom",
            align: "start",
            onNextClick: (_el, _step, options) => {
              ensureCollapseShown("usersFilterCollapse", "#users-filter-toggle");
              advanceAfterUiUpdate(options);
            },
          },
        },
        {
          element: "#users-filter-apply",
          popover: { title: t("tutorial.users.apply.title"), description: t("tutorial.users.apply.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#users-bulk-toggle",
          popover: { title: t("tutorial.users.bulk_toggle.title"), description: t("tutorial.users.bulk_toggle.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#users-bulk-delete",
          popover: { title: t("tutorial.users.bulk_delete.title"), description: t("tutorial.users.bulk_delete.desc"), side: "bottom", align: "start" },
        },
      ],
      "auth.login": [
        {
          element: "#auth-login-email",
          popover: { title: t("tutorial.auth.email.title"), description: t("tutorial.auth.login.email.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-login-password",
          popover: { title: t("tutorial.auth.password.title"), description: t("tutorial.auth.login.password.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-login-submit",
          popover: { title: t("tutorial.auth.submit.title"), description: t("tutorial.auth.login.submit.desc"), side: "top", align: "start" },
        },
      ],
      "auth.singup": [
        {
          element: "#auth-signup-name",
          popover: { title: t("tutorial.auth.name.title"), description: t("tutorial.auth.signup.name.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-signup-email",
          popover: { title: t("tutorial.auth.email.title"), description: t("tutorial.auth.signup.email.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-signup-country",
          popover: { title: t("tutorial.auth.country.title"), description: t("tutorial.auth.signup.country.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-signup-password",
          popover: { title: t("tutorial.auth.password.title"), description: t("tutorial.auth.signup.password.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-signup-confirm-password",
          popover: { title: t("tutorial.auth.confirm_password.title"), description: t("tutorial.auth.signup.confirm_password.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-signup-submit",
          popover: { title: t("tutorial.auth.submit.title"), description: t("tutorial.auth.signup.submit.desc"), side: "top", align: "start" },
        },
      ],
      "auth.forgot_password": [
        {
          element: "#auth-forgot-email",
          popover: { title: t("tutorial.auth.email.title"), description: t("tutorial.auth.forgot.email.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-forgot-submit",
          popover: { title: t("tutorial.auth.submit.title"), description: t("tutorial.auth.forgot.submit.desc"), side: "top", align: "start" },
        },
      ],
      "auth.reset_password": [
        {
          element: "#auth-reset-password",
          popover: { title: t("tutorial.auth.new_password.title"), description: t("tutorial.auth.reset.password.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-reset-confirm-password",
          popover: { title: t("tutorial.auth.confirm_password.title"), description: t("tutorial.auth.reset.confirm_password.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#auth-reset-submit",
          popover: { title: t("tutorial.auth.submit.title"), description: t("tutorial.auth.reset.submit.desc"), side: "top", align: "start" },
        },
      ],
    };

    const steps = [];

    // Header steps should be available on every page tutorial.
    if (endpoint !== "main.pag_principal") {
      steps.push({
        element: "#nav-logo-home",
        popover: { title: t("tutorial.home.logo.title"), description: t("tutorial.home.logo.desc"), side: "bottom", align: "start" },
      });
    }

    steps.push({
      element: "#nav-open-menu",
      popover: { title: t("tutorial.home.menu.title"), description: t("tutorial.home.menu.desc"), side: "bottom", align: "start" },
    });

    if (perPage[endpoint]) {
      const perPageSteps = [...perPage[endpoint]];
      if (endpoint === "main.stats_page" && isAdmin()) {
        perPageSteps.push({
          element: "#chart-top-users",
          popover: { title: t("tutorial.stats.ranking.title"), description: t("tutorial.stats.ranking.desc"), side: "top", align: "start" },
        });
      }
      steps.push(...perPageSteps);
    }

    if (endpoint === "main.pag_principal") {
      const homeSteps = [
        {
          element: "#home-rag-card",
          popover: { title: t("tutorial.home.rag.title"), description: t("tutorial.home.rag.desc"), side: "bottom", align: "start" },
        },
        {
          element: "#homeCalendarChart",
          popover: { title: t("tutorial.home.charts.title"), description: t("tutorial.home.charts.desc"), side: "top", align: "start" },
        },
        {
          element: "#home-full-history",
          popover: { title: t("tutorial.home.history_link.title"), description: t("tutorial.home.history_link.desc"), side: "top", align: "start" },
        },
      ];

      steps.push(...homeSteps);
      return steps.filter((step) => elementExists(step.element));
    }

    return steps.filter((step) => elementExists(step.element));
  }

  function startTour(options = {}) {
    const { includeMenu = true } = options;
    const createDriver =
      (window.driver && window.driver.js && typeof window.driver.js.driver === "function" && window.driver.js.driver) ||
      (window.driverjs && typeof window.driverjs.driver === "function" && window.driverjs.driver) ||
      (typeof window.driver === "function" && window.driver) ||
      (typeof window.Driver === "function" && window.Driver) ||
      null;
    if (!createDriver) {
      console.warn(t("tutorial.error.no_driver"));
      showToast(t("tutorial.error.no_driver"), "danger");
      return;
    }

    const endpoint = getEndpoint();
    const steps = includeMenu ? buildMenuSteps() : buildPageSteps(endpoint);
    if (!steps.length) {
      showToast(t("tutorial.error.no_steps"), "warning");
      return;
    }

    const driver = createDriver({
      showProgress: true,
      allowClose: true,
      animate: true,
      steps,
      nextBtnText: t("tutorial.next"),
      prevBtnText: t("tutorial.prev"),
      doneBtnText: t("tutorial.done"),
      progressText: t("tutorial.progress"),
    });

    activeDriver = driver;
    driver.drive();
  }

  function wireButton() {
    const btn = document.getElementById(startButtonId);
    if (!btn) return;
    btn.addEventListener("click", () => {
      startTour({ includeMenu: true });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    wireButton();
    const fab = document.getElementById(floatingButtonId);
    if (fab) {
      try {
        window.bootstrap?.Tooltip?.getOrCreateInstance(fab);
      } catch {
        // noop
      }
      fab.addEventListener("click", () => startTour({ includeMenu: false }));
    }
  });
})();
