using System.Globalization;
using DemoConsole.Models;
using DemoConsole.Services;
using LiveChartsCore;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Painting;
using LiveChartsCore.SkiaSharpView.WinForms;
using SkiaSharp;

namespace DemoConsole.UI;

/// <summary>
/// The "Doanh thu" tab (PB-49): the three charts of the design (Survey v6 §6.5-6.7),
/// one scope/period filter row, the KPIs and the time-quality badge.
///
///   * line  — net revenue per bucket over the view scope,
///   * pie   — revenue share per product category over the same scope,
///   * bar   — the comparison set, which is independent of the view scope.
///
/// The tab owns no timer. <see cref="MainForm"/> drives it from its own 30-second
/// timer, because folding it into the 3-second refresh of the other four tabs would
/// send three range aggregates fifteen times as often for charts that only need to
/// move once a period.
///
/// Nothing here computes a number: totals, shares and quality labels all come from the
/// API. A second implementation of the revenue rule on the client is exactly the drift
/// the API exists to prevent. The only client-side reasoning is presentation, such as
/// keeping a negative category out of a pie that cannot draw it.
/// </summary>
internal sealed class DashboardTab : UserControl
{
    /// <summary>Day / week / month / quarter, in the order the plan lists them.</summary>
    public static readonly (string Key, string Label)[] Periods =
    {
        ("day", "Ngày"),
        ("week", "Tuần"),
        ("month", "Tháng"),
        ("quarter", "Quý"),
    };

    /// <summary>How many days each period looks back from today, inclusive of today.</summary>
    public static int DaysFor(string period) => period switch
    {
        "day" => 7,
        "week" => 28,
        "month" => 180,
        "quarter" => 365,
        _ => 7,
    };

    /// <summary>
    /// The category labels of the design (§6.6). Kept here rather than read from the
    /// database: the mapping is presentation, so it must not need a migration.
    /// </summary>
    private static readonly Dictionary<string, string> CategoryLabels = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Dairy"] = "Sản phẩm từ sữa",
        ["Bakery"] = "Bánh nướng",
        ["Dry goods"] = "Thực phẩm khô",
    };

    private readonly Func<DateTime> _utcNow;
    private readonly ComboBox _scope = new();
    private readonly ComboBox _period = new();
    private readonly Button _refresh;
    private readonly Label _kpiRevenue;
    private readonly Label _kpiTransactions;
    private readonly Label _quality;
    private readonly Label _sourceLine;
    private readonly Label _emptyLine;
    private readonly Label _pieNote;
    private readonly CartesianChart _lineChart;
    private readonly PieChart _pieChart;
    private readonly CartesianChart _barChart;
    private readonly LineSeries<double> _lineSeries;
    private readonly ColumnSeries<double> _barSeries;

    private IReadOnlyList<DashboardStore> _stores = Array.Empty<DashboardStore>();
    private string? _selectedStoreId;
    private bool _loading;
    private bool _available = true;

    public DashboardTab(string middlewareBaseUrl, Func<DateTime> utcNow, float fontSize)
    {
        _utcNow = utcNow;
        BackColor = Theme.Background;
        Font = Theme.Regular(fontSize);
        Dock = DockStyle.Fill;

        _scope.DropDownStyle = ComboBoxStyle.DropDownList;
        _scope.Font = Theme.Bold(fontSize);
        _scope.Width = (int)(fontSize * 20);
        _scope.SelectedIndexChanged += (_, _) => OnScopeChanged();

        _period.DropDownStyle = ComboBoxStyle.DropDownList;
        _period.Font = Theme.Bold(fontSize);
        _period.Width = (int)(fontSize * 8);
        foreach (var (_, label) in Periods)
        {
            _period.Items.Add(label);
        }

        // Day is the demo's answer; it is the period the plan promises.
        _period.SelectedIndex = 0;

        _refresh = Theme.ActionButton("Làm mới", fontSize + 1);
        _refresh.Click += async (_, _) => await RaiseRefreshAsync();

        _kpiRevenue = Kpi(fontSize * 1.6f);
        _kpiTransactions = Kpi(fontSize * 1.1f);
        _quality = Theme.Line(fontSize, bold: true);
        _quality.AutoSize = false;
        _quality.Height = (int)(fontSize * 3.2);
        _quality.Dock = DockStyle.Fill;
        _sourceLine = Theme.Line(fontSize);
        _sourceLine.ForeColor = Theme.Muted;
        _sourceLine.Text = $"Nguồn: {middlewareBaseUrl}";
        _emptyLine = Theme.Line(fontSize, bold: true);
        _emptyLine.ForeColor = Theme.Warn;
        _emptyLine.Visible = false;
        _pieNote = Theme.Line(fontSize);
        _pieNote.ForeColor = Theme.Warn;
        _pieNote.Dock = DockStyle.Top;

        // --- chart 1: revenue over time -----------------------------------
        _lineSeries = new LineSeries<double>
        {
            Values = Array.Empty<double>(),
            Stroke = new SolidColorPaint(new SKColor(0, 84, 166)) { StrokeThickness = 4 },
            GeometryStroke = new SolidColorPaint(new SKColor(0, 84, 166)) { StrokeThickness = 3 },
            GeometryFill = new SolidColorPaint(SKColors.White),
            GeometrySize = 7,
            Fill = new SolidColorPaint(new SKColor(0, 84, 166, 26)),
            Name = "Doanh thu",
        };
        _lineChart = new CartesianChart
        {
            Dock = DockStyle.Fill,
            Series = new ISeries[] { _lineSeries },
            AnimationsSpeed = TimeSpan.Zero,
            LegendPosition = LiveChartsCore.Measure.LegendPosition.Hidden,
        };

        // --- chart 2: share per category ----------------------------------
        _pieChart = new PieChart
        {
            Dock = DockStyle.Fill,
            Series = Array.Empty<ISeries>(),
            AnimationsSpeed = TimeSpan.Zero,
            LegendPosition = LiveChartsCore.Measure.LegendPosition.Right,
        };

        // --- chart 3: comparison set --------------------------------------
        _barSeries = new ColumnSeries<double>
        {
            Values = Array.Empty<double>(),
            Fill = new SolidColorPaint(new SKColor(0, 84, 166)),
            Stroke = null,
            DataLabelsPaint = new SolidColorPaint(SKColors.Black),
            DataLabelsSize = (int)fontSize,
            DataLabelsPosition = LiveChartsCore.Measure.DataLabelsPosition.Top,
            DataLabelsFormatter = point => point.Model.ToString("N0", CultureInfo.InvariantCulture),
            Name = "Doanh thu",
        };
        _barChart = new CartesianChart
        {
            Dock = DockStyle.Fill,
            Series = new ISeries[] { _barSeries },
            AnimationsSpeed = TimeSpan.Zero,
            LegendPosition = LiveChartsCore.Measure.LegendPosition.Hidden,
        };

        var filters = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        filters.Controls.Add(LabelText("Phạm vi xem:", fontSize));
        filters.Controls.Add(_scope);
        filters.Controls.Add(LabelText("Mốc:", fontSize));
        filters.Controls.Add(_period);
        filters.Controls.Add(_refresh);

        var kpis = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        kpis.Controls.Add(_kpiRevenue);
        kpis.Controls.Add(_kpiTransactions);

        // The line gets the most room: it is the chart the demo talks through.
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6 };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // filters
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // KPI
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // badge
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 48));   // line
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 52));   // pie + bar
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));      // source
        layout.Controls.Add(filters, 0, 0);
        layout.Controls.Add(kpis, 0, 1);
        layout.Controls.Add(_quality, 0, 2);

        var lineArea = new Panel { Dock = DockStyle.Fill };
        lineArea.Controls.Add(_lineChart);
        lineArea.Controls.Add(_emptyLine);
        _emptyLine.Dock = DockStyle.Top;
        layout.Controls.Add(lineArea, 0, 3);

        var split = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        split.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));

        var pieArea = new Panel { Dock = DockStyle.Fill };
        pieArea.Controls.Add(_pieChart);
        pieArea.Controls.Add(_pieNote);
        var barArea = new Panel { Dock = DockStyle.Fill };
        barArea.Controls.Add(_barChart);
        split.Controls.Add(Captioned("Tỷ lệ theo danh mục", pieArea, fontSize), 0, 0);
        split.Controls.Add(Captioned("So sánh cửa hàng (độc lập với phạm vi xem)", barArea, fontSize), 1, 0);
        layout.Controls.Add(split, 0, 4);

        layout.Controls.Add(_sourceLine, 0, 5);

        Controls.Add(layout);
    }

    /// <summary>Raised when the presenter asks for new data (refresh button or a filter).</summary>
    public event Func<Task>? RefreshRequested;

    public string Period => Periods[_period.SelectedIndex].Key;

    public string? SelectedStoreId => _selectedStoreId;

    /// <summary>The choices the store filter currently offers, for MainForm's "load once" check.</summary>
    public int ScopeChoices => _stores.Count;

    /// <summary>Fills the view-scope filter. The first entry is the whole system.</summary>
    public void SetStores(IReadOnlyList<DashboardStore> stores)
    {
        _stores = stores;
        var previous = _selectedStoreId;
        _scope.Items.Clear();
        _scope.Items.Add($"Toàn hệ thống ({stores.Count} cửa hàng)");
        foreach (var store in stores)
        {
            _scope.Items.Add($"{store.StoreId} {store.Name}");
        }

        var index = previous is null ? 0 : stores.ToList().FindIndex(s => s.StoreId == previous) + 1;
        _scope.SelectedIndex = index <= 0 ? 0 : index;
    }

    /// <summary>The half-open interval this tab asks for: the last N local days, up to now.</summary>
    public (DateTime FromUtc, DateTime ToUtc) Window()
    {
        var now = _utcNow();
        var localToday = BusinessClock.Today(now);
        var fromLocal = localToday.AddDays(-(DaysFor(Period) - 1)).ToDateTime(TimeOnly.MinValue);
        var fromUtc = fromLocal.Subtract(BusinessClock.Offset);
        return (DateTime.SpecifyKind(fromUtc, DateTimeKind.Utc), now);
    }

    /// <summary>Renders the line chart, the KPI and the badge. Never recomputes a number.</summary>
    public void Show(DashboardRevenue revenue)
    {
        _kpiRevenue.Text = "Doanh thu thuần: " + Money(revenue.TotalRevenue);
        _kpiTransactions.Text =
            $"   {revenue.Transactions.ToString("N0", CultureInfo.InvariantCulture)} giao dịch";

        _quality.Text = QualityLine(revenue.Quality, revenue.TimePolicy);
        _quality.ForeColor = revenue.Quality.IsClean ? Theme.Ok : Theme.Warn;

        _lineSeries.Values = revenue.Buckets.Select(bucket => (double)bucket.Revenue).ToArray();
        _lineChart.XAxes = new[]
        {
            new Axis
            {
                Labels = revenue.Buckets.Select(bucket => BucketLabel(bucket.FromUtc, Period)).ToArray(),
                LabelsRotation = 0,
                TextSize = (float)(_quality.Font.SizeInPoints + 1),
                LabelsPaint = new SolidColorPaint(SKColors.Black),
            },
        };
        _lineChart.YAxes = new[] { MoneyAxis() };
        _lineChart.Invalidate();

        _emptyLine.Visible = !revenue.HasData;
        _emptyLine.Text = revenue.HasData
            ? string.Empty
            : "Chưa có giao dịch trong khoảng này. Bán một đơn ở tab khác rồi làm mới.";
    }

    /// <summary>Renders the pie. A negative category cannot be a share, so it is noted.</summary>
    public void ShowCategories(DashboardCategoryRevenue revenue)
    {
        var slices = revenue.PositiveSlices;
        // One series per category, because the legend is built from the series names
        // and each slice needs its own "label + share". A single series would give the
        // pie its values but no per-slice label.
        _pieChart.Series = slices
            .Select(category => (ISeries)new PieSeries<double>
            {
                Values = new[] { (double)category.Revenue },
                Name = $"{Label(category.Category)} {category.Share * 100:0.#}%",
                DataLabelsPaint = new SolidColorPaint(SKColors.Black),
                DataLabelsSize = (int)_quality.Font.SizeInPoints + 1,
                DataLabelsPosition = LiveChartsCore.Measure.PolarLabelsPosition.Outer,
                ToolTipLabelFormatter = _ => $"{Label(category.Category)}: {Money(category.Revenue)}",
            })
            .ToArray();
        _pieChart.Invalidate();

        _pieNote.Text = NoteLine(revenue);
        _pieNote.Visible = _pieNote.Text.Length > 0;
    }

    /// <summary>Renders the comparison bars. Order is the server's (revenue descending).</summary>
    public void ShowStores(DashboardStoreRevenueResponse revenue)
    {
        _barSeries.Values = revenue.Stores.Select(store => (double)store.Revenue).ToArray();
        _barChart.XAxes = new[]
        {
            new Axis
            {
                Labels = revenue.Stores.Select(store => store.StoreId).ToArray(),
                LabelsRotation = 0,
                TextSize = (float)(_quality.Font.SizeInPoints + 1),
                LabelsPaint = new SolidColorPaint(SKColors.Black),
            },
        };
        _barChart.YAxes = new[] { MoneyAxis() };
        _barChart.Invalidate();
    }

    /// <summary>Renders a failed answer without clearing the last good charts.</summary>
    public void ShowError(ApiResult answer)
    {
        _quality.Text = $"Không tải được doanh thu: {answer.Summary}";
        _quality.ForeColor = Theme.Error;
    }

    /// <summary>
    /// Reports that one of the two lower charts could not be refreshed while the line
    /// and the KPI are fine. The last good chart stays, so a partial outage does not
    /// blank the screen during a demo.
    /// </summary>
    public void ShowPartialError(string summary)
    {
        _pieNote.Text = $"Một phần dữ liệu chưa tải được: {summary}";
        _pieNote.ForeColor = Theme.Warn;
        _pieNote.Visible = true;
    }

    /// <summary>The note under the pie: empty, a negative-category warning, or both.</summary>
    public static string NoteLine(DashboardCategoryRevenue revenue)
    {
        if (revenue.Categories.Count == 0)
        {
            return "Chưa có danh mục nào trong khoảng này.";
        }

        if (revenue.PositiveSlices.Count == 0)
        {
            return "Không có danh mục dương: biểu đồ tròn để trống (doanh thu ròng ≤ 0).";
        }

        var negative = revenue.NegativeCategories;
        return negative.Count == 0
            ? string.Empty
            : "Không vẽ trên biểu đồ tròn vì doanh thu ròng âm: " +
              string.Join(", ", negative.Select(category => $"{Label(category.Category)} ({Money(category.Revenue)})"));
    }

    /// <summary>
    /// The badge text. It names the two suspect groups and the pre-migration rows, so a
    /// number that is only approximate is never shown as if it were exact.
    /// </summary>
    public static string QualityLine(DashboardTimeQuality quality, DashboardTimePolicy policy)
    {
        var window = $"ngưỡng: lệch tới {policy.MaxFutureSkewSeconds} s, nhận muộn tới {policy.MaxBackfillDays} ngày";
        if (quality.Total == 0)
        {
            return $"Chất lượng thời gian: chưa có giao dịch nào ({window}).";
        }

        if (quality.IsClean)
        {
            return $"Chất lượng thời gian: đủ tin cậy, {quality.OnTime} đúng giờ + " +
                   $"{quality.Backfill} nhận bù ({window}).";
        }

        return $"Chất lượng thời gian: {quality.NotTrusted}/{quality.Total} giao dịch chưa tin cậy — " +
               $"{quality.SuspectFuture} giờ tương lai, {quality.SuspectOld} quá cũ, " +
               $"{quality.Unknown} thiếu mốc ({window}).";
    }

    /// <summary>The design's UI label for a product category, or the raw name.</summary>
    public static string Label(string category) =>
        CategoryLabels.TryGetValue(category, out var label) ? label : category;

    /// <summary>``dd/MM`` for a bucket, in local time.</summary>
    public static string BucketLabel(DateTime fromUtc, string period)
    {
        var local = BusinessClock.ToLocal(DateTime.SpecifyKind(fromUtc, DateTimeKind.Utc));
        return local.ToString("dd/MM", CultureInfo.InvariantCulture);
    }

    public static string Money(decimal amount) =>
        amount.ToString("N0", CultureInfo.InvariantCulture) + " đ";

    /// <summary>
    /// Bật/tắt ô lọc và nút làm mới. When the route answers 404 the tab keeps the
    /// existing "disabled button with a reason" rule instead of inventing a second
    /// mechanism (plan §7.3).
    /// </summary>
    public void SetAvailable(bool available, string reason)
    {
        _available = available;
        _refresh.Enabled = available && !_loading;
        _scope.Enabled = available;
        _period.Enabled = available;
        if (!available)
        {
            _quality.Text = reason;
            _quality.ForeColor = Theme.Muted;
        }
    }

    public void SetBusy(bool busy)
    {
        _loading = busy;
        // A busy tab may still be a not-deployed tab: availability, not just the
        // in-flight flag, decides whether the button can be pressed.
        _refresh.Enabled = _available && !busy;
        _refresh.Text = busy ? "Đang tải..." : "Làm mới";
    }

    private void OnScopeChanged()
    {
        if (_scope.SelectedIndex <= 0)
        {
            _selectedStoreId = null;
        }
        else if (_scope.SelectedIndex - 1 < _stores.Count)
        {
            _selectedStoreId = _stores[_scope.SelectedIndex - 1].StoreId;
        }

        if (!_loading)
        {
            _ = RaiseRefreshAsync();
        }
    }

    private async Task RaiseRefreshAsync()
    {
        if (RefreshRequested is not null)
        {
            await RefreshRequested.Invoke();
        }
    }

    private static Axis MoneyAxis() => new()
    {
        Labeler = value => value.ToString("N0", CultureInfo.InvariantCulture),
        LabelsPaint = new SolidColorPaint(SKColors.Black),
        Name = "VNĐ",
        NamePaint = new SolidColorPaint(SKColors.Black),
    };

    private static Control Captioned(string title, Control content, float fontSize)
    {
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        panel.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        panel.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        var label = Theme.Line(fontSize, bold: true);
        label.Text = title;
        panel.Controls.Add(label, 0, 0);
        panel.Controls.Add(content, 0, 1);
        return panel;
    }

    private static Label Kpi(float size) => new()
    {
        AutoSize = true,
        Font = Theme.Bold(size),
        ForeColor = Theme.Header,
        Margin = new Padding(6, 6, 18, 6),
        Text = "—",
    };

    private static Label LabelText(string text, float size)
    {
        var label = Theme.Line(size, bold: true);
        label.Text = text;
        label.Margin = new Padding(6, 10, 4, 4);
        return label;
    }
}
