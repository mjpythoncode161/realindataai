content = """\
{% extends "base.html" %}
{% load user_roles %}
{% block title %}Dashboard{% endblock %}

{% block content %}
<div class="content-header">
  <div class="container-fluid">
    <div class="row mb-2">
      <div class="col-sm-6">
        <h1 class="m-0"><i class="fas fa-tachometer-alt mr-2"></i>Dashboard</h1>
      </div>
      <div class="col-sm-6">
        <ol class="breadcrumb float-sm-right">
          <li class="breadcrumb-item active">
            <i class="fas fa-user mr-1"></i>{{ request.user.get_full_name|default:request.user.username }}
            &nbsp;&mdash;&nbsp;{{ request.user.role|title }}
            &nbsp;&nbsp;<i class="fas fa-calendar-day mr-1"></i>{% now "d M Y" %}
          </li>
        </ol>
      </div>
    </div>
  </div>
</div>

<section class="content">
  <div class="container-fluid">

    <!-- Row 1: KPI info-box cards -->
    {% if request.user|has_any_role:"admin,manager,followup,executive,telecaller" %}
    <div class="row">

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'customer_list' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-info elevation-1"><i class="fas fa-users"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Total Customers</span>
              <span class="info-box-number">{{ total_customers|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'booking_list' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-success elevation-1"><i class="fas fa-clipboard-check"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Total Bookings</span>
              <span class="info-box-number">{{ total_bookings|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'booking_list' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-warning elevation-1"><i class="fas fa-times-circle"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Cancelled Bookings</span>
              <span class="info-box-number">{{ total_cancellations|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'booking_list' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-primary elevation-1"><i class="fas fa-rupee-sign"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Revenue Collected</span>
              <span class="info-box-number">&#8377;{{ total_revenue|floatformat:0 }}</span>
            </div>
          </div>
        </a>
      </div>

    </div>
    {% endif %}

    <!-- Row 2: Follow-up urgency info-box cards -->
    {% if request.user|has_any_role:"admin,manager,followup,executive,telecaller" %}
    <div class="row">

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'follow_up_report' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-danger elevation-1"><i class="fas fa-fire"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Follow-up Due Today</span>
              <span class="info-box-number">{{ followups_today|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'follow_up_report' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-orange elevation-1"><i class="fas fa-clock"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Follow-up Next 7 Days</span>
              <span class="info-box-number">{{ followups_7|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'follow_up_report' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-yellow elevation-1"><i class="fas fa-calendar-check"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Follow-up Next 15 Days</span>
              <span class="info-box-number">{{ followups_15|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

      <div class="col-lg-3 col-md-6 col-sm-6 col-12">
        <a href="{% url 'follow_up_report' %}" class="text-decoration-none text-dark">
          <div class="info-box">
            <span class="info-box-icon bg-success elevation-1"><i class="fas fa-calendar-alt"></i></span>
            <div class="info-box-content">
              <span class="info-box-text">Follow-up Next 30 Days</span>
              <span class="info-box-number">{{ followups_30|default:"0" }}</span>
            </div>
          </div>
        </a>
      </div>

    </div>
    {% endif %}

    <!-- Charts -->
    {% if request.user|has_any_role:"admin,manager,followup" %}
    <div class="row">

      <div class="col-lg-8">
        <div class="card card-primary card-outline">
          <div class="card-header">
            <h3 class="card-title"><i class="fas fa-chart-bar mr-1"></i>Bookings &amp; Revenue <small class="text-muted">(Last 6 months)</small></h3>
            <div class="card-tools">
              <button type="button" class="btn btn-tool" data-card-widget="collapse"><i class="fas fa-minus"></i></button>
            </div>
          </div>
          <div class="card-body">
            <canvas id="bookingChart" style="min-height:220px;height:220px;max-height:220px;max-width:100%;"></canvas>
          </div>
        </div>
      </div>

      <div class="col-lg-4">
        <div class="card card-success card-outline">
          <div class="card-header">
            <h3 class="card-title"><i class="fas fa-chart-pie mr-1"></i>Bookings by Project</h3>
            <div class="card-tools">
              <button type="button" class="btn btn-tool" data-card-widget="collapse"><i class="fas fa-minus"></i></button>
            </div>
          </div>
          <div class="card-body">
            {% if project_labels_json != "[]" %}
            <canvas id="projectChart" style="min-height:220px;height:220px;max-height:220px;max-width:100%;"></canvas>
            {% else %}
            <p class="text-center text-muted mt-4"><i class="fas fa-info-circle mr-1"></i>No active bookings yet</p>
            {% endif %}
          </div>
        </div>
      </div>

    </div>
    {% endif %}

    <!-- Recent Bookings -->
    {% if request.user|has_any_role:"admin,manager,followup" %}
    <div class="row">
      <div class="col-12">
        <div class="card card-info card-outline">
          <div class="card-header">
            <h3 class="card-title"><i class="fas fa-list mr-1"></i>Recent Bookings</h3>
            <div class="card-tools">
              <a href="{% url 'booking_list' %}" class="btn btn-sm btn-info">View All <i class="fas fa-arrow-right ml-1"></i></a>
            </div>
          </div>
          <div class="card-body p-0 table-responsive">
            <table class="table table-hover table-sm mb-0">
              <thead class="thead-light">
                <tr>
                  <th>#</th><th>Customer</th><th>Phone</th><th>Project</th><th>Date</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {% for booking in recent_bookings %}
                <tr>
                  <td>{{ forloop.counter }}</td>
                  <td><strong>{{ booking.customer_full_name }}</strong></td>
                  <td>{{ booking.customer_phone }}</td>
                  <td>{{ booking.p_id.name|default:"-" }}</td>
                  <td>{{ booking.booking_date|date:"d M Y" }}</td>
                  <td>
                    {% if booking.status == 'ACTIVE' %}
                      <span class="badge badge-success">Active</span>
                    {% else %}
                      <span class="badge badge-danger">{{ booking.get_status_display }}</span>
                    {% endif %}
                  </td>
                </tr>
                {% empty %}
                <tr><td colspan="6" class="text-center text-muted py-3">No bookings found</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    {% endif %}

    <!-- Upcoming Holidays -->
    {% if upcoming_holidays %}
    <div class="row">
      <div class="col-12">
        <div class="card card-warning card-outline">
          <div class="card-header">
            <h3 class="card-title"><i class="fas fa-calendar-day mr-1"></i>Upcoming Holidays</h3>
          </div>
          <div class="card-body p-0 table-responsive">
            <table class="table table-sm mb-0">
              <thead class="thead-light"><tr><th>Holiday</th><th>Date</th></tr></thead>
              <tbody>
                {% for h in upcoming_holidays %}
                <tr><td>{{ h.holiday_tital }}</td><td>{{ h.holiday_date }}</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    {% endif %}

  </div>
</section>
{% endblock %}

{% block extra_scripts %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script>
(function () {
  var mL = {{ monthly_labels_json|safe }};
  var mB = {{ monthly_bookings_json|safe }};
  var mR = {{ monthly_revenue_json|safe }};
  var pL = {{ project_labels_json|safe }};
  var pC = {{ project_counts_json|safe }};

  var bCtx = document.getElementById('bookingChart');
  if (bCtx) {
    new Chart(bCtx, {
      type: 'bar',
      data: {
        labels: mL,
        datasets: [
          {
            label: 'Bookings', data: mB,
            backgroundColor: 'rgba(60,141,188,0.25)', borderColor: '#3c8dbc',
            borderWidth: 2, borderRadius: 4, yAxisID: 'y', type: 'bar'
          },
          {
            label: 'Revenue', data: mR,
            borderColor: '#00a65a', backgroundColor: 'rgba(0,166,90,0.08)',
            borderWidth: 2, pointRadius: 4, pointBackgroundColor: '#00a65a',
            tension: 0.4, fill: true, type: 'line', yAxisID: 'y1'
          }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'top', labels: { font: { size: 11 }, padding: 12, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: function(c) {
                return c.datasetIndex === 1
                  ? ' \u20b9' + c.parsed.y.toLocaleString('en-IN')
                  : ' ' + c.parsed.y + ' bookings';
              }
            }
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { stepSize: 1, font: { size: 10 } },
            grid: { color: '#f4f4f4' },
            title: { display: true, text: 'Bookings', font: { size: 10 } }
          },
          y1: {
            beginAtZero: true, position: 'right',
            grid: { drawOnChartArea: false },
            ticks: {
              font: { size: 10 },
              callback: function(v) {
                return v >= 100000 ? '\u20b9' + (v / 100000).toFixed(1) + 'L' : '\u20b9' + v;
              }
            },
            title: { display: true, text: 'Revenue', font: { size: 10 } }
          }
        }
      }
    });
  }

  var pCtx = document.getElementById('projectChart');
  if (pCtx && pL.length > 0) {
    var pal = ['#3c8dbc','#00a65a','#f39c12','#dd4b39','#00c0ef','#605ca8','#d81b60','#111'];
    new Chart(pCtx, {
      type: 'doughnut',
      data: {
        labels: pL,
        datasets: [{
          data: pC,
          backgroundColor: pal.slice(0, pL.length),
          borderWidth: 2, borderColor: '#fff'
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { font: { size: 10 }, padding: 10, boxWidth: 12 } }
        },
        cutout: '60%'
      }
    });
  }
})();
</script>
{% endblock %}
"""

with open('accounts/templates/accounts/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Written", len(content), "chars")
