(() => {
  const dataNode = document.getElementById("reportData");
  const data = dataNode ? JSON.parse(dataNode.textContent) : {};
  const one = (selector, root = document) => root.querySelector(selector);
  const all = (selector, root = document) => [...root.querySelectorAll(selector)];
  const rowsRoot = one("#matchRows");
  const rows = rowsRoot ? all(".match-row", rowsRoot) : [];
  const league = one("#leagueFilter");
  const search = one("#teamSearch");
  const sort = one("#sortFilter");
  const count = one("#visibleCount");
  let stateFilter = "all";
  let dialogOpener = null;

  const crestColors = [
    ["#3568A8", "#70A5FF"], ["#7B5A1D", "#D7A44B"], ["#246B52", "#42B88A"],
    ["#81403D", "#D36E68"], ["#58468A", "#957ED2"], ["#2A687D", "#55AFCB"],
  ];
  all(".crest[data-team]:not(.has-flag)").forEach((node) => {
    const name = node.dataset.team || "?";
    let hash = 0;
    for (const char of name) hash = (hash * 31 + char.codePointAt(0)) >>> 0;
    const colors = crestColors[hash % crestColors.length];
    node.style.background = `linear-gradient(135deg, ${colors[0]}, ${colors[1]})`;
    node.textContent = [...name][0] || "?";
  });

  function applyFilters() {
    const query = (search?.value || "").trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      const hidden = Boolean(
        (league?.value && row.dataset.league !== league.value) ||
        (stateFilter !== "all" && row.dataset.state !== stateFilter) ||
        (query && !row.dataset.search.includes(query))
      );
      row.hidden = hidden;
      if (!hidden) visible += 1;
    });
    if (count) count.textContent = `${visible} 场`;
  }

  function applySort() {
    if (!rowsRoot || !sort) return;
    const key = sort.value;
    const ordered = [...rows].sort((left, right) => {
      if (key === "edge") return Number(right.dataset.edge) - Number(left.dataset.edge);
      if (key === "confidence") return Number(right.dataset.confidence) - Number(left.dataset.confidence);
      return left.dataset.kickoff.localeCompare(right.dataset.kickoff);
    });
    ordered.forEach((row) => rowsRoot.appendChild(row));
  }

  league?.addEventListener("change", applyFilters);
  search?.addEventListener("input", applyFilters);
  sort?.addEventListener("change", applySort);
  all(".filter-button").forEach((button) => {
    button.addEventListener("click", () => {
      stateFilter = button.dataset.filter;
      all(".filter-button").forEach((item) => {
        const active = item === button;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      applyFilters();
    });
  });

  function activateTab(dialog, button) {
    const name = button.dataset.tab;
    const tabs = all('[role="tab"]', dialog);
    tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
    all(".tab-panel", dialog).forEach((panel) => {
      panel.hidden = panel.dataset.panel !== name;
    });
  }

  rows.forEach((row) => {
    row.addEventListener("click", () => {
      const dialog = document.getElementById(row.dataset.dialog);
      dialogOpener = row;
      dialog?.showModal();
    });
    row.addEventListener("keydown", (event) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const visibleRows = rows.filter((item) => !item.hidden);
      const index = visibleRows.indexOf(row);
      const target = event.key === "Home" ? 0
        : event.key === "End" ? visibleRows.length - 1
        : Math.max(0, Math.min(visibleRows.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)));
      visibleRows[target]?.focus();
    });
  });
  all(".match-dialog").forEach((dialog) => {
    one(".close-dialog", dialog)?.addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      dialogOpener?.focus();
      dialogOpener = null;
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    const tabs = all('[role="tab"]', dialog);
    tabs.forEach((button, index) => {
      button.addEventListener("click", () => activateTab(dialog, button));
      button.addEventListener("keydown", (event) => {
        const offset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!offset && !["Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const target = event.key === "Home" ? 0
          : event.key === "End" ? tabs.length - 1
          : (index + offset + tabs.length) % tabs.length;
        tabs[target].focus();
        activateTab(dialog, tabs[target]);
      });
    });
  });
  all(".print-button").forEach((button) => button.addEventListener("click", () => window.print()));

  all(".score-matrix").forEach((element) => {
    const matrix = JSON.parse(element.dataset.matrix || "[]");
    const size = Math.min(matrix.length, 7);
    const maximum = Math.max(0.0001, ...matrix.slice(0, size).flatMap((row) => row.slice(0, size)));
    const corner = document.createElement("span");
    corner.className = "matrix-axis corner";
    corner.textContent = "主\\客";
    element.appendChild(corner);
    for (let away = 0; away < size; away += 1) {
      const label = document.createElement("span");
      label.className = "matrix-axis";
      label.textContent = String(away);
      element.appendChild(label);
    }
    for (let home = 0; home < size; home += 1) {
      const label = document.createElement("span");
      label.className = "matrix-axis";
      label.textContent = String(home);
      element.appendChild(label);
      for (let away = 0; away < size; away += 1) {
        const probability = matrix[home][away];
        const cell = document.createElement("span");
        cell.className = "matrix-cell";
        cell.title = `${home}-${away}：${(probability * 100).toFixed(2)}%`;
        cell.setAttribute("aria-label", cell.title);
        cell.style.background = `rgba(76, 201, 240, ${0.08 + 0.68 * probability / maximum})`;
        cell.textContent = probability >= 0.015 ? `${(probability * 100).toFixed(0)}%` : "";
        element.appendChild(cell);
      }
    }
  });

  const svgNS = "http://www.w3.org/2000/svg";
  function svgElement(name, attributes) {
    const node = document.createElementNS(svgNS, name);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function addAxes(svg, xLabels, yLabels) {
    svg.appendChild(svgElement("line", { x1: 54, y1: 238, x2: 790, y2: 238, class: "chart-axis" }));
    svg.appendChild(svgElement("line", { x1: 54, y1: 28, x2: 54, y2: 238, class: "chart-axis" }));
    yLabels.forEach(({ y, label }) => {
      svg.appendChild(svgElement("line", { x1: 54, y1: y, x2: 790, y2: y, class: "chart-guide" }));
      const text = svgElement("text", { x: 48, y: y + 4, class: "chart-label", "text-anchor": "end" });
      text.textContent = label;
      svg.appendChild(text);
    });
    xLabels.forEach(({ x, label }) => {
      const text = svgElement("text", { x, y: 258, class: "chart-label", "text-anchor": "middle" });
      text.textContent = label;
      svg.appendChild(text);
    });
  }

  const equity = one("#equityChart");
  if (equity && data.backtest) {
    const values = data.backtest.equity_curve || [];
    const drawdowns = data.backtest.drawdown_curve || [];
    if (values.length) {
      const min = Math.min(0, ...values), max = Math.max(0, ...values);
      const span = max - min || 1;
      const x = (index) => 54 + index * 736 / Math.max(1, values.length - 1);
      const y = (value) => 238 - (value - min) * 200 / span;
      addAxes(
        equity,
        [{ x: 54, label: "0" }, { x: 422, label: String(Math.floor(values.length / 2)) }, { x: 790, label: String(values.length - 1) }],
        [0, 0.5, 1].map((ratio) => ({
          y: 238 - ratio * 200,
          label: `${((min + ratio * span) * 100).toFixed(0)}%`,
        })),
      );
      const path = svgElement("path", {
        d: values.map((value, index) => `${index ? "L" : "M"}${x(index)},${y(value)}`).join(" "),
        class: "chart-line",
      });
      equity.appendChild(path);
      if (drawdowns.length === values.length) {
        const maxDrawdown = Math.max(0.0001, ...drawdowns);
        const drawdownPath = svgElement("path", {
          d: drawdowns.map((value, index) => `${index ? "L" : "M"}${x(index)},${238 - value * 90 / maxDrawdown}`).join(" "),
          class: "chart-line secondary",
        });
        equity.appendChild(drawdownPath);
      }
    }
  }

  const reliability = one("#reliabilityChart");
  if (reliability && data.backtest) {
    const rowsData = data.backtest.reliability || [];
    const x = (value) => 54 + value * 736;
    const y = (value) => 238 - value * 200;
    addAxes(
      reliability,
      [0, 0.5, 1].map((value) => ({ x: x(value), label: `${Math.round(value * 100)}%` })),
      [0, 0.5, 1].map((value) => ({ y: y(value), label: `${Math.round(value * 100)}%` })),
    );
    reliability.appendChild(svgElement("line", { x1: x(0), y1: y(0), x2: x(1), y2: y(1), class: "chart-guide" }));
    if (rowsData.length) {
      const path = svgElement("path", {
        d: rowsData.map((row, index) => `${index ? "L" : "M"}${x(row.predicted ?? (row.lower + row.upper) / 2)},${y(row.actual)}`).join(" "),
        class: "chart-line",
      });
      reliability.appendChild(path);
      rowsData.forEach((row) => {
        reliability.appendChild(svgElement("circle", {
          cx: x(row.predicted ?? (row.lower + row.upper) / 2),
          cy: y(row.actual),
          r: Math.max(3, Math.min(8, Math.sqrt(row.count))),
          class: "chart-point",
        }));
      });
    }
  }
})();
