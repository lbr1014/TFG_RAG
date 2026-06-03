(function () {
  const config = window.PYTHIA_STATS;
  if (!config || typeof d3 === "undefined") {
    return;
  }

  const tooltip = createTooltip();
  const locale = config.locale || "es";
  const usageData = (config.data && config.data.usage) ? config.data.usage : (config.data || {});
  const formatMonth = new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" });
  const formatDateTime = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  const formatDate = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });
  const formatDayShort = new Intl.DateTimeFormat(locale, { day: "2-digit", month: "short" });

  const monthlyState = {
    level: "months",
    month: null,
    week: null,
    day: null,
  };

  const monthlyCalendarState = {
    monthKey: null,
  };

  const hourlyState = {
    view: "bars",
  };

  const avgTimeState = {
    level: "months",
    month: null,
    week: null,
  };

  initBootstrapTooltips();

  setupMonthlyBarsDrilldown();
  setupAvgTimeDrilldown();
  setupHourlyChartToggle();
  setupMonthlyCalendar();
  renderStaticCharts();

  function initBootstrapTooltips() {
    if (!window.bootstrap?.Tooltip) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => {
      window.bootstrap.Tooltip.getOrCreateInstance(el);
    });
  }

  const observedChartWidths = new Map();
  const resizeHandler = debounce((entries) => {
    if (!entries || chartWidthsChanged(entries)) {
      redrawCharts();
    }
  }, 180);
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(resizeHandler);
    document.querySelectorAll(".stats-chart").forEach((container) => {
      observedChartWidths.set(container, chartWidth(container));
      observer.observe(container);
    });
  } else {
    window.addEventListener("resize", () => resizeHandler());
  }

  function clearChartContainer(selector) {
    const container = document.querySelector(selector);
    if (container) {
      container.innerHTML = "";
    }
  }

  function debounce(fn, wait) {
    let timeout = null;
    return (...args) => {
      if (timeout) {
        window.clearTimeout(timeout);
      }
      timeout = window.setTimeout(() => {
        timeout = null;
        fn(...args);
      }, wait);
    };
  }

  function redrawCharts() {
    renderMonthlyBarsChart();
    renderMonthlyCalendar();
    renderHourlyChart();
    renderAvgTimeChart();
    renderStaticCharts();
  }

  function chartWidthsChanged(entries) {
    let changed = false;
    entries.forEach((entry) => {
      const currentWidth = chartWidth(entry.target);
      const previousWidth = observedChartWidths.get(entry.target);
      if (previousWidth === undefined) {
        observedChartWidths.set(entry.target, currentWidth);
        return;
      }

      if (Math.abs(currentWidth - previousWidth) >= 2) {
        observedChartWidths.set(entry.target, currentWidth);
        changed = true;
      }
    });
    return changed;
  }

  function chartWidth(container, fallback) {
    return Math.max(280, Math.round(container.getBoundingClientRect().width || container.clientWidth || fallback || 640));
  }

  function isNarrow(width) {
    return width < 520;
  }

  function compactTickValues(data, key, width, preferredTicks) {
    const ticks = isNarrow(width) ? 4 : preferredTicks;
    return selectTickValues(data, key, ticks);
  }

  function truncateLabel(value, maxLength) {
    const label = String(value || "");
    if (label.length <= maxLength) {
      return label;
    }
    return `${label.slice(0, Math.max(1, maxLength - 3))}...`;
  }

  function renderStaticCharts() {
    clearChartContainer("#chart-weekdays");
    drawDonutChart("#chart-weekdays", usageData.weekday_queries, {
      labelKey: "weekday",
      valueKey: "count",
      colors: ["#58d68d", "#48c9b0", "#5dade2", "#f4d03f", "#eb984e", "#ec7063", "#af7ac5"],
      labelFormatter: (value) => config.labels.weekdays[value] || value,
      tooltipFormatter: (item) =>
        `${config.labels.weekdays[item.weekday] || item.weekday}: ${item.count}`,
    });

    clearChartContainer("#chart-top-users");
    if (Array.isArray(config.data.top_users) && config.data.top_users.length) {
      drawDonutChart("#chart-top-users", config.data.top_users, {
        labelKey: "user",
        valueKey: "count",
        colors: ["#af7ac5", "#5dade2", "#58d68d", "#f5b041", "#ec7063", "#48c9b0", "#eb984e", "#7fb3d5"],
        labelFormatter: (value) => value,
        tooltipFormatter: (item) => `${item.user}: ${item.count}`,
      });
    }

    clearChartContainer("#chart-top-logins");
    if (Array.isArray(config.data.top_logins) && config.data.top_logins.length) {
      drawDonutChart("#chart-top-logins", config.data.top_logins, {
        labelKey: "user",
        valueKey: "count",
        unitLabel: config.labels.unitLogins || "accesos",
        colors: ["#f5b041", "#5dade2", "#58d68d", "#af7ac5", "#ec7063", "#48c9b0", "#7fb3d5", "#eb984e"],
        labelFormatter: (value) => value,
        tooltipFormatter: (item) => `${item.user}: ${item.count}`,
      });
    }

    clearChartContainer("#chart-user-locations");
    if (Array.isArray(config.data.user_locations) && config.data.user_locations.length) {
      drawUserLocationsMap("#chart-user-locations", config.data.user_locations);
    }

    clearChartContainer("#chart-user-comparison");
    if (config.data.user_comparison && Array.isArray(config.data.user_comparison.data) && config.data.user_comparison.data.length) {
      drawUserComparisonChart("#chart-user-comparison", config.data.user_comparison.data, {
        xKey: "user",
        yKey: "count",
        color: "#7fb3d5",
        mean: config.data.user_comparison.stats.mean,
        median: config.data.user_comparison.stats.median,
        variance: config.data.user_comparison.stats.variance,
        meanLabel: config.labels.comparisonMean || "Media",
        medianLabel: config.labels.comparisonMedian || "Mediana",
        varianceLabel: config.labels.comparisonVariance || "Varianza",
        tooltipFormatter: (item) => `${item.user}: ${item.count}`,
        rotateLabels: true,
      });
    }
  }

  const summaryDate = document.querySelector("[data-stats-last-query]");
  if (summaryDate && summaryDate.dataset.value) {
    summaryDate.textContent = formatDateTime.format(new Date(summaryDate.dataset.value));
  }

  function renderHourlyChart() {
    const container = document.querySelector("#chart-hours");
    if (!container) return;
    container.innerHTML = "";

    if (hourlyState.view === "heatmap") {
      drawHeatmapChart("#chart-hours", usageData.hourly_queries, {
        xKey: "hour",
        yKey: "count",
        labelFormatter: (value) => `${String(value).padStart(2, "0")}:00`,
        tooltipFormatter: (item) => `${String(item.hour).padStart(2, "0")}:00 - ${item.count}`,
      });
      return;
    }

    drawBarChart("#chart-hours", usageData.hourly_queries, {
      xKey: "hour",
      yKey: "count",
      color: "#ec7063",
      xFormatter: (value) => `${String(value).padStart(2, "0")}:00`,
      tickValues: selectHourTicks(usageData.hourly_queries, container.clientWidth),
      tooltipFormatter: (item) => `${String(item.hour).padStart(2, "0")}:00 - ${item.count}`,
      rotateLabels: true,
    });
  }

  function setupHourlyChartToggle() {
    const container = document.querySelector("#chart-hours");
    if (!container) return;

    const buttons = Array.from(document.querySelectorAll("[data-hours-view]"));
    const clones = buttons.map((button) => button.cloneNode(true));
    buttons.forEach((button, index) => button.parentNode.replaceChild(clones[index], button));

    const setView = (view) => {
      hourlyState.view = view;
      renderHourlyChart();
      clones.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.hoursView === view);
      });
    };

    clones.forEach((button) => {
      button.addEventListener("click", () => setView(button.dataset.hoursView));
    });

    setView(hourlyState.view);
  }

  function renderMonthlyBarsChart() {
    const container = document.querySelector("#chart-monthly-bars");
    if (!container) return;
    container.innerHTML = "";

    renderDrillHeader(container, monthlyState, {
      rootLabel: config.labels.months || "Meses",
      valueLabel: config.labels.queries || "Consultas",
      onBack: () => {
        monthlyState.level = "months";
        monthlyState.month = null;
        monthlyState.week = null;
        monthlyState.day = null;
        renderMonthlyBarsChart();
      },
    });

    if (monthlyState.level === "hours" && monthlyState.day) {
      drawBarChart("#chart-monthly-bars", hourlyDataForDay(monthlyState.day.date), {
        xKey: "hour",
        yKey: "count",
        color: "#3498db",
        xFormatter: (value) => `${String(value).padStart(2, "0")}:00`,
        tickValues: selectHourTicks(usageData.hourly_queries, container.clientWidth),
        tooltipFormatter: (item) =>
          `${formatDateOnly(monthlyState.day.date)} ${String(item.hour).padStart(2, "0")}:00 - ${item.count}`,
      });
      return;
    }

    if (monthlyState.level === "weeks") {
      const weeklyData = buildWeeklyCountData(usageData.daily_queries, monthlyState.month);
      drawBarChart("#chart-monthly-bars", weeklyData, {
        xKey: "id",
        yKey: "count",
        color: "#5dade2",
        xFormatter: (value, item) => (item ? item.label : value),
        rotateLabels: true,
        tooltipFormatter: (item) => `${item.label}: ${item.count}`,
        onClick: (item) => {
          monthlyState.level = "days";
          monthlyState.week = item;
          renderMonthlyBarsChart();
        },
      });
      return;
    }

    if (monthlyState.level === "days" && monthlyState.week) {
      drawBarChart("#chart-monthly-bars", monthlyState.week.days, {
        xKey: "date",
        yKey: "count",
        color: "#5dade2",
        xFormatter: (value) => formatDayShort.format(new Date(`${value}T00:00:00`)),
        rotateLabels: true,
        tooltipFormatter: (item) => `${formatDateOnly(item.date)}: ${item.count}`,
        onClick: (item) => {
          monthlyState.level = "hours";
          monthlyState.day = item;
          renderMonthlyBarsChart();
        },
      });
      return;
    }

    drawBarChart("#chart-monthly-bars", usageData.monthly_queries, {
      xKey: "month",
      yKey: "count",
      color: "#5dade2",
      xFormatter: (value) => formatMonth.format(new Date(value)),
      tickValues: compactTickValues(usageData.monthly_queries, "month", container.clientWidth, 6),
      rotateLabels: true,
      tooltipFormatter: (item) => `${formatMonth.format(new Date(item.month))}: ${item.count}`,
      onClick: (item) => {
        monthlyState.level = "weeks";
        monthlyState.month = monthKeyFromDate(item.month);
        monthlyCalendarState.monthKey = monthlyState.month;
        renderMonthlyCalendar();
        renderMonthlyBarsChart();
      },
    });
  }

  function setupMonthlyBarsDrilldown() {
    renderMonthlyBarsChart();
  }

  function renderMonthlyCalendar() {
    const container = document.querySelector("#chart-monthly-calendar");
    if (!container) return;
    container.innerHTML = "";

    const monthKey = monthlyCalendarState.monthKey || defaultCalendarMonthKey();
    if (!monthKey) return renderEmptyState(container);

    const header = document.createElement("div");
    header.className = "stats-monthly-calendar-header";

    const prev = document.createElement("button");
    prev.type = "button";
    prev.className = "stats-drill-back";
    prev.textContent = "‹";
    prev.addEventListener("click", () => {
      monthlyCalendarState.monthKey = shiftMonthKey(monthKey, -1);
      renderMonthlyCalendar();
    });
    header.appendChild(prev);

    const title = document.createElement("div");
    title.className = "stats-drill-title";
    title.textContent = formatMonth.format(new Date(`${monthKey}-01T00:00:00`));
    header.appendChild(title);

    const next = document.createElement("button");
    next.type = "button";
    next.className = "stats-drill-back";
    next.textContent = "›";
    next.addEventListener("click", () => {
      monthlyCalendarState.monthKey = shiftMonthKey(monthKey, 1);
      renderMonthlyCalendar();
    });
    header.appendChild(next);
    container.appendChild(header);

    const monthData = (usageData.daily_queries || []).filter((item) => item.date && item.date.slice(0, 7) === monthKey);
    drawCalendarChart("#chart-monthly-calendar", monthData, {
      colorRange: ["#ebf5fb", "#85c1e9", "#3498db", "#21618c"],
      tooltipFormatter: (item) => `${formatDateOnly(item.date)}: ${item.count}`,
      cellSizeMax: 28,
      center: true,
      hideMonthLabel: true,
      onDayClick: (item) => {
        monthlyState.level = "hours";
        monthlyState.day = item;
        renderMonthlyBarsChart();
      },
    });
  }

  function setupMonthlyCalendar() {
    monthlyCalendarState.monthKey = defaultCalendarMonthKey();
    renderMonthlyCalendar();
  }

  function defaultCalendarMonthKey() {
    const daily = usageData.daily_queries || [];
    const lastWithDate = [...daily].reverse().find((item) => item.date);
    return lastWithDate ? String(lastWithDate.date).slice(0, 7) : null;
  }

  function shiftMonthKey(monthKey, delta) {
    const [yearStr, monthStr] = String(monthKey).split("-");
    const base = new Date(Number(yearStr), Number(monthStr) - 1, 1);
    base.setMonth(base.getMonth() + delta);
    const year = base.getFullYear();
    const month = String(base.getMonth() + 1).padStart(2, "0");
    return `${year}-${month}`;
  }

  function renderAvgTimeChart() {
    const container = document.querySelector("#chart-monthly-avg-time");
    if (!container) return;
    container.innerHTML = "";

    renderDrillHeader(container, avgTimeState, {
      rootLabel: config.labels.months || "Meses",
      valueLabel: config.labels.averageTime || "Tiempo medio",
      onBack: () => {
        if (avgTimeState.level === "days") {
          avgTimeState.level = "weeks";
          avgTimeState.week = null;
        } else {
          avgTimeState.level = "months";
          avgTimeState.month = null;
        }
        renderAvgTimeChart();
      },
    });

    if (avgTimeState.level === "weeks") {
      const weeklyData = buildWeeklyAverageData(usageData.daily_avg_time, usageData.daily_queries, avgTimeState.month);
      drawLineChart("#chart-monthly-avg-time", weeklyData, {
        xKey: "id",
        yKey: "avg_time",
        color: "#f5b041",
        xFormatter: (value, item) => (item ? item.label : value),
        rotateLabels: true,
        tooltipFormatter: (item) => `${item.label}: ${item.avg_time} ${config.labels.seconds}`,
        onClick: (item) => {
          avgTimeState.level = "days";
          avgTimeState.week = item;
          renderAvgTimeChart();
        },
      });
      return;
    }

    if (avgTimeState.level === "days" && avgTimeState.week) {
      drawLineChart("#chart-monthly-avg-time", avgTimeState.week.days, {
        xKey: "date",
        yKey: "avg_time",
        color: "#f5b041",
        xFormatter: (value) => formatDayShort.format(new Date(`${value}T00:00:00`)),
        rotateLabels: true,
        tooltipFormatter: (item) => `${formatDateOnly(item.date)}: ${item.avg_time} ${config.labels.seconds}`,
      });
      return;
    }

    drawLineChart("#chart-monthly-avg-time", usageData.monthly_avg_time, {
      xKey: "month",
      yKey: "avg_time",
      color: "#f5b041",
      xFormatter: (value) => formatMonth.format(new Date(value)),
      tickValues: selectTickValues(usageData.monthly_avg_time, "month", 4),
      tooltipFormatter: (item) =>
        `${formatMonth.format(new Date(item.month))}: ${item.avg_time} ${config.labels.seconds}`,
      onClick: (item) => {
        avgTimeState.level = "weeks";
        avgTimeState.month = monthKeyFromDate(item.month);
        renderAvgTimeChart();
      },
    });
  }

  function setupAvgTimeDrilldown() {
    renderAvgTimeChart();
  }

  function drawBarChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const width = chartWidth(container, 640);
    const narrow = isNarrow(width);
    const height = container.classList.contains("stats-chart-compact") ? (narrow ? 260 : 280) : (narrow ? 300 : 320);
    const margin = {
      top: 18,
      right: narrow ? 10 : 18,
      bottom: options.rotateLabels || narrow ? 86 : 56,
      left: narrow ? 38 : 46,
    };

    const xValues = data.map((item) => item[options.xKey]);
    const yMax = d3.max(data, (item) => Number(item[options.yKey]) || 0) || 1;
    const xScale = d3.scaleBand().domain(xValues).range([margin.left, width - margin.right]).padding(0.22);
    const yScale = d3.scaleLinear().domain([0, yMax]).nice().range([height - margin.bottom, margin.top]);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    svg
      .append("g")
      .attr("class", "stats-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickSize(-(width - margin.left - margin.right)).tickFormat(""))
      .call((g) => g.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(
        d3
          .axisBottom(xScale)
          .tickValues(options.tickValues || compactTickValues(data, options.xKey, width, 8))
          .tickFormat((value) => {
            const item = data.find((entry) => entry[options.xKey] === value);
            const label = options.xFormatter ? options.xFormatter(value, item) : value;
            return truncateLabel(label, narrow ? 10 : 18);
          })
      )
      .call((g) => {
        g.select(".domain").remove();
        if (options.rotateLabels || narrow) {
          g.selectAll("text")
            .style("text-anchor", "end")
            .attr("transform", "rotate(-35)")
            .attr("dx", "-0.55em")
            .attr("dy", "0.2em");
        }
      });

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5))
      .call((g) => g.select(".domain").remove());

    svg
      .append("g")
      .selectAll("rect")
      .data(data)
      .join("rect")
      .attr("x", (item) => xScale(item[options.xKey]))
      .attr("y", (item) => yScale(Number(item[options.yKey]) || 0))
      .attr("width", xScale.bandwidth())
      .attr("height", (item) => yScale(0) - yScale(Number(item[options.yKey]) || 0))
      .attr("rx", 12)
      .attr("fill", options.color)
      .attr("cursor", options.onClick ? "pointer" : null)
      .on("click", function (event, item) {
        if (options.onClick) {
          options.onClick(item, event);
        }
      })
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item[options.yKey]}`);
        d3.select(this).attr("opacity", 0.82);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("opacity", 1);
      });
  }

  function drawLineChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const width = chartWidth(container, 640);
    const narrow = isNarrow(width);
    const height = narrow ? 260 : 280;
    const margin = { top: 18, right: narrow ? 10 : 18, bottom: options.rotateLabels || narrow ? 86 : 56, left: narrow ? 38 : 46 };
    const parsedData = data.map((item) => ({
      ...item,
      __date: new Date(item[options.xKey]),
      __value: Number(item[options.yKey]) || 0,
    }));

    const xScale = d3
      .scalePoint()
      .domain(parsedData.map((item) => item[options.xKey]))
      .range([margin.left, width - margin.right]);
    const yScale = d3
      .scaleLinear()
      .domain([0, d3.max(parsedData, (item) => item.__value) || 1])
      .nice()
      .range([height - margin.bottom, margin.top]);

    const line = d3
      .line()
      .x((item) => xScale(item[options.xKey]))
      .y((item) => yScale(item.__value))
      .curve(d3.curveMonotoneX);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    svg
      .append("g")
      .attr("class", "stats-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickSize(-(width - margin.left - margin.right)).tickFormat(""))
      .call((g) => g.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(
        d3
          .axisBottom(xScale)
          .tickValues(options.tickValues || compactTickValues(parsedData, options.xKey, width, 8))
          .tickFormat((value) => {
            const item = parsedData.find((entry) => entry[options.xKey] === value);
            const label = options.xFormatter ? options.xFormatter(value, item) : value;
            return truncateLabel(label, narrow ? 10 : 18);
          })
      )
      .call((g) => {
        g.select(".domain").remove();
        if (options.rotateLabels || narrow) {
          g.selectAll("text")
            .style("text-anchor", "end")
            .attr("transform", "rotate(-35)")
            .attr("dx", "-0.55em")
            .attr("dy", "0.2em");
        }
      });

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5))
      .call((g) => g.select(".domain").remove());

    svg
      .append("path")
      .datum(parsedData)
      .attr("fill", "none")
      .attr("stroke", options.color)
      .attr("stroke-width", 3)
      .attr("cursor", options.onClick ? "pointer" : null)
      .on("click", function (event) {
        if (!options.onClick) return;
        const [pointerX] = d3.pointer(event, this);
        const nearest = parsedData.reduce((best, item) => {
          const distance = Math.abs((xScale(item[options.xKey]) || 0) - pointerX);
          return distance < best.distance ? { item, distance } : best;
        }, { item: parsedData[0], distance: Infinity });
        options.onClick(nearest.item, event);
      })
      .attr("d", line);

    svg
      .append("g")
      .selectAll("circle")
      .data(parsedData)
      .join("circle")
      .attr("cx", (item) => xScale(item[options.xKey]))
      .attr("cy", (item) => yScale(item.__value))
      .attr("r", options.onClick ? 6 : 5)
      .attr("fill", options.color)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .attr("cursor", options.onClick ? "pointer" : null)
      .on("click", function (event, item) {
        if (options.onClick) {
          options.onClick(item, event);
        }
      })
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item.__value}`);
        d3.select(this).attr("r", options.onClick ? 8 : 6);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("r", options.onClick ? 6 : 5);
      });
  }

  function drawUserComparisonChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container, options.noDataMessage || config.labels.noData);

    const width = chartWidth(container, 640);
    const narrow = isNarrow(width);
    const height = narrow ? 360 : 340;
    const margin = { top: narrow ? 54 : 34, right: narrow ? 14 : 38, bottom: options.rotateLabels || narrow ? 104 : 56, left: narrow ? 40 : 52 };
    const xValues = data.map((item) => item[options.xKey]);
    const yMax = d3.max(data, (item) => Number(item[options.yKey]) || 0) || 1;
    const totalValue = d3.sum(data, (item) => Number(item[options.yKey]) || 0);
    if (!totalValue) return renderEmptyState(container, options.noDataMessage || config.labels.noData);

    const medianValue = Number(options.median);
    const hasMedian = Number.isFinite(medianValue);
    const variance = Number(options.variance) || 0;
    const xScale = d3.scaleBand().domain(xValues).range([margin.left, width - margin.right]).padding(0.18);
    const yScale = d3
      .scaleLinear()
      .domain([0, Math.max(yMax, Number(options.mean) || 0, hasMedian ? medianValue : 0)])
      .nice()
      .range([height - margin.bottom, margin.top]);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    svg
      .append("g")
      .attr("class", "stats-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickSize(-(width - margin.left - margin.right)).tickFormat(""))
      .call((g) => g.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(
        d3
          .axisBottom(xScale)
          .tickValues(options.tickValues || compactTickValues(data, options.xKey, width, 8))
          .tickFormat((value) => {
            const item = data.find((entry) => entry[options.xKey] === value);
            const label = options.xFormatter ? options.xFormatter(value, item) : value;
            return truncateLabel(label, narrow ? 11 : 18);
          })
      )
      .call((g) => {
        g.select(".domain").remove();
        if (options.rotateLabels || narrow) {
          g.selectAll("text")
            .style("text-anchor", "end")
            .attr("transform", "rotate(-35)")
            .attr("dx", "-0.55em")
            .attr("dy", "0.2em");
        }
      });

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5))
      .call((g) => g.select(".domain").remove());

    svg
      .append("g")
      .selectAll("rect")
      .data(data)
      .join("rect")
      .attr("x", (item) => xScale(item[options.xKey]))
      .attr("y", (item) => yScale(Number(item[options.yKey]) || 0))
      .attr("width", xScale.bandwidth())
      .attr("height", (item) => yScale(0) - yScale(Number(item[options.yKey]) || 0))
      .attr("rx", 10)
      .attr("fill", options.color)
      .attr("cursor", options.onClick ? "pointer" : null)
      .on("click", function (event, item) {
        if (options.onClick) {
          options.onClick(item, event);
        }
      })
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item[options.yKey]}`);
        d3.select(this).attr("opacity", 0.82);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("opacity", 1);
      });

    if (typeof options.mean === "number") {
      drawReferenceLine(svg, yScale, margin, width, options.mean, {
        color: "#f1c40f",
        dash: "4 6",
        label: `${options.meanLabel || config.labels.comparisonMean || "Media"}: ${options.mean}`,
      });
    }

    if (hasMedian) {
      drawReferenceLine(svg, yScale, margin, width, medianValue, {
        color: "#48c9b0",
        dash: "2 5",
        label: `${options.medianLabel || config.labels.comparisonMedian || "Mediana"}: ${medianValue}`,
        offset: 22,
      });
    }

    svg
      .append("text")
      .attr("x", margin.left)
      .attr("y", narrow ? 22 : 20)
      .attr("fill", "var(--bs-secondary-color)")
      .attr("font-size", 12)
      .attr("font-weight", 700)
      .text(`${options.varianceLabel || config.labels.comparisonVariance || "Varianza"}: ${variance}`);
  }

  function drawReferenceLine(svg, yScale, margin, width, value, options) {
    const y = yScale(value);
    svg
      .append("line")
      .attr("x1", margin.left)
      .attr("x2", width - margin.right)
      .attr("y1", y)
      .attr("y2", y)
      .attr("stroke", options.color)
      .attr("stroke-dasharray", options.dash)
      .attr("stroke-width", 2);

    svg
      .append("text")
      .attr("x", width - margin.right)
      .attr("y", y - (options.offset || 8))
      .attr("text-anchor", "end")
      .attr("fill", options.color)
      .attr("font-size", 12)
      .attr("font-weight", 700)
      .text(options.label);
  }

  function drawDonutChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const total = d3.sum(data, (item) => Number(item[options.valueKey]) || 0);
    if (!total) return renderEmptyState(container);

    const width = chartWidth(container, 640);
    const narrow = isNarrow(width);
    const height = narrow ? 340 : 280;
    const chartCenterX = narrow ? width / 2 : width * 0.58;
    const chartCenterY = narrow ? 220 : height / 2;
    const radius = Math.min(width * (narrow ? 0.34 : 0.36), height * 0.44) - 10;
    const innerRadius = radius * 0.56;
    const pieData = d3
      .pie()
      .sort(null)
      .value((item) => Number(item[options.valueKey]) || 0)(data);
    const colorScale = d3
      .scaleOrdinal()
      .domain(data.map((item) => item[options.labelKey]))
      .range(options.colors || d3.schemeTableau10);

    const arc = d3.arc().innerRadius(innerRadius).outerRadius(radius);
    const hoverArc = d3.arc().innerRadius(innerRadius).outerRadius(radius + 6);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    const chart = svg
      .append("g")
      .attr("transform", `translate(${chartCenterX},${chartCenterY})`);

    chart
      .selectAll("path")
      .data(pieData)
      .join("path")
      .attr("d", arc)
      .attr("fill", (item) => colorScale(item.data[options.labelKey]))
      .attr("stroke", "rgba(255, 255, 255, 0.92)")
      .attr("stroke-width", 2)
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item.data) : `${item.data[options.valueKey]}`);
        d3.select(this).attr("d", hoverArc);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("d", arc);
      });

    chart
      .append("text")
      .attr("text-anchor", "middle")
      .attr("y", -4)
      .attr("fill", "currentColor")
      .attr("font-size", 28)
      .attr("font-weight", 700)
      .text(total);

    chart
      .append("text")
      .attr("text-anchor", "middle")
      .attr("y", 18)
      .attr("fill", "var(--bs-secondary-color)")
      .attr("font-size", 12)
      .text(options.unitLabel || config.labels.unitQueries || "consultas");

    const legend = svg
      .append("g")
      .attr("transform", `translate(16, 18)`);

    const legendItem = legend
      .selectAll("g")
      .data(data)
      .join("g")
      .attr("transform", (_, index) => {
        const itemsPerColumn = narrow ? 6 : 4;
        const column = Math.floor(index / itemsPerColumn);
        const row = index % itemsPerColumn;
        const columnWidth = narrow ? Math.max(120, (width - 32) / Math.max(1, Math.ceil(data.length / itemsPerColumn))) : 140;
        return `translate(${column * columnWidth}, ${row * 24})`;
      });

    legendItem
      .append("circle")
      .attr("r", 6)
      .attr("cx", 0)
      .attr("cy", 0)
      .attr("fill", (item) => colorScale(item[options.labelKey]));

    legendItem
      .append("text")
      .attr("x", 12)
      .attr("y", 4)
      .attr("fill", "currentColor")
      .attr("font-size", 12)
      .text((item) => {
        const label = options.labelFormatter ? options.labelFormatter(item[options.labelKey]) : item[options.labelKey];
        return `${truncateLabel(label, narrow ? 13 : 20)} (${item[options.valueKey]})`;
      });
  }

  function drawHeatmapChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const width = chartWidth(container, 640);
    const narrow = isNarrow(width);
    const height = narrow ? 320 : 280;
    const margin = { top: 26, right: 18, bottom: 50, left: 18 };
    const columns = narrow ? 4 : 6;
    const rows = Math.ceil(data.length / columns);
    const gridWidth = width - margin.left - margin.right;
    const gridHeight = height - margin.top - margin.bottom;
    const gap = 8;
    const cellWidth = (gridWidth - gap * (columns - 1)) / columns;
    const cellHeight = (gridHeight - gap * (rows - 1)) / rows;
    const maxValue = d3.max(data, (item) => Number(item[options.yKey]) || 0) || 0;
    const colorScale = d3
      .scaleLinear()
      .domain([0, Math.max(maxValue / 2, 1), Math.max(maxValue, 1)])
      .range(["#f8d7da", "#ec7063", "#7b241c"]);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    const chart = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    chart
      .selectAll("g")
      .data(data)
      .join("g")
      .attr("transform", (_, index) => {
        const column = index % columns;
        const row = Math.floor(index / columns);
        return `translate(${column * (cellWidth + gap)}, ${row * (cellHeight + gap)})`;
      })
      .call((group) => {
        group
          .append("rect")
          .attr("class", "stats-heatmap-cell")
          .attr("rx", 14)
          .attr("width", cellWidth)
          .attr("height", cellHeight)
          .attr("fill", (item) => colorScale(Number(item[options.yKey]) || 0))
          .on("mousemove", function (event, item) {
            showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item[options.yKey]}`);
            d3.select(this).attr("opacity", 0.86);
          })
          .on("mouseleave", function () {
            hideTooltip();
            d3.select(this).attr("opacity", 1);
          });

        group
          .append("text")
          .attr("x", cellWidth / 2)
          .attr("y", cellHeight / 2 - 4)
          .attr("text-anchor", "middle")
          .attr("fill", "#fff")
          .attr("font-size", Math.max(11, Math.min(cellWidth * 0.16, 16)))
          .attr("font-weight", 700)
          .text((item) => options.labelFormatter ? options.labelFormatter(item[options.xKey]) : item[options.xKey]);

        group
          .append("text")
          .attr("x", cellWidth / 2)
          .attr("y", cellHeight / 2 + 18)
          .attr("text-anchor", "middle")
          .attr("fill", "#fff")
          .attr("font-size", Math.max(12, Math.min(cellWidth * 0.18, 18)))
          .attr("font-weight", 600)
          .text((item) => item[options.yKey]);
      });

    const legend = svg.append("g").attr("transform", `translate(${margin.left}, ${height - 20})`);
    const legendWidth = Math.min(170, gridWidth);

    const gradientId = "stats-hours-heatmap-gradient";
    const defs = svg.append("defs");
    const gradient = defs.append("linearGradient").attr("id", gradientId);
    gradient.append("stop").attr("offset", "0%").attr("stop-color", "#f8d7da");
    gradient.append("stop").attr("offset", "50%").attr("stop-color", "#ec7063");
    gradient.append("stop").attr("offset", "100%").attr("stop-color", "#7b241c");

    legend
      .append("rect")
      .attr("width", legendWidth)
      .attr("height", 10)
      .attr("rx", 999)
      .attr("fill", `url(#${gradientId})`);

    legend
      .append("text")
      .attr("class", "stats-heatmap-label")
      .attr("x", 0)
      .attr("y", -4)
      .text("0");

    legend
      .append("text")
      .attr("class", "stats-heatmap-label")
      .attr("x", legendWidth)
      .attr("y", -4)
      .attr("text-anchor", "end")
      .text(String(maxValue));
  }

  function drawUserLocationsMap(selector, data) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (typeof topojson === "undefined") return renderEmptyState(container, config.labels.mapLoadError);

    const byCountryId = new Map(data.map((item) => [String(item.country_id).padStart(3, "0"), item]));
    const maxValue = d3.max(data, (item) => Number(item.count) || 0) || 1;
    const colorScale = d3
      .scaleSequential()
      .domain([0, maxValue])
      .interpolator(d3.interpolateYlGnBu);

    d3.json("https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json")
      .then((world) => {
        container.innerHTML = "";
        const countries = topojson.feature(world, world.objects.countries).features;
        const width = chartWidth(container, 860);
        const height = Math.max(isNarrow(width) ? 300 : 360, Math.round(width * 0.52));
        const projection = d3.geoNaturalEarth1().fitSize([width, height], { type: "Sphere" });
        const path = d3.geoPath(projection);

        const svg = d3
          .select(container)
          .append("svg")
          .attr("viewBox", `0 0 ${width} ${height}`)
          .attr("role", "img");

        svg
          .append("path")
          .datum({ type: "Sphere" })
          .attr("class", "stats-map-ocean")
          .attr("d", path);

        svg
          .append("g")
          .selectAll("path")
          .data(countries)
          .join("path")
          .attr("class", "stats-map-country")
          .attr("d", path)
          .attr("fill", (feature) => {
            const item = byCountryId.get(String(feature.id).padStart(3, "0"));
            return item ? colorScale(item.count) : "rgba(148, 163, 184, 0.28)";
          })
          .on("mousemove", function (event, feature) {
            const item = byCountryId.get(String(feature.id).padStart(3, "0"));
            if (!item) {
              return;
            }
            showTooltip(event, formatCountryTooltip(item));
            d3.select(this).attr("opacity", 0.82);
          })
          .on("mouseleave", function () {
            hideTooltip();
            d3.select(this).attr("opacity", 1);
          });

        drawMapLegend(svg, width, height, colorScale, maxValue);
      })
      .catch(() => renderEmptyState(container, config.labels.mapLoadError));
  }

  function drawMapLegend(svg, width, height, colorScale, maxValue) {
    const legendWidth = Math.min(220, width - 36);
    const legendX = 18;
    const legendY = height - 34;
    const gradientId = "stats-user-map-gradient";
    const defs = svg.append("defs");
    const gradient = defs.append("linearGradient").attr("id", gradientId);

    d3.range(0, 1.01, 0.1).forEach((value) => {
      gradient
        .append("stop")
        .attr("offset", `${value * 100}%`)
        .attr("stop-color", colorScale(value * maxValue));
    });

    const legend = svg.append("g").attr("transform", `translate(${legendX}, ${legendY})`);
    legend
      .append("rect")
      .attr("width", legendWidth)
      .attr("height", 10)
      .attr("rx", 5)
      .attr("fill", `url(#${gradientId})`);

    legend
      .append("text")
      .attr("class", "stats-map-legend-label")
      .attr("x", 0)
      .attr("y", -5)
      .text("0");

    legend
      .append("text")
      .attr("class", "stats-map-legend-label")
      .attr("x", legendWidth)
      .attr("y", -5)
      .attr("text-anchor", "end")
      .text(String(maxValue));
  }

  function formatCountryTooltip(item) {
    const base = `${item.country_name}: ${item.count} ${config.labels.users || "usuarios"}`;
    if (!Array.isArray(item.users) || item.users.length === 0) {
      return base;
    }

    return `${base}\n${config.labels.userNames || "Usuarios"}: ${item.users.join(", ")}`;
  }

  function drawCalendarChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const parsedData = data.map((item) => ({
      ...item,
      __date: new Date(`${item.date}T00:00:00`),
      __value: Number(item.count) || 0,
    }));
    const byMonth = d3.groups(parsedData, (item) => item.date.slice(0, 7));
    const width = chartWidth(container, 860);
    let columns = width >= 920 ? 4 : width >= 680 ? 3 : width >= 440 ? 2 : 1;
    columns = Math.max(1, Math.min(columns, byMonth.length));
    const monthWidth = Math.floor((width - 24 * (columns - 1)) / columns);
    const cellMax = Number.isFinite(options.cellSizeMax) ? options.cellSizeMax : 18;
    const cellMin = Number.isFinite(options.cellSizeMin) ? options.cellSizeMin : 11;
    const cellSize = Math.max(cellMin, Math.min(cellMax, Math.floor((monthWidth - 46) / 7)));
    const monthHeight = cellSize * 7 + 42;
    const rows = Math.ceil(byMonth.length / columns);
    const height = rows * monthHeight + Math.max(0, rows - 1) * 20;
    const maxValue = d3.max(parsedData, (item) => item.__value) || 0;
    const colorScale = d3
      .scaleLinear()
      .domain([0, Math.max(1, maxValue / 3), Math.max(1, (maxValue * 2) / 3), Math.max(1, maxValue)])
      .range(options.colorRange || ["#ebf5fb", "#85c1e9", "#3498db", "#21618c"]);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    const dayLabels = config.labels.weekdays || ["L", "M", "X", "J", "V", "S", "D"];

    byMonth.forEach(([monthKey, values], index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const baseOffsetX = column * (monthWidth + 24);
      const contentWidth = 34 + cellSize * 7 + 2;
      const offsetX =
        options.center && columns === 1
          ? Math.max(0, Math.round((width - contentWidth) / 2))
          : baseOffsetX;
      const offsetY = row * (monthHeight + 20);
      const monthStart = new Date(`${monthKey}-01T00:00:00`);
      const monthEnd = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0);
      const lastWeek = d3.timeMonday.count(d3.timeMonth(monthStart), monthEnd);
      const monthGroup = svg.append("g").attr("transform", `translate(${offsetX},${offsetY})`);

      if (!options.hideMonthLabel) {
        monthGroup
          .append("text")
          .attr("class", "stats-calendar-month-label")
          .attr("x", 0)
          .attr("y", 14)
          .attr("cursor", options.onMonthClick ? "pointer" : null)
          .on("click", () => {
            if (options.onMonthClick) {
              options.onMonthClick(monthKey);
            }
          })
          .text(formatMonth.format(monthStart));
      }

      monthGroup
        .selectAll(".stats-calendar-day-label")
        .data(dayLabels)
        .join("text")
        .attr("class", "stats-calendar-day-label")
        .attr("x", (_, dayIndex) => 34 + dayIndex * cellSize + cellSize / 2)
        .attr("y", 32)
        .attr("text-anchor", "middle")
        .text((label) => String(label).slice(0, 1));

      monthGroup
        .selectAll(".stats-calendar-cell")
        .data(values)
        .join("rect")
        .attr("class", "stats-calendar-cell")
        .attr("width", cellSize - 2)
        .attr("height", cellSize - 2)
        .attr("rx", 3)
        .attr("x", (item) => 34 + dayIndexMonday(item.__date) * cellSize)
        .attr("y", (item) => 40 + d3.timeMonday.count(d3.timeMonth(item.__date), item.__date) * cellSize)
        .attr("fill", (item) => colorScale(item.__value))
        .attr("cursor", options.onDayClick || options.onMonthClick ? "pointer" : null)
        .on("click", (event, item) => {
          if (options.onDayClick) {
            options.onDayClick(item, event);
          } else if (options.onMonthClick) {
            options.onMonthClick(monthKey, event);
          }
        })
        .on("mousemove", function (event, item) {
          showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item.__value}`);
          d3.select(this).attr("opacity", 0.86);
        })
        .on("mouseleave", function () {
          hideTooltip();
          d3.select(this).attr("opacity", 1);
        });

      monthGroup
        .append("rect")
        .attr("class", "stats-calendar-month-outline")
        .attr("x", 33)
        .attr("y", 39)
        .attr("width", cellSize * 7 + 2)
        .attr("height", (lastWeek + 1) * cellSize + 2)
        .attr("cursor", options.onMonthClick ? "pointer" : null)
        .on("click", () => {
          if (options.onMonthClick) {
            options.onMonthClick(monthKey);
          }
        });
    });
  }

  function renderDrillHeader(container, state, options) {
    const header = document.createElement("div");
    header.className = "stats-drill-header";

    const title = document.createElement("div");
    title.className = "stats-drill-title";
    title.textContent = buildDrillTitle(state, options);
    header.appendChild(title);

    if (state.level !== "months") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "stats-drill-back";
      button.textContent = config.labels.back || "Volver";
      button.addEventListener("click", options.onBack);
      header.appendChild(button);
    }

    container.appendChild(header);
  }

  function buildDrillTitle(state, options) {
    if (state.level === "hours" && state.day) {
      return `${options.valueLabel} - ${formatDateOnly(state.day.date)}`;
    }

    if (state.level === "days" && state.week) {
      return `${options.valueLabel} - ${state.week.label}`;
    }

    if (state.level === "weeks" && state.month) {
      return `${options.valueLabel} - ${formatMonth.format(new Date(`${state.month}-01T00:00:00`))}`;
    }

    return options.rootLabel;
  }

  function buildWeeklyCountData(dailyData, monthKey) {
    return buildWeeklyData(dailyData, monthKey, (days, index) => ({
      id: `${monthKey}-W${index + 1}`,
      label: weekLabel(days, index),
      count: d3.sum(days, (item) => Number(item.count) || 0),
      days,
    }));
  }

  function buildWeeklyAverageData(avgData, countData, monthKey) {
    const countByDate = new Map((countData || []).map((item) => [item.date, Number(item.count) || 0]));
    const daysWithCounts = (avgData || []).map((item) => ({
      ...item,
      count: countByDate.get(item.date) || 0,
    }));

    return buildWeeklyData(daysWithCounts, monthKey, (days, index) => {
      const totalCount = d3.sum(days, (item) => item.count);
      const weightedTime = d3.sum(days, (item) => (Number(item.avg_time) || 0) * item.count);

      return {
        id: `${monthKey}-W${index + 1}`,
        label: weekLabel(days, index),
        avg_time: totalCount ? roundMetric(weightedTime / totalCount) : 0,
        days,
      };
    });
  }

  function hourlyDataForDay(dateKey) {
    const dayData = (usageData.daily_hourly_queries || []).find((item) => item.date === dateKey);
    if (dayData && Array.isArray(dayData.hours)) {
      return dayData.hours;
    }

    return d3.range(24).map((hour) => ({ hour, count: 0 }));
  }

  function buildWeeklyData(dailyData, monthKey, mapper) {
    const monthDays = (dailyData || [])
      .filter((item) => item.date && item.date.slice(0, 7) === monthKey)
      .map((item) => ({ ...item, __date: new Date(`${item.date}T00:00:00`) }));

    const grouped = d3.groups(monthDays, (item) => d3.timeMonday.count(d3.timeMonth(item.__date), item.__date));
    return grouped.map(([_, days], index) => mapper(days, index));
  }

  function weekLabel(days, index) {
    const first = days[0];
    const last = days[days.length - 1];
    const range = first && last ? `${formatDayShort.format(first.__date)} - ${formatDayShort.format(last.__date)}` : "";
    return `${config.labels.week || "Semana"} ${index + 1}${range ? ` (${range})` : ""}`;
  }

  function monthKeyFromDate(value) {
    return String(value).slice(0, 7);
  }

  function roundMetric(value) {
    return Math.round(value * 100) / 100;
  }

  function renderEmptyState(container, message) {
    const empty = document.createElement("div");
    empty.className = "stats-empty";
    empty.textContent = message || config.labels.noData;
    container.appendChild(empty);
  }

  function createTooltip() {
    const element = document.createElement("div");
    element.className = "stats-tooltip";
    document.body.appendChild(element);
    return element;
  }

  function showTooltip(event, text) {
    tooltip.textContent = text;
    tooltip.style.opacity = "1";
    tooltip.style.transform = "translateY(0)";
    tooltip.style.left = `${event.clientX + 14}px`;
    tooltip.style.top = `${event.clientY + 14}px`;
  }

  function hideTooltip() {
    tooltip.style.opacity = "0";
    tooltip.style.transform = "translateY(4px)";
  }

  function selectTickValues(data, key, maxTicks) {
    if (!Array.isArray(data) || data.length <= maxTicks) {
      return data.map((item) => item[key]);
    }

    const step = Math.ceil(data.length / maxTicks);
    return data
      .filter((_, index) => index % step === 0 || index === data.length - 1)
      .map((item) => item[key]);
  }

  function selectHourTicks(data, width) {
    if (!Array.isArray(data)) {
      return [];
    }

    const step = width && width < 520 ? 6 : 3;
    return data
      .filter((item) => item.hour % step === 0 || item.hour === 23)
      .map((item) => item.hour);
  }

  function formatDateOnly(value) {
    return formatDate.format(new Date(`${value}T00:00:00`));
  }

  function dayIndexMonday(dateValue) {
    return (dateValue.getDay() + 6) % 7;
  }
})();
