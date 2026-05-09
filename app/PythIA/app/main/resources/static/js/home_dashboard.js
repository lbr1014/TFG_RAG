(function () {
  const config = window.PYTHIA_HOME_DASHBOARD;
  if (!config || typeof d3 === "undefined") {
    return;
  }

  const tooltip = createTooltip();

  renderCharts();

  const resizeHandler = debounce(renderCharts, 180);
  if ("ResizeObserver" in window) {
    const observer = new ResizeObserver(resizeHandler);
    document.querySelectorAll(".home-calendar-chart, .home-query-donut-chart").forEach((node) => observer.observe(node));
  } else {
    window.addEventListener("resize", resizeHandler);
  }

  function renderCharts() {
    drawCalendar();
    drawDonut();
  }

  function drawCalendar() {
    const container = document.querySelector("#homeCalendarChart");
    if (!container) return;
    container.innerHTML = "";

    const weeks = Array.isArray(config.calendar?.weeks) ? config.calendar.weeks : [];
    const weekdays = Array.isArray(config.calendar?.weekdays) ? config.calendar.weekdays : [];
    if (!weeks.length) return;

    const width = Math.max(240, Math.round(container.getBoundingClientRect().width || 300));
    const gap = width < 300 ? 5 : 7;
    const margin = { top: 20, right: 4, bottom: 4, left: 4 };
    const cellSize = Math.floor((width - margin.left - margin.right - gap * 6) / 7);
    const height = margin.top + weeks.length * cellSize + Math.max(0, weeks.length - 1) * gap + margin.bottom;
    const days = weeks.flatMap((week, weekIndex) =>
      week.map((day, dayIndex) => ({ ...day, weekIndex, dayIndex }))
    );
    const maxCount = d3.max(days, (day) => Number(day.count) || 0) || 0;
    const colorScale = d3
      .scaleLinear()
      .domain([0, Math.max(1, maxCount / 2), Math.max(1, maxCount)])
      .range(["rgba(255,255,255,0.12)", "#85c1e9", "#21618c"]);

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img");

    svg
      .append("g")
      .selectAll("text")
      .data(weekdays)
      .join("text")
      .attr("class", "home-calendar-weekday-d3")
      .attr("x", (_, index) => margin.left + index * (cellSize + gap) + cellSize / 2)
      .attr("y", 11)
      .attr("text-anchor", "middle")
      .text((label) => String(label).slice(0, 1));

    const dayGroup = svg
      .append("g")
      .selectAll("g")
      .data(days)
      .join("g")
      .attr("transform", (day) => {
        const x = margin.left + day.dayIndex * (cellSize + gap);
        const y = margin.top + day.weekIndex * (cellSize + gap);
        return `translate(${x},${y})`;
      });

    dayGroup
      .filter((day) => !day.empty)
      .append("rect")
      .attr("class", (day) => `home-calendar-cell-d3${day.is_today ? " is-today" : ""}`)
      .attr("width", cellSize)
      .attr("height", cellSize)
      .attr("rx", 6)
      .attr("fill", (day) => colorScale(Number(day.count) || 0))
      .on("mousemove", function (event, day) {
        showTooltip(event, `${day.date}: ${day.count} ${config.labels?.queryUnit || ""}`.trim());
        d3.select(this).attr("opacity", 0.86);
      })
      .on("mouseleave", function () {
        hideTooltip();
        d3.select(this).attr("opacity", 1);
      });

    dayGroup
      .filter((day) => !day.empty)
      .append("text")
      .attr("class", "home-calendar-day-label-d3")
      .attr("x", cellSize / 2)
      .attr("y", cellSize / 2 + 4)
      .attr("text-anchor", "middle")
      .text((day) => day.day);
  }

  function drawDonut() {
    const container = document.querySelector("#homeQueryDonutChart");
    const legend = document.querySelector("#homeQueryDonutLegend");
    if (!container) return;
    container.innerHTML = "";
    if (legend) legend.innerHTML = "";

    const rawSegments = Array.isArray(config.donut?.segments) ? config.donut.segments : [];
    const segments = rawSegments.filter((item) => Number(item.count) > 0);
    const total = Number(config.donut?.total) || 0;
    const centerTotal = Number(config.donut?.centerTotal) || 0;
    const width = Math.max(260, Math.round(container.getBoundingClientRect().width || 320));
    const size = Math.min(300, width);
    const radius = size / 2 - 14;
    const innerRadius = radius * 0.55;

    const svg = d3
      .select(container)
      .append("svg")
      .attr("viewBox", `0 0 ${size} ${size}`)
      .attr("role", "img");

    const chart = svg.append("g").attr("transform", `translate(${size / 2},${size / 2})`);

    if (!segments.length || total === 0) {
      chart
        .append("circle")
        .attr("r", radius)
        .attr("fill", "rgba(255,255,255,0.14)");
    } else {
      const pieData = d3.pie().sort(null).value((item) => Number(item.count) || 0)(segments);
      const arc = d3.arc().innerRadius(innerRadius).outerRadius(radius);
      const hoverArc = d3.arc().innerRadius(innerRadius).outerRadius(radius + 6);

      chart
        .selectAll("path")
        .data(pieData)
        .join("path")
        .attr("d", arc)
        .attr("fill", (item) => item.data.color)
        .attr("stroke", "rgba(255,255,255,0.32)")
        .attr("stroke-width", 1.5)
        .on("mousemove", function (event, item) {
          showTooltip(event, `${item.data.label}: ${item.data.count}`);
          d3.select(this).attr("d", hoverArc);
        })
        .on("mouseleave", function () {
          hideTooltip();
          d3.select(this).attr("d", arc);
        });
    }

    chart
      .append("circle")
      .attr("r", innerRadius)
      .attr("fill", "rgba(15, 23, 42, 0.84)");

    chart
      .append("text")
      .attr("class", "home-donut-total-d3")
      .attr("text-anchor", "middle")
      .attr("y", 10)
      .text(centerTotal);

    if (legend && segments.length) {
      const legendItems = d3.select(legend)
        .selectAll("span")
        .data(segments)
        .join("span")
        .attr("class", "home-query-donut-legend-item");

      legendItems
        .append("span")
        .attr("class", "home-query-donut-legend-swatch")
        .style("background", (item) => item.color);

      legendItems
        .append("span")
        .text((item) => `${item.label}: ${item.count}`);
    } else if (legend) {
      legend.textContent = config.labels?.noData || "";
    }
  }

  function createTooltip() {
    const element = document.createElement("div");
    element.className = "home-dashboard-tooltip";
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

  function debounce(fn, wait) {
    let timeout = null;
    return () => {
      if (timeout) {
        window.clearTimeout(timeout);
      }
      timeout = window.setTimeout(() => {
        timeout = null;
        fn();
      }, wait);
    };
  }
})();
