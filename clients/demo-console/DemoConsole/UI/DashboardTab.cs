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
/// The "Doanh thu" tab (PB-49, plan D3): a day-bucket revenue line, the two KPIs and
/// the time-quality badge, over one interval and one scope.
///
/// The tab owns no timer. <see cref="MainForm"/> drives it from its own 30-second
/// timer, because folding it into the 3-second refresh of the other four tabs would
/// send a range aggregate fifteen times as often for a chart that only needs to move
/// once a period.
///
/// Nothing here computes a number: the total, the counts and the quality labels all
/// come from the API. A second implementation of the revenue rule on the client is
/// exactly the drift the API exists to prevent.
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

    private readonly Func<DateTime> _utcNow;
    private readonly ComboBox _scope = new();
    private readonly ComboBox _period = new();
    private readonly Button _refresh;
    private readonly Label _kpiRevenue;
    private readonly Label _kpiTransactions;
    private readonly Label _quality;
    private readonly Label _sourceLine;
    private readonly Label _emptyLine;
    private readonly CartesianChart _chart;
    private readonly LineSeries<double> _series;

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
        _scope.Width = (int)(fontSize * 22);
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

        _kpiRevenue = Kpi(fontSize * 1.8f);
        _kpiTransactions = Kpi(fontSize * 1.2f);
        _quality = Theme.Line(fontSize, bold: true);
        _quality.AutoSize = false;
        _quality.Height = (int)(fontSize * 3.4);
        _quality.Dock = DockStyle.Fill;
        _sourceLine = Theme.Line(fontSize);
        _sourceLine.ForeColor = Theme.Muted;
        _sourceLine.Text = $"Nguồn: {middlewareBaseUrl}";
        _emptyLine = Theme.Line(fontSize, bold: true);
        _emptyLine.ForeColor = Theme.Warn;
        _emptyLine.Visible = false;

        _series = new LineSeries<double>
        {
            Values = Array.Empty<double>(),
            // A projector needs a thick, saturated line, and Skia paints Vietnamese
            // diacritics through its own font manager, so no GDI fallback is needed.
            Stroke = new SolidColorPaint(new SKColor(0, 84, 166)) { StrokeThickness = 4 },
            GeometryStroke = new SolidColorPaint(new SKColor(0, 84, 166)) { StrokeThickness = 4 },
            GeometryFill = new SolidColorPaint(SKColors.White),
            GeometrySize = 10,
            Fill = new SolidColorPaint(new SKColor(0, 84, 166, 26)),
            Name = "Doanh thu",
        };

        _chart = new CartesianChart
        {
            Dock = DockStyle.Fill,
            Series = new ISeries[] { _series },
            // No animation: on a projector a chart that slides for half a second
            // looks broken next to the instant grid refreshes.
            AnimationsSpeed = TimeSpan.Zero,
            LegendPosition = LiveChartsCore.Measure.LegendPosition.Hidden,
        };

        var filters = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        filters.Controls.Add(LabelText("Phạm vi:", fontSize));
        filters.Controls.Add(_scope);
        filters.Controls.Add(LabelText("Mốc:", fontSize));
        filters.Controls.Add(_period);
        filters.Controls.Add(_refresh);

        var kpis = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        kpis.Controls.Add(_kpiRevenue);
        kpis.Controls.Add(_kpiTransactions);

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5 };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));   // filters
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));   // KPI
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));   // quality badge
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100)); // chart and its note
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));   // source line
        layout.Controls.Add(filters, 0, 0);
        layout.Controls.Add(kpis, 0, 1);
        layout.Controls.Add(_quality, 0, 2);

        var chartArea = new Panel { Dock = DockStyle.Fill };
        chartArea.Controls.Add(_chart);
        chartArea.Controls.Add(_emptyLine);
        _emptyLine.Dock = DockStyle.Top;
        layout.Controls.Add(chartArea, 0, 3);
        layout.Controls.Add(_sourceLine, 0, 4);

        Controls.Add(layout);
    }

    /// <summary>The filter row, so MainForm can place it and wire its own status label.</summary>
    public Control Content => this;

    /// <summary>Raised when the presenter asks for a new interval (the refresh button or a filter).</summary>
    public event Func<Task>? RefreshRequested;

    public string Period => Periods[_period.SelectedIndex].Key;

    public string? SelectedStoreId => _selectedStoreId;

    /// <summary>The choices the store filter currently offers, for MainForm's "load once" check.</summary>
    public int ScopeChoices => _stores.Count;

    /// <summary>Fills the store filter. The first entry is the whole system.</summary>
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

    /// <summary>Renders one successful answer. Never recomputes what the server said.</summary>
    public void Show(DashboardRevenue revenue)
    {
        _kpiRevenue.Text = "Doanh thu thuần: " + Money(revenue.TotalRevenue);
        _kpiTransactions.Text =
            $"   {revenue.Transactions.ToString("N0", CultureInfo.InvariantCulture)} giao dịch";

        _quality.Text = QualityLine(revenue.Quality, revenue.TimePolicy);
        _quality.ForeColor = revenue.Quality.IsClean ? Theme.Ok : Theme.Warn;

        _series.Values = revenue.Buckets.Select(bucket => (double)bucket.Revenue).ToArray();
        _chart.XAxes = new[]
        {
            new Axis
            {
                Labels = revenue.Buckets.Select(bucket => BucketLabel(bucket.FromUtc, Period)).ToArray(),
                LabelsRotation = 0,
                TextSize = (float)(_quality.Font.SizeInPoints + 1),
                LabelsPaint = new SolidColorPaint(SKColors.Black),
            },
        };
        _chart.YAxes = new[]
        {
            new Axis
            {
                Labeler = value => value.ToString("N0", CultureInfo.InvariantCulture),
                LabelsPaint = new SolidColorPaint(SKColors.Black),
                Name = "VNĐ",
                NamePaint = new SolidColorPaint(SKColors.Black),
            },
        };
        _chart.Invalidate();

        _emptyLine.Visible = !revenue.HasData;
        _emptyLine.Text = revenue.HasData
            ? string.Empty
            : "Chưa có giao dịch trong khoảng này. Bán một đơn ở tab khác rồi làm mới.";
    }

    /// <summary>Renders a failed answer without clearing the last good chart.</summary>
    public void ShowError(ApiResult answer)
    {
        _quality.Text = $"Không tải được doanh thu: {answer.Summary}";
        _quality.ForeColor = Theme.Error;
    }

    /// <summary>
    /// The badge text. It names the two suspect groups and the pre-migration rows,
    /// so a number that is only approximate is never shown as if it were exact.
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

    /// <summary>``dd/MM`` for a day bucket, ISO week-ish ``dd/MM`` for the coarser ones.</summary>
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

    public bool IsBusy => _loading;

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
