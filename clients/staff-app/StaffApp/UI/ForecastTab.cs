using LiveChartsCore;
using LiveChartsCore.Measure;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Painting;
using LiveChartsCore.SkiaSharpView.WinForms;
using SkiaSharp;
using StaffApp.Models;
using StaffApp.Services;

namespace StaffApp.UI;

/// <summary>Read-only forecast comparison and table; no API or SQL work in the view.</summary>
public sealed class ForecastTab : UserControl
{
    private readonly CartesianChart _top = Chart();
    private readonly CartesianChart _short = Chart();
    private readonly DataGridView _grid = new() {
        Dock = DockStyle.Fill, ReadOnly = true, AllowUserToAddRows = false,
        AllowUserToDeleteRows = false, RowHeadersVisible = false,
        AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
        BackgroundColor = Color.White, ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.AutoSize,
    };
    private readonly Label _empty = new() { AutoSize = true, ForeColor = Color.DimGray };
    public event EventHandler? RefreshRequested;

    public ForecastTab()
    {
        Dock = DockStyle.Fill;
        var refresh = new Button { Text = "Làm mới", AutoSize = true };
        refresh.Click += (_, _) => RefreshRequested?.Invoke(this, EventArgs.Empty);
        var heading = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(4) };
        heading.Controls.Add(refresh);
        heading.Controls.Add(_empty);
        var charts = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        charts.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        charts.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        charts.Controls.Add(ChartBox("Top 10 bán chạy", _top), 0, 0);
        charts.Controls.Add(ChartBox("Hàng thiếu", _short), 1, 0);
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 3, ColumnCount = 1, Padding = new Padding(8) };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 58));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 42));
        layout.Controls.Add(heading, 0, 0);
        layout.Controls.Add(charts, 0, 1);
        layout.Controls.Add(_grid, 0, 2);
        foreach (var title in ForecastRows.Columns) _grid.Columns.Add("c" + _grid.Columns.Count, title);
        _grid.Columns[0].FillWeight = 230;
        Controls.Add(layout);
    }

    private static CartesianChart Chart() => new() {
        Dock = DockStyle.Top, Height = 340, AnimationsSpeed = TimeSpan.Zero,
        LegendPosition = LegendPosition.Top, BackColor = Color.White,
    };

    private static Control ChartBox(string title, CartesianChart chart)
    {
        var box = new GroupBox { Text = title, Dock = DockStyle.Fill, Padding = new Padding(8) };
        var scroll = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        scroll.Controls.Add(chart);
        box.Controls.Add(scroll);
        return box;
    }

    private static RowSeries<double> Series(string name, IEnumerable<decimal> values, SKColor color) => new() {
        Name = name, Values = values.Select(x => (double)x).ToArray(),
        Fill = new SolidColorPaint(color), Stroke = null,
        DataLabelsPaint = new SolidColorPaint(SKColors.Black), DataLabelsSize = 11,
        DataLabelsPosition = DataLabelsPosition.End,
        DataLabelsFormatter = point => point.Model.ToString("0.##", System.Globalization.CultureInfo.InvariantCulture),
    };

    private static void BindChart(CartesianChart chart, IReadOnlyList<ForecastLine> lines,
                                  string first, string second, Func<ForecastLine, decimal> comparison)
    {
        chart.Height = lines.Count <= 10 ? 300 : Math.Max(300, lines.Count * 26 + 75);
        chart.Series = new ISeries[] {
            Series(first, lines.Select(x => x.PredictedDemand), new SKColor(0, 84, 166)),
            Series(second, lines.Select(comparison), new SKColor(117, 144, 159)),
        };
        chart.YAxes = new[] { new Axis {
            Labels = lines.Select(x => x.Name).ToArray(), IsInverted = true, TextSize = 12,
            LabelsPaint = new SolidColorPaint(SKColors.Black), MinStep = 1, ForceStepToMin = true,
        }};
        var values = lines.Select(x => x.PredictedDemand).Concat(lines.Select(comparison)).DefaultIfEmpty(0).ToArray();
        chart.XAxes = new[] { new Axis { Name = "Đơn vị", TextSize = 12,
            MinLimit = (double)Math.Min(0, values.Min()), MaxLimit = (double)Math.Max(1, values.Max()) * 1.15,
            LabelsPaint = new SolidColorPaint(SKColors.Black) }};
    }

    public void Bind(ForecastList data)
    {
        _empty.Text = data.Items.Count == 0 ? "Chưa có dự báo cho cửa hàng này."
            : $"Ngày nghiệp vụ {data.BusinessDate:dd/MM/yyyy} — {data.Items.Count} sản phẩm";
        _grid.Rows.Clear();
        foreach (var line in data.Items)
        {
            var row = _grid.Rows[_grid.Rows.Add(ForecastRows.Cells(line, TimeZoneInfo.Local))];
            row.DefaultCellStyle.BackColor = line.BalanceStatus == "SHORTAGE" ? Color.FromArgb(255, 229, 180)
                : line.BalanceStatus == "SURPLUS" ? Color.FromArgb(226, 240, 217) : Color.White;
        }
        _grid.ClearSelection();
        BindChart(_top, ForecastRows.Top10(data.Items), "Dự báo 7 ngày tới", "Đã bán 7 ngày qua", x => x.SoldLast7Days);
        BindChart(_short, ForecastRows.Shortages(data.Items), "Dự báo", "Tồn bán được", x => x.SellableStock);
    }

    public void Clear()
    {
        Bind(new ForecastList(default, Array.Empty<ForecastLine>()));
        _empty.Text = string.Empty; // an error is not proof that the store has no forecasts
    }
}
