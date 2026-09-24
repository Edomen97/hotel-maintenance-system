/* ══════════════════════════════════════════════════════
   Rori Hotel — Dashboard Chart.js Config
   ══════════════════════════════════════════════════════ */
(function () {
  'use strict';

  function init() {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not loaded — charts skipped');
      return;
    }

    const DATA = window.RORI_DATA || {};
    console.log('RORI_DATA loaded:', DATA);

    Chart.defaults.color = '#AAB4C3';
    Chart.defaults.borderColor = 'rgba(197,160,89,0.15)';
    Chart.defaults.font.family = "'Inter', system-ui, -apple-system, sans-serif";
    Chart.defaults.font.size = 11;

    const tooltipStyle = {
      backgroundColor: 'rgba(7,20,38,0.96)',
      borderColor: 'rgba(197,160,89,0.45)',
      borderWidth: 1,
      titleColor: '#fff',
      bodyColor: '#e5e7eb',
      padding: 12,
      cornerRadius: 10,
      displayColors: true,
      boxPadding: 6,
    };

    const GOLD = 'rgba(197,160,89,1)';
    const GOLD_BRIGHT = 'rgba(212,175,55,1)';
    const BLUE = 'rgba(59,130,246,1)';
    const PINK = 'rgba(236,72,153,1)';
    const GREEN = 'rgba(16,185,129,1)';

    function gradient(ctx, c1, c2, h) {
      const g = ctx.createLinearGradient(0, 0, 0, h || 300);
      g.addColorStop(0, c1);
      g.addColorStop(1, c2);
      return g;
    }

    function emptyState(el, icon, message) {
      if (!el) return;
      const wrap = el.parentElement;
      if (!wrap) return;
      wrap.innerHTML = '<div class="rori-empty"><i class="fas ' + icon +
        '"></i>' + message + '</div>';
    }

    /* ─────── TRENDS ─────── */
    (function renderTrends() {
      const el = document.getElementById('chart-trends');
      if (!el) return;
      const t = DATA.trends;
      if (!t || !t.labels || !t.labels.length) {
        emptyState(el, 'fa-chart-line', 'No data for the selected filters.');
        return;
      }
      const ctx = el.getContext('2d');
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: t.labels,
          datasets: [
            {
              label: 'Total',
              data: t.total,
              borderColor: GOLD,
              backgroundColor: gradient(ctx, 'rgba(197,160,89,0.35)', 'rgba(197,160,89,0.02)', 340),
              fill: true,
              tension: 0.4,
              borderWidth: 2.5,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: GOLD,
              pointHoverBorderColor: '#fff',
              pointHoverBorderWidth: 2,
            },
            {
              label: 'Completed',
              data: t.completed,
              borderColor: GREEN,
              backgroundColor: 'transparent',
              fill: false,
              tension: 0.4,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: GREEN,
            },
            {
              label: 'Pending',
              data: t.pending,
              borderColor: PINK,
              backgroundColor: 'transparent',
              fill: false,
              tension: 0.4,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: PINK,
            },
            {
              label: 'In Progress',
              data: t.in_progress,
              borderColor: BLUE,
              backgroundColor: 'transparent',
              fill: false,
              tension: 0.4,
              borderWidth: 2,
              pointRadius: 0,
              pointHoverRadius: 5,
              pointHoverBackgroundColor: BLUE,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { intersect: false, mode: 'index' },
          plugins: {
            legend: {
              position: 'top',
              align: 'end',
              labels: {
                boxWidth: 8, boxHeight: 8, padding: 16,
                usePointStyle: true, pointStyle: 'circle',
              },
            },
            tooltip: tooltipStyle,
          },
          scales: {
            x: {
              grid: { color: 'rgba(197,160,89,0.06)', drawBorder: false },
              ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 },
            },
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(197,160,89,0.08)', drawBorder: false },
              ticks: { precision: 0 },
            },
          },
        },
      });
    })();

    /* ─────── CATEGORIES DONUT ─────── */
    (function renderCategories() {
      const el = document.getElementById('chart-categories');
      if (!el) return;
      const c = DATA.categories;
      if (!c || !c.labels || !c.labels.length) {
        emptyState(el, 'fa-chart-pie', 'No category data available.');
        return;
      }
      const palette = ['#C5A059', '#D4AF37', '#3B82F6', '#10B981', '#F59E0B',
                       '#06B6D4', '#EC4899', '#8B5CF6', '#F472B6', '#22C55E'];
      new Chart(el.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: c.labels,
          datasets: [{
            data: c.values,
            backgroundColor: palette,
            borderColor: '#0F2540',
            borderWidth: 3,
            hoverOffset: 10,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: {
              position: 'right',
              labels: {
                boxWidth: 8, boxHeight: 8, padding: 10,
                usePointStyle: true, pointStyle: 'circle',
                font: { size: 10 },
              },
            },
            tooltip: {
              ...tooltipStyle,
              callbacks: {
                label: function (ctx) {
                  const pct = c.percentages[ctx.dataIndex];
                  return ' ' + ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
                },
              },
            },
          },
        },
      });
    })();

    /* ─────── STATUS DONUT ─────── */
    (function renderStatuses() {
      const el = document.getElementById('chart-status');
      if (!el) return;
      const s = DATA.statuses;
      if (!s || !s.labels || !s.labels.length) {
        emptyState(el, 'fa-chart-pie', 'No status data available.');
        return;
      }
      const map = {
        'Pending': '#F59E0B',
        'Approved': '#3B82F6',
        'Assigned': '#C5A059',
        'In Progress': '#06B6D4',
        'Completed': '#10B981',
        'Verified': '#22C55E',
        'Closed': '#16A34A',
        'Rejected': '#EF4444',
        'Overdue': '#DC2626',
      };
      const colors = s.labels.map(l => map[l] || '#AAB4C3');
      new Chart(el.getContext('2d'), {
        type: 'doughnut',
        data: {
          labels: s.labels,
          datasets: [{
            data: s.values,
            backgroundColor: colors,
            borderColor: '#0F2540',
            borderWidth: 3,
            hoverOffset: 10,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '68%',
          plugins: {
            legend: {
              position: 'right',
              labels: {
                boxWidth: 8, boxHeight: 8, padding: 10,
                usePointStyle: true, pointStyle: 'circle',
                font: { size: 10 },
              },
            },
            tooltip: {
              ...tooltipStyle,
              callbacks: {
                label: function (ctx) {
                  const pct = s.percentages[ctx.dataIndex];
                  return ' ' + ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
                },
              },
            },
          },
        },
      });
    })();

    /* ─────── DEPARTMENT BAR ─────── */
    (function renderDepartments() {
      const el = document.getElementById('chart-departments');
      if (!el) return;
      const d = DATA.departments;
      if (!d || !d.labels || !d.labels.length) {
        emptyState(el, 'fa-chart-bar', 'No department data available.');
        return;
      }
      const ctx = el.getContext('2d');
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: d.labels,
          datasets: [{
            label: 'Requests',
            data: d.values,
            backgroundColor: gradient(ctx, 'rgba(197,160,89,0.95)', 'rgba(11,31,58,0.55)', 300),
            borderRadius: 8,
            borderSkipped: false,
            maxBarThickness: 36,
          }],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: tooltipStyle,
          },
          scales: {
            x: {
              beginAtZero: true,
              grid: { color: 'rgba(197,160,89,0.08)', drawBorder: false },
              ticks: { precision: 0 },
            },
            y: {
              grid: { display: false },
              ticks: { font: { size: 11 } },
            },
          },
        },
      });
    })();

    /* ─────── SIDEBAR TOGGLE ─────── */
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('rori-sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (toggle && sidebar) {
      toggle.addEventListener('click', function () {
        sidebar.classList.toggle('open');
        if (backdrop) backdrop.classList.toggle('show');
      });
    }
    if (backdrop && sidebar) {
      backdrop.addEventListener('click', function () {
        sidebar.classList.remove('open');
        backdrop.classList.remove('show');
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(); 