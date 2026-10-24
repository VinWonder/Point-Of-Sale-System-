/* Dashboard charts. Colours: reference palette slot 1 for the current series, muted dashed grey
   for the comparison; text uses ink tokens, never the series colour. */
(function () {
    const data = JSON.parse(document.getElementById('chart-data').textContent);
    const SERIES = '#2a78d6', COMPARE = '#9ca3af', INK = '#52514e', GRID = '#eef0f3';
    const kes = v => 'KES ' + Number(v).toLocaleString('en-KE', { maximumFractionDigits: 0 });
    const kesShort = v => v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : v >= 1e3 ? Math.round(v / 1e3) + 'K' : String(v);

    Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = INK;
    Chart.defaults.plugins.legend.display = false;   // HTML legends sit in the panel headers
    Chart.defaults.maintainAspectRatio = false;
    Chart.defaults.plugins.tooltip.backgroundColor = '#0f172a';
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;

    const valueAxis = { grid: { color: GRID }, border: { display: false }, beginAtZero: true,
                        ticks: { callback: v => kesShort(v), maxTicksLimit: 5 } };
    const catAxis = { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 14 } };

    // Revenue: this period vs previous
    const ctx = document.getElementById('revenueChart');
    if (ctx) {
        const fill = ctx.getContext('2d').createLinearGradient(0, 0, 0, 300);
        fill.addColorStop(0, 'rgba(42,120,214,0.20)');
        fill.addColorStop(1, 'rgba(42,120,214,0)');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [
                    { label: 'This period', data: data.current, borderColor: SERIES, backgroundColor: fill, fill: true,
                      borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 6, pointHitRadius: 12,
                      pointBackgroundColor: SERIES, pointBorderColor: '#fff', pointBorderWidth: 2 },
                    { label: data.compareLabel, data: data.previous, borderColor: COMPARE, borderDash: [5, 4],
                      borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 12, fill: false },
                ],
            },
            options: {
                interaction: { mode: 'index', intersect: false },
                plugins: { tooltip: { callbacks: {
                    label: c => `${c.dataset.label}: ${kes(c.parsed.y)}` + (c.datasetIndex === 0 ? ` · ${data.counts[c.dataIndex]} sales` : ''),
                } } },
                scales: { y: valueAxis, x: catAxis },
            },
        });
    }

    const bars = (id, labels, values, horizontal, fmt) => {
        const el = document.getElementById(id);
        if (!el) return;
        new Chart(el, {
            type: 'bar',
            data: { labels, datasets: [{ data: values, backgroundColor: SERIES, borderRadius: 4, borderSkipped: 'start',
                                         barPercentage: 0.75, categoryPercentage: 0.85 }] },
            options: {
                indexAxis: horizontal ? 'y' : 'x',
                plugins: { tooltip: { callbacks: { label: c => fmt(horizontal ? c.parsed.x : c.parsed.y) } } },
                scales: horizontal
                    ? { x: { ...valueAxis }, y: { ...catAxis, ticks: { autoSkip: false } } }
                    : { y: { ...valueAxis, ticks: { precision: 0, maxTicksLimit: 4 } }, x: catAxis },
            },
        });
    };
    bars('hoursChart', data.hours.map(h => String(h.hour).padStart(2, '0')), data.hours.map(h => h.count), false,
         v => `${v} sale${v === 1 ? '' : 's'}`);
    bars('categoryChart', data.categories.map(c => c.name), data.categories.map(c => c.revenue), true, kes);

    // Keep the numbers current on a till screen left open all day.
    setInterval(() => {
        const palette = document.querySelector('.palette-backdrop');
        const paletteOpen = palette && getComputedStyle(palette).display !== 'none';
        const typing = ['INPUT', 'SELECT', 'TEXTAREA'].includes((document.activeElement || {}).tagName);
        if (document.visibilityState === 'visible' && !paletteOpen && !typing) window.location.reload();
    }, 120000);
})();
