// Draws each canvas from a JSON block in the page. Colours follow one fixed order per series,
// so a series keeps its colour across pages. The table under the chart holds the same values.
(function () {
  var SERIES_COLOURS = ["#2a78d6", "#eb6834"];
  var money = new Intl.NumberFormat("ro-RO", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    var source = document.getElementById(canvas.dataset.chart);
    if (!source || !window.Chart) { return; }
    var payload = JSON.parse(source.textContent);
    new window.Chart(canvas, {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: payload.datasets.map(function (dataset, index) {
          return {
            label: dataset.label,
            data: dataset.data,
            backgroundColor: SERIES_COLOURS[index],
            borderRadius: { topLeft: 4, topRight: 4 },
            borderSkipped: "bottom",
            maxBarThickness: 24,
            categoryPercentage: 0.7,
            barPercentage: 0.9
          };
        })
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "top", align: "start", labels: { usePointStyle: true, boxHeight: 8 } },
          tooltip: {
            callbacks: {
              label: function (item) { return item.dataset.label + ": " + money.format(item.parsed.y) + " lei"; }
            }
          }
        },
        scales: {
          x: { grid: { display: false } },
          y: {
            beginAtZero: true,
            grid: { color: "#e3e8f0" },
            ticks: { callback: function (value) { return money.format(value); } }
          }
        }
      }
    });
  });
})();
