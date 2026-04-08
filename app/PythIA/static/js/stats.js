(function () {
  const config = window.PYTHIA_STATS;
  if (!config || typeof d3 === "undefined") {
    return;
  }

  const tooltip = createTooltip();
  const locale = config.locale || "es";
  const formatMonth = new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" });
  const formatDateTime = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  setupMonthlyChartToggle();

  drawLineChart("#chart-monthly-avg-time", config.data.monthly_avg_time, {
    xKey: "month",
    yKey: "avg_time",
    color: "#f5b041",
    xFormatter: (value) => formatMonth.format(new Date(value)),
    tickValues: selectTickValues(config.data.monthly_avg_time, "month", 4),
    tooltipFormatter: (item) =>
      `${formatMonth.format(new Date(item.month))}: ${item.avg_time} ${config.labels.seconds}`,
  });

  drawDonutChart("#chart-weekdays", config.data.weekday_queries, {
    labelKey: "weekday",
    valueKey: "count",
    colors: ["#58d68d", "#48c9b0", "#5dade2", "#f4d03f", "#eb984e", "#ec7063", "#af7ac5"],
    labelFormatter: (value) => config.labels.weekdays[value] || value,
    tooltipFormatter: (item) =>
      `${config.labels.weekdays[item.weekday] || item.weekday}: ${item.count}`,
  });

  setupHourlyChartToggle();

  if (Array.isArray(config.data.top_users) && config.data.top_users.length) {
    drawDonutChart("#chart-top-users", config.data.top_users, {
      labelKey: "user",
      valueKey: "count",
      colors: ["#af7ac5", "#5dade2", "#58d68d", "#f5b041", "#ec7063", "#48c9b0", "#eb984e", "#7fb3d5"],
      labelFormatter: (value) => value,
      tooltipFormatter: (item) => `${item.user}: ${item.count}`,
    });
  }

  const summaryDate = document.querySelector("[data-stats-last-query]");
  if (summaryDate && summaryDate.dataset.value) {
    summaryDate.textContent = formatDateTime.format(new Date(summaryDate.dataset.value));
  }

  function setupHourlyChartToggle() {
    const container = document.querySelector("#chart-hours");
    if (!container) return;

    const buttons = Array.from(document.querySelectorAll("[data-hours-view]"));
    const renderers = {
      bars: () =>
        drawBarChart("#chart-hours", config.data.hourly_queries, {
          xKey: "hour",
          yKey: "count",
          color: "#ec7063",
          xFormatter: (value) => `${String(value).padStart(2, "0")}:00`,
          tickValues: selectHourTicks(config.data.hourly_queries),
          tooltipFormatter: (item) => `${String(item.hour).padStart(2, "0")}:00 - ${item.count}`,
        }),
      heatmap: () =>
        drawHeatmapChart("#chart-hours", config.data.hourly_queries, {
          xKey: "hour",
          yKey: "count",
          labelFormatter: (value) => `${String(value).padStart(2, "0")}:00`,
          tooltipFormatter: (item) => `${String(item.hour).padStart(2, "0")}:00 - ${item.count}`,
        }),
    };

    const setView = (view) => {
      container.innerHTML = "";
      (renderers[view] || renderers.bars)();
      buttons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.hoursView === view);
      });
    };

    buttons.forEach((button) => {
      button.addEventListener("click", () => setView(button.dataset.hoursView));
    });

    setView("bars");
  }

  function setupMonthlyChartToggle() {
    const container = document.querySelector("#chart-monthly-queries");
    if (!container) return;

    const buttons = Array.from(document.querySelectorAll("[data-monthly-view]"));
    const renderers = {
      bars: () =>
        drawBarChart("#chart-monthly-queries", config.data.monthly_queries, {
          xKey: "month",
          yKey: "count",
          color: "#5dade2",
          xFormatter: (value) => formatMonth.format(new Date(value)),
          tooltipFormatter: (item) => `${formatMonth.format(new Date(item.month))}: ${item.count}`,
        }),
      calendar: () =>
        drawCalendarChart("#chart-monthly-queries", config.data.daily_queries, {
          colorRange: ["#ebf5fb", "#85c1e9", "#3498db", "#21618c"],
          tooltipFormatter: (item) => `${formatDateTimeDateOnly(item.date)}: ${item.count}`,
        }),
    };

    const setView = (view) => {
      container.innerHTML = "";
      (renderers[view] || renderers.bars)();
      buttons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.monthlyView === view);
      });
    };

    buttons.forEach((button) => {
      button.addEventListener("click", () => setView(button.dataset.monthlyView));
    });

    setView("bars");
  }

  function drawBarChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const width = container.clientWidth || 640;
    const height = container.classList.contains("stats-chart-compact") ? 280 : 320;
    const margin = {
      top: 18,
      right: 18,
      bottom: options.rotateLabels ? 90 : 56,
      left: 46,
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
          .tickValues(options.tickValues || xValues)
          .tickFormat((value) => options.xFormatter ? options.xFormatter(value) : value)
      )
      .call((g) => {
        g.select(".domain").remove();
        if (options.rotateLabels) {
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

    const width = container.clientWidth || 640;
    const height = 280;
    const margin = { top: 18, right: 18, bottom: 56, left: 46 };
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
          .tickValues(options.tickValues || parsedData.map((item) => item[options.xKey]))
          .tickFormat((value) => options.xFormatter ? options.xFormatter(value) : value)
      )
      .call((g) => g.select(".domain").remove());

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
      .attr("d", line);

    svg
      .append("g")
      .selectAll("circle")
      .data(parsedData)
      .join("circle")
      .attr("cx", (item) => xScale(item[options.xKey]))
      .attr("cy", (item) => yScale(item.__value))
      .attr("r", 5)
      .attr("fill", options.color)
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter ? options.tooltipFormatter(item) : `${item.__value}`);
        d3.select(this).attr("r", 6);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("r", 5);
      });
  }

  function drawDonutChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const total = d3.sum(data, (item) => Number(item[options.valueKey]) || 0);
    if (!total) return renderEmptyState(container);

    const width = container.clientWidth || 640;
    const height = 280;
    const radius = Math.min(width, height) / 2 - 16;
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
      .attr("transform", `translate(${width / 2},${height / 2})`);

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
      .text("consultas");

    const legend = svg
      .append("g")
      .attr("transform", `translate(16, 18)`);

    const legendItem = legend
      .selectAll("g")
      .data(data)
      .join("g")
      .attr("transform", (_, index) => {
        const column = Math.floor(index / 4);
        const row = index % 4;
        return `translate(${column * 140}, ${row * 24})`;
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
        return `${label} (${item[options.valueKey]})`;
      });
  }

  function drawHeatmapChart(selector, data, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    if (!Array.isArray(data) || data.length === 0) return renderEmptyState(container);

    const width = container.clientWidth || 640;
    const height = 280;
    const margin = { top: 26, right: 18, bottom: 50, left: 18 };
    const columns = 6;
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
    const width = container.clientWidth || 860;
    const columns = width >= 920 ? 4 : width >= 680 ? 3 : 2;
    const monthWidth = Math.floor((width - 24 * (columns - 1)) / columns);
    const cellSize = Math.max(11, Math.min(18, Math.floor((monthWidth - 46) / 7)));
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
      const offsetX = column * (monthWidth + 24);
      const offsetY = row * (monthHeight + 20);
      const monthStart = new Date(`${monthKey}-01T00:00:00`);
      const monthEnd = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0);
      const lastWeek = d3.timeMonday.count(d3.timeMonth(monthStart), monthEnd);
      const monthGroup = svg.append("g").attr("transform", `translate(${offsetX},${offsetY})`);

      monthGroup
        .append("text")
        .attr("class", "stats-calendar-month-label")
        .attr("x", 0)
        .attr("y", 14)
        .text(formatMonth.format(monthStart));

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
        .attr("height", (lastWeek + 1) * cellSize + 2);
    });
  }

  function renderEmptyState(container) {
    const empty = document.createElement("div");
    empty.className = "stats-empty";
    empty.textContent = config.labels.noData;
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

  function selectHourTicks(data) {
    if (!Array.isArray(data)) {
      return [];
    }

    return data
      .filter((item) => item.hour % 3 === 0 || item.hour === 23)
      .map((item) => item.hour);
  }

  function formatDateTimeDateOnly(value) {
    return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(`${value}T00:00:00`));
  }

  function dayIndexMonday(dateValue) {
    return (dateValue.getDay() + 6) % 7;
  }
})();
