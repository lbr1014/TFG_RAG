(function () {
  const config = window.PYTHIA_MODEL_STATS;
  if (!config || typeof d3 === "undefined") {
    return;
  }

  const tooltip = createTooltip();
  const data = Array.isArray(config.data.models) ? config.data.models : [];

  drawCharts();

  const redraw = debounce(drawCharts, 180);
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(redraw);
    document.querySelectorAll(".stats-chart").forEach((container) => observer.observe(container));
  } else {
    window.addEventListener("resize", redraw);
  }

  function drawCharts() {
    drawBarChart("#chart-model-uses", data, {
      xKey: "model",
      yKey: "uses",
      color: "#5dade2",
      tooltipFormatter: (item) =>
        `${item.model}\n${config.labels.uses}: ${item.uses}\n${config.labels.users}: ${item.users}`,
    });

    drawBarChart("#chart-model-tokens", data, {
      xKey: "model",
      yKey: "tokens",
      color: "#58d68d",
      tooltipFormatter: (item) => `${item.model}\n${config.labels.tokens}: ${formatNumber(item.tokens)}`,
    });

    drawBarChart("#chart-model-time", data, {
      xKey: "model",
      yKey: "avg_time",
      color: "#f5b041",
      tooltipFormatter: (item) => `${item.model}\n${config.labels.avgTime}: ${item.avg_time} ${config.labels.seconds}`,
    });

    drawDeviceChart("#chart-model-device", data);
  }

  function drawBarChart(selector, chartData, options) {
    const container = document.querySelector(selector);
    if (!container) return;
    container.innerHTML = "";
    if (!chartData.length) return renderEmptyState(container);

    const width = chartWidth(container, 720);
    const narrow = width < 520;
    const height = narrow ? 300 : 320;
    const margin = { top: 18, right: narrow ? 10 : 18, bottom: 96, left: narrow ? 46 : 64 };
    const xScale = d3
      .scaleBand()
      .domain(chartData.map((item) => item[options.xKey]))
      .range([margin.left, width - margin.right])
      .padding(0.22);
    const yScale = d3
      .scaleLinear()
      .domain([0, d3.max(chartData, (item) => Number(item[options.yKey]) || 0) || 1])
      .nice()
      .range([height - margin.bottom, margin.top]);

    const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img");

    svg
      .append("g")
      .attr("class", "stats-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickSize(-(width - margin.left - margin.right)).tickFormat(""))
      .call((group) => group.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(xScale).tickFormat((value) => truncateLabel(value, narrow ? 12 : 22)))
      .call((group) => {
        group.select(".domain").remove();
        group
          .selectAll("text")
          .style("text-anchor", "end")
          .attr("transform", "rotate(-35)")
          .attr("dx", "-0.55em")
          .attr("dy", "0.2em");
      });

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickFormat(formatCompact))
      .call((group) => group.select(".domain").remove());

    svg
      .append("g")
      .selectAll("rect")
      .data(chartData)
      .join("rect")
      .attr("x", (item) => xScale(item[options.xKey]))
      .attr("y", (item) => yScale(Number(item[options.yKey]) || 0))
      .attr("width", xScale.bandwidth())
      .attr("height", (item) => yScale(0) - yScale(Number(item[options.yKey]) || 0))
      .attr("rx", 8)
      .attr("fill", options.color)
      .on("mousemove", function (event, item) {
        showTooltip(event, options.tooltipFormatter(item));
        d3.select(this).attr("opacity", 0.82);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("opacity", 1);
      });
  }

  function drawDeviceChart(selector, chartData) {
    const container = document.querySelector(selector);
    if (!container) return;
    container.innerHTML = "";
    if (!chartData.length) return renderEmptyState(container);

    const width = chartWidth(container, 720);
    const narrow = width < 560;
    const height = narrow ? 340 : 360;
    const margin = { top: 18, right: 18, bottom: 104, left: narrow ? 46 : 64 };
    const deviceKeys = ["cpu", "gpu"];
    const colorScale = d3
      .scaleOrdinal()
      .domain(deviceKeys)
      .range(["#ec7063", "#48c9b0"]);
    const x0 = d3.scaleBand().domain(chartData.map((item) => item.model)).range([margin.left, width - margin.right]).padding(0.2);
    const x1 = d3.scaleBand().domain(deviceKeys).range([0, x0.bandwidth()]).padding(0.12);
    const yScale = d3
      .scaleLinear()
      .domain([0, d3.max(chartData, (item) => d3.max(deviceKeys, (key) => Number(item[key]) || 0)) || 1])
      .nice()
      .range([height - margin.bottom, margin.top]);

    const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("role", "img");

    svg
      .append("g")
      .attr("class", "stats-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5).tickSize(-(width - margin.left - margin.right)).tickFormat(""))
      .call((group) => group.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(yScale).ticks(5))
      .call((group) => group.select(".domain").remove());

    svg
      .append("g")
      .attr("class", "stats-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x0).tickFormat((value) => truncateLabel(value, narrow ? 12 : 22)))
      .call((group) => {
        group.select(".domain").remove();
        group
          .selectAll("text")
          .style("text-anchor", "end")
          .attr("transform", "rotate(-35)")
          .attr("dx", "-0.55em")
          .attr("dy", "0.2em");
      });

    svg
      .append("g")
      .selectAll("g")
      .data(chartData)
      .join("g")
      .attr("transform", (item) => `translate(${x0(item.model)},0)`)
      .selectAll("rect")
      .data((item) => deviceKeys.map((key) => ({ model: item.model, key, value: Number(item[key]) || 0 })))
      .join("rect")
      .attr("x", (item) => x1(item.key))
      .attr("y", (item) => yScale(item.value))
      .attr("width", x1.bandwidth())
      .attr("height", (item) => yScale(0) - yScale(item.value))
      .attr("rx", 6)
      .attr("fill", (item) => colorScale(item.key))
      .on("mousemove", function (event, item) {
        showTooltip(event, `${item.model}\n${deviceLabel(item.key)}: ${item.value}`);
        d3.select(this).attr("opacity", 0.82);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("opacity", 1);
      });

    const legend = svg.append("g").attr("transform", `translate(${margin.left}, ${height - 24})`);
    legend
      .selectAll("g")
      .data(deviceKeys)
      .join("g")
      .attr("transform", (_, index) => `translate(${index * 112},0)`)
      .call((group) => {
        group.append("rect").attr("width", 14).attr("height", 14).attr("rx", 3).attr("fill", (key) => colorScale(key));
        group.append("text").attr("x", 20).attr("y", 12).attr("fill", "currentColor").attr("font-size", 12).text(deviceLabel);
      });
  }

  function deviceLabel(key) {
    if (key === "cpu") return config.labels.cpu;
    if (key === "gpu") return config.labels.gpu;
    return config.labels.unknown;
  }

  function chartWidth(container, fallback) {
    return Math.max(280, Math.round(container.getBoundingClientRect().width || container.clientWidth || fallback || 640));
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

  function truncateLabel(value, maxLength) {
    const label = String(value || "");
    return label.length <= maxLength ? label : `${label.slice(0, Math.max(1, maxLength - 3))}...`;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value) || 0);
  }

  function formatCompact(value) {
    return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(Number(value) || 0);
  }

  function debounce(fn, wait) {
    let timeout = null;
    return () => {
      if (timeout) window.clearTimeout(timeout);
      timeout = window.setTimeout(() => {
        timeout = null;
        fn();
      }, wait);
    };
  }
})();
