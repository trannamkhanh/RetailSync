using System.Globalization;
using DemoConsole.Configuration;
using DemoConsole.Models;
using DemoConsole.Services;

namespace DemoConsole.UI;

/// <summary>
/// The presenter's window on machine S: four tabs that refresh on their own. Every
/// call runs off the UI thread (async HTTP and SQL); the timer skips a tick while the
/// previous refresh is still running, so a slow or failed call never freezes it.
/// </summary>
internal sealed class MainForm : Form
{
    private const int TransactionLimit = 30;
    private const int AuditLimit = 30;
    private const int SyncBatchLimit = 40;
    private static readonly string[] HqModes = { "ONLINE", "OFFLINE", "ERROR", "SLOW", "DROP_ACK" };
    private static readonly TimeSpan ProbeEvery = TimeSpan.FromSeconds(30);

    private readonly LoadedConsoleConfig _loaded;
    private readonly ConsoleConfig _config;
    private readonly DemoApiClient _api;
    private readonly ReadOnlySql? _sql;
    private readonly Dictionary<string, string> _productNames;
    private readonly Dictionary<string, string> _storeNames;
    private readonly float _font;

    private readonly ChangeTracker<int> _stockChanges;
    private readonly ChangeTracker<string> _transactionChanges;
    private readonly ChangeTracker<long> _auditChanges;
    private readonly ChangeTracker<string> _syncChanges;
    private readonly ChangeTracker<string> _hqBatchChanges;
    private readonly ChangeTracker<string> _hqTotalChanges;
    private readonly ChangeTracker<string> _alertChanges;

    private readonly System.Windows.Forms.Timer _timer = new();
    private bool _refreshing;
    private DateTime _lastProbe = DateTime.MinValue;
    private IReadOnlyList<StockLine> _stock = Array.Empty<StockLine>();

    private FeatureState _syncFeature = FeatureState.Unknown;
    private FeatureState _snapshotFeature = FeatureState.Unknown;
    private FeatureState _nearExpiryFeature = FeatureState.Unknown;
    private FeatureState _forecastFeature = FeatureState.Unknown;
    private string _hqMode = "chưa đặt từ bảng điều khiển (HQ demo khởi động ở ONLINE)";

    // Tab 1
    private readonly Label _stockStatus;
    private readonly DataGridView _stockGrid;
    private readonly DataGridView _batchGrid;
    private readonly Label _batchTitle;

    // Tab 2
    private readonly Label _activityStatus;
    private readonly DataGridView _transactionGrid;
    private readonly DataGridView _auditGrid;

    // Tab 3
    private readonly Label _syncStatus;
    private readonly Label _syncFeatureLine;
    private readonly Label _hqModeLine;
    private readonly Label _hqTotalLine;
    private readonly Button _runSync;
    private readonly Button _sendSnapshot;
    private readonly List<Button> _modeButtons = new();
    private readonly DataGridView _syncGrid;
    private readonly DataGridView _hqBatchGrid;
    private readonly DataGridView _hqTotalGrid;

    // Tab 4
    private readonly Label _jobStatus;
    private readonly Label _jobFeatureLine;
    private readonly Button _runNearExpiry;
    private readonly Button _runForecast;
    private readonly Button _setThreshold;
    private readonly ComboBox _thresholdCategory;
    private readonly NumericUpDown _thresholdDays;
    private readonly DataGridView _alertGrid;
    private readonly DataGridView _forecastGrid;
    private readonly Label _forecastEmpty;

    // Window
    private readonly Label _resultLine;
    private readonly Label _headerLine;

    public MainForm(LoadedConsoleConfig loaded)
    {
        _loaded = loaded;
        _config = loaded.Config;
        _font = _config.FontSize;
        var hold = TimeSpan.FromSeconds(_config.HighlightSeconds);
        _stockChanges = new ChangeTracker<int>(hold);
        _transactionChanges = new ChangeTracker<string>(hold);
        _auditChanges = new ChangeTracker<long>(hold);
        _syncChanges = new ChangeTracker<string>(hold);
        _hqBatchChanges = new ChangeTracker<string>(hold);
        _hqTotalChanges = new ChangeTracker<string>(hold);
        _alertChanges = new ChangeTracker<string>(hold);
        _productNames = _config.Products.ToDictionary(p => p.Sku, p => p.Name, StringComparer.OrdinalIgnoreCase);
        _storeNames = _config.Stores.ToDictionary(s => s.StoreId, s => s.Name, StringComparer.OrdinalIgnoreCase);

        var authority = Security.ServerCertificateValidator.LoadAuthority(loaded.Paths.CaCertificate);
        _api = new DemoApiClient(_config.MiddlewareBaseUrl, _config.HqBaseUrl, authority, loaded.Tokens);
        _sql = loaded.SqlPassword.Length > 0
            ? new ReadOnlySql(_config.SqlServer, _config.Database, loaded.SqlPassword)
            : null;

        Text = $"RetailSync - bảng điều khiển demo ({_config.Database})";
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = Theme.Regular(_font);
        WindowState = FormWindowState.Maximized;
        MinimumSize = new Size(1024, 700);

        _headerLine = Theme.Line(_font);
        _headerLine.Dock = DockStyle.Top;
        _headerLine.Padding = new Padding(6, 4, 6, 4);
        _headerLine.Text = $"Middleware {_config.MiddlewareBaseUrl}   HQ {_config.HqBaseUrl}   SQL {_config.SqlServer}/{_config.Database} (chỉ đọc)   làm mới mỗi {_config.RefreshSeconds} giây";

        _resultLine = new Label
        {
            Dock = DockStyle.Bottom,
            AutoSize = false,
            Height = (int)(_font * 3.2),
            Font = Theme.Bold(_font + 1),
            Padding = new Padding(8, 6, 8, 6),
            BackColor = Color.FromArgb(240, 240, 240),
            ForeColor = Theme.Text,
            Text = loaded.Problems.Count > 0
                ? "Cảnh báo cấu hình: " + string.Join("  |  ", loaded.Problems)
                : "Kết quả thao tác sẽ hiện ở đây.",
        };
        if (loaded.Problems.Count > 0)
        {
            _resultLine.ForeColor = Theme.Error;
        }

        var tabs = new TabControl
        {
            Dock = DockStyle.Fill,
            Font = Theme.Bold(_font + 1),
            Padding = new Point(18, 6),
        };

        // --- Tab 1: stock and batches ---------------------------------------
        _stockStatus = StatusLine();
        _stockGrid = Theme.Grid(_font, ("store", "Cửa hàng", 18), ("sku", "SKU", 14), ("name", "Sản phẩm", 26),
            ("qty", "Tồn", 10), ("sellable", "Bán được", 12), ("change", "Thay đổi", 12));
        _stockGrid.CellClick += (_, _) => ShowBatches();
        _stockGrid.KeyUp += (_, _) => ShowBatches();
        _batchTitle = Theme.Line(_font, bold: true);
        _batchTitle.Text = "Lô của dòng đang chọn";
        _batchGrid = Theme.Grid(_font, ("batch", "Lô", 34), ("expiry", "Hạn dùng", 18), ("qty", "Số lượng", 14),
            ("state", "Trạng thái", 22));
        var stockSplit = new SplitContainer
        {
            Dock = DockStyle.Fill,
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
        };
        stockSplit.Panel1.Controls.Add(_stockGrid);
        stockSplit.Panel2.Controls.Add(_batchGrid);
        stockSplit.Panel2.Controls.Add(_batchTitle);
        _batchTitle.Dock = DockStyle.Top;
        tabs.TabPages.Add(Page("Tồn và lô", _stockStatus, stockSplit));
        stockSplit.SplitterDistance = Math.Max(200, (int)(Screen.PrimaryScreen!.WorkingArea.Height * 0.45));

        // --- Tab 2: transactions and audit ----------------------------------
        _activityStatus = StatusLine();
        _transactionGrid = Theme.Grid(_font, ("txn", "Giao dịch", 30), ("store", "Cửa hàng", 14), ("pos", "POS", 14),
            ("type", "Loại", 14), ("status", "TT", 8), ("time", "Giờ (UTC+7)", 13), ("batch", "sync_batch_id", 22));
        _auditGrid = Theme.Grid(_font, ("time", "Giờ (UTC+7)", 12), ("action", "Action", 18),
            ("key", "Entity key", 22), ("details", "Chi tiết", 48));
        var activity = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 4 };
        activity.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        activity.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        activity.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        activity.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        activity.Controls.Add(Title($"{TransactionLimit} giao dịch mới nhất (không tính lịch sử HIST-)"), 0, 0);
        activity.Controls.Add(_transactionGrid, 0, 1);
        activity.Controls.Add(Title($"{AuditLimit} dòng audit mới nhất (GET /audit-logs, auditor)"), 0, 2);
        activity.Controls.Add(_auditGrid, 0, 3);
        tabs.TabPages.Add(Page("Giao dịch và audit", _activityStatus, activity));

        // --- Tab 3: sync and HQ ---------------------------------------------
        _syncStatus = StatusLine();
        _runSync = Theme.ActionButton("Chạy đồng bộ", _font + 1);
        _runSync.Click += async (_, _) => await RunSyncAsync();
        _sendSnapshot = Theme.ActionButton("Gửi snapshot", _font + 1);
        _sendSnapshot.Click += async (_, _) => await SendSnapshotAsync();
        var syncButtons = ButtonRow(_runSync);
        syncButtons.Controls.Add(Theme.Line(_font, bold: true));
        syncButtons.Controls[^1].Text = "   HQ:";
        foreach (var mode in HqModes)
        {
            var button = Theme.ActionButton(mode, _font);
            button.Click += async (_, _) => await SetHqModeAsync(mode);
            _modeButtons.Add(button);
            syncButtons.Controls.Add(button);
        }

        syncButtons.Controls.Add(_sendSnapshot);
        _syncFeatureLine = Theme.Line(_font);
        _syncFeatureLine.ForeColor = Theme.Warn;
        _hqModeLine = Theme.Line(_font, bold: true);
        _hqTotalLine = Theme.Line(_font, bold: true);
        _syncGrid = Theme.Grid(_font, ("id", "sync_batch_id", 26), ("store", "Cửa hàng", 12), ("status", "Trạng thái", 11),
            ("attempts", "Lần thử", 8), ("txns", "GD", 6), ("error", "Lỗi gần nhất", 22), ("retry", "Thử lại lúc", 12),
            ("acked", "ACK lúc", 12));
        _hqBatchGrid = Theme.Grid(_font, ("id", "Batch ở HQ", 30), ("store", "Cửa hàng", 14), ("txns", "GD", 8),
            ("received", "Nhận lúc (UTC+7)", 18), ("dups", "Trùng", 8));
        _hqTotalGrid = Theme.Grid(_font, ("store", "Cửa hàng", 16), ("sku", "SKU", 14), ("sold", "Bán", 10),
            ("returned", "Trả", 10), ("revenue", "Doanh thu ròng", 18));
        var hqSplit = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        hqSplit.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        hqSplit.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        hqSplit.Controls.Add(_hqBatchGrid, 0, 0);
        hqSplit.Controls.Add(_hqTotalGrid, 1, 0);
        var sync = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 7 };
        sync.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        sync.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        sync.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        sync.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        sync.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        sync.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        sync.Controls.Add(syncButtons, 0, 0);
        sync.Controls.Add(_syncFeatureLine, 0, 1);
        sync.Controls.Add(Title("sync_batch ở middleware (SQL chỉ đọc)"), 0, 2);
        sync.Controls.Add(_syncGrid, 0, 3);
        var hqHeader = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        hqHeader.Controls.Add(_hqModeLine);
        hqHeader.Controls.Add(_hqTotalLine);
        sync.Controls.Add(hqHeader, 0, 4);
        sync.Controls.Add(hqSplit, 0, 5);
        tabs.TabPages.Add(Page("Đồng bộ và HQ", _syncStatus, sync));

        // --- Tab 4: jobs, alerts, forecast ----------------------------------
        _jobStatus = StatusLine();
        _runNearExpiry = Theme.ActionButton("Chạy kiểm tra cận hạn", _font + 1);
        _runNearExpiry.Click += async (_, _) => await RunJobAsync("near-expiry");
        _runForecast = Theme.ActionButton("Chạy dự báo", _font + 1);
        _runForecast.Click += async (_, _) => await RunJobAsync("forecast");
        _thresholdCategory = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Font = Theme.Regular(_font),
            Width = (int)(_font * 11),
            Margin = new Padding(16, 8, 4, 4),
        };
        _thresholdCategory.Items.AddRange(new object[] { "Dairy", "Bakery", "Dry goods" });
        _thresholdCategory.SelectedIndex = 0;
        _thresholdDays = new NumericUpDown
        {
            Minimum = 0,
            Maximum = 3650,
            Value = 7,
            Font = Theme.Regular(_font),
            Width = (int)(_font * 6),
            Margin = new Padding(4, 8, 4, 4),
        };
        _setThreshold = Theme.ActionButton("Đặt ngưỡng", _font);
        _setThreshold.Click += async (_, _) => await SetThresholdAsync();
        var jobButtons = ButtonRow(_runNearExpiry, _runForecast);
        jobButtons.Controls.Add(_thresholdCategory);
        jobButtons.Controls.Add(_thresholdDays);
        jobButtons.Controls.Add(_setThreshold);
        _jobFeatureLine = Theme.Line(_font);
        _jobFeatureLine.ForeColor = Theme.Warn;
        _alertGrid = Theme.Grid(_font, ("store", "Cửa hàng", 12), ("sku", "SKU", 11), ("name", "Sản phẩm", 18),
            ("batch", "Lô", 24), ("expiry", "Hạn", 12), ("days", "Còn (ngày)", 9), ("qty", "SL", 7),
            ("type", "Loại", 13), ("status", "TT", 8));
        _forecastGrid = Theme.Grid(_font, ("store", "Cửa hàng", 12), ("sku", "SKU", 11), ("name", "Sản phẩm", 18),
            ("horizon", "Số ngày", 8), ("demand", "Nhu cầu dự báo", 13), ("gap", "Thừa(+)/thiếu(-)", 13),
            ("balance", "Kết luận", 12), ("model", "Mô hình", 12), ("at", "Lúc (UTC+7)", 12));
        _forecastEmpty = Theme.Line(_font);
        _forecastEmpty.ForeColor = Theme.Muted;
        var jobs = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 6 };
        jobs.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        jobs.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        jobs.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        jobs.RowStyles.Add(new RowStyle(SizeType.Percent, 55));
        jobs.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        jobs.RowStyles.Add(new RowStyle(SizeType.Percent, 45));
        jobs.Controls.Add(jobButtons, 0, 0);
        jobs.Controls.Add(_jobFeatureLine, 0, 1);
        jobs.Controls.Add(Title("Cảnh báo cận hạn đang mở (SQL chỉ đọc), số ngày tính theo hôm nay UTC+7"), 0, 2);
        jobs.Controls.Add(_alertGrid, 0, 3);
        var forecastHeader = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        forecastHeader.Controls.Add(Title("Dự báo mới nhất theo cửa hàng và SKU"));
        forecastHeader.Controls.Add(_forecastEmpty);
        jobs.Controls.Add(forecastHeader, 0, 4);
        jobs.Controls.Add(_forecastGrid, 0, 5);
        tabs.TabPages.Add(Page("Job", _jobStatus, jobs));

        Controls.Add(tabs);
        Controls.Add(_resultLine);
        Controls.Add(_headerLine);

        UpdateFeatureControls();
        _timer.Interval = _config.RefreshSeconds * 1000;
        _timer.Tick += async (_, _) => await RefreshAllAsync();
        Shown += async (_, _) =>
        {
            await RefreshAllAsync();
            _timer.Start();
        };
        FormClosed += (_, _) =>
        {
            _timer.Stop();
            _api.Dispose();
        };
    }

    // --- Refresh ------------------------------------------------------------

    private async Task RefreshAllAsync()
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;
        try
        {
            var now = DateTime.UtcNow;
            var tasks = new List<Task>
            {
                Guard(_stockStatus, RefreshStockAsync),
                Guard(_activityStatus, RefreshActivityAsync),
                Guard(_syncStatus, RefreshSyncAsync),
                Guard(_jobStatus, RefreshJobsAsync),
            };
            if (now - _lastProbe >= ProbeEvery)
            {
                _lastProbe = now;
                tasks.Add(ProbeFeaturesAsync());
            }

            await Task.WhenAll(tasks);
        }
        finally
        {
            _refreshing = false;
        }
    }

    /// <summary>Runs one tab's refresh and writes its last refresh time and last error.</summary>
    private static async Task Guard(Label status, Func<Task<string?>> refresh)
    {
        string? error;
        try
        {
            error = await refresh();
        }
        catch (Exception exception)
        {
            error = exception.Message;
        }

        var time = BusinessClock.ToLocal(DateTime.UtcNow).ToString("HH:mm:ss", CultureInfo.InvariantCulture);
        if (error is null)
        {
            status.Text = $"Làm mới lúc {time}. Không có lỗi.";
            status.ForeColor = Theme.Ok;
            status.Tag = null;
        }
        else
        {
            status.Text = $"Làm mới lúc {time}. Lỗi gần nhất: {error}";
            status.ForeColor = Theme.Error;
        }
    }

    private async Task<string?> RefreshStockAsync()
    {
        var calls = _config.Stores
            .Select(store => (store, task: _api.GetInventoryAsync(store.StoreId, store.Token)))
            .ToList();
        await Task.WhenAll(calls.Select(call => call.task));

        var errors = new List<string>();
        var lines = new List<StockLine>();
        foreach (var (store, task) in calls)
        {
            var result = task.Result;
            if (!result.IsSuccess)
            {
                errors.Add($"{store.StoreId}: {result.Summary}");
                // Keep the last known lines of that store rather than showing nothing.
                lines.AddRange(_stock.Where(line => line.StoreId == store.StoreId));
                continue;
            }

            try
            {
                lines.AddRange(ApiParsers.Inventory(result.Body));
            }
            catch (FormatException error)
            {
                errors.Add($"{store.StoreId}: {error.Message}");
            }
        }

        var now = DateTime.UtcNow;
        var today = BusinessClock.Today(now);
        if (errors.Count == 0 || lines.Count > 0)
        {
            _stockChanges.Update(lines.ToDictionary(line => StockKey(line), line => line.Quantity), now);
        }

        _stock = lines;
        var rows = lines.Select(line =>
        {
            var key = StockKey(line);
            var highlighted = _stockChanges.IsHighlighted(key, now);
            var change = _stockChanges.TryGetPrevious(key, now, out var previous)
                ? $"{previous} → {line.Quantity}"
                : string.Empty;
            return new GridRow(key,
                new object?[] { StoreLabel(line.StoreId), line.Sku, SkuName(line.Sku), line.Quantity, line.SellableOn(today), change },
                highlighted ? Theme.Changed : null);
        }).ToList();
        GridFiller.Fill(_stockGrid, rows);
        ShowBatches();
        return errors.Count == 0 ? null : string.Join("; ", errors);
    }

    private void ShowBatches()
    {
        var key = GridFiller.SelectedKey(_stockGrid);
        var line = key is null ? null : _stock.FirstOrDefault(item => StockKey(item) == key);
        if (line is null)
        {
            _batchTitle.Text = "Chọn một dòng ở trên để xem các lô (FEFO: lô hạn sớm nhất bị trừ trước)";
            GridFiller.Fill(_batchGrid, Array.Empty<GridRow>());
            return;
        }

        var today = BusinessClock.Today(DateTime.UtcNow);
        _batchTitle.Text = $"Lô của {StoreLabel(line.StoreId)} / {line.Sku} {SkuName(line.Sku)} - hôm nay {today:yyyy-MM-dd}";
        var rows = line.Batches
            .OrderBy(batch => batch.ExpiryDate).ThenBy(batch => batch.BatchId, StringComparer.Ordinal)
            .Select(batch =>
            {
                var expired = batch.ExpiryDate < today;
                return new GridRow(batch.BatchId,
                    new object?[] { batch.BatchId, batch.ExpiryDate.ToString("yyyy-MM-dd"), batch.Quantity, BusinessClock.BatchState(batch.ExpiryDate, today) },
                    Fore: expired ? Theme.Expired : null);
            })
            .ToList();
        GridFiller.Fill(_batchGrid, rows);
    }

    private async Task<string?> RefreshActivityAsync()
    {
        var errors = new List<string>();
        var now = DateTime.UtcNow;
        var auditTask = _api.GetAuditLogsAsync(AuditLimit);

        if (_sql is null)
        {
            errors.Add("không có MSSQL_SA_PASSWORD nên không đọc được giao dịch");
        }
        else
        {
            try
            {
                var transactions = await _sql.LatestTransactionsAsync(TransactionLimit);
                _transactionChanges.Update(
                    transactions.ToDictionary(row => row.TxnId, row => $"{row.Status}|{row.SyncBatchId}"), now);
                GridFiller.Fill(_transactionGrid, transactions.Select(row => new GridRow(row.TxnId,
                    new object?[] { row.TxnId, row.StoreId, row.PosId, row.TxnType, row.Status, LocalTime(row.CreatedAtUtc), row.SyncBatchId ?? "-" },
                    _transactionChanges.IsHighlighted(row.TxnId, now) ? Theme.Changed : null)).ToList());
            }
            catch (Exception error)
            {
                errors.Add($"SQL: {error.Message}");
            }
        }

        var audit = await auditTask;
        if (audit.IsSuccess)
        {
            try
            {
                var rows = ApiParsers.AuditLogs(audit.Body);
                _auditChanges.Update(rows.ToDictionary(row => row.AuditId.ToString(CultureInfo.InvariantCulture), row => row.AuditId), now);
                GridFiller.Fill(_auditGrid, rows.Select(row =>
                {
                    var key = row.AuditId.ToString(CultureInfo.InvariantCulture);
                    return new GridRow(key,
                        new object?[] { LocalTime(row.CreatedAtUtc), row.Action, row.EntityKey ?? "-", row.Details ?? string.Empty },
                        _auditChanges.IsHighlighted(key, now) ? Theme.Changed : null,
                        AuditColour(row.Action));
                }).ToList());
            }
            catch (FormatException error)
            {
                errors.Add($"audit: {error.Message}");
            }
        }
        else
        {
            errors.Add($"audit: {audit.Summary}");
        }

        return errors.Count == 0 ? null : string.Join("; ", errors);
    }

    private async Task<string?> RefreshSyncAsync()
    {
        var errors = new List<string>();
        var now = DateTime.UtcNow;
        var hqTask = _api.GetHqBatchesAsync();

        if (_sql is null)
        {
            errors.Add("không có MSSQL_SA_PASSWORD nên không đọc được sync_batch");
        }
        else
        {
            try
            {
                var batches = await _sql.SyncBatchesAsync(SyncBatchLimit);
                _syncChanges.Update(batches.ToDictionary(row => row.SyncBatchId,
                    row => $"{row.Status}|{row.Attempts}|{row.LastError}"), now);
                GridFiller.Fill(_syncGrid, batches.Select(row => new GridRow(row.SyncBatchId,
                    new object?[]
                    {
                        row.SyncBatchId, row.StoreId, row.Status, row.Attempts, row.TxnCount,
                        row.LastError ?? "-", row.NextRetryAtUtc is { } retry ? LocalTime(retry) : "-",
                        row.AckedAtUtc is { } acked ? LocalTime(acked) : "-",
                    },
                    _syncChanges.IsHighlighted(row.SyncBatchId, now) ? Theme.Changed : null,
                    SyncColour(row.Status))).ToList());
            }
            catch (Exception error)
            {
                errors.Add($"SQL: {error.Message}");
            }
        }

        var hq = await hqTask;
        if (hq.IsSuccess)
        {
            try
            {
                var view = ApiParsers.DemoBatches(hq.Body);
                _hqBatchChanges.Update(view.Batches.ToDictionary(b => b.BatchId, b => $"{b.TxnCount}|{b.DuplicateCount}"), now);
                GridFiller.Fill(_hqBatchGrid, view.Batches.OrderByDescending(b => b.ReceivedAtUtc).Select(b => new GridRow(b.BatchId,
                    new object?[] { b.BatchId, b.StoreId, b.TxnCount, LocalTime(b.ReceivedAtUtc), b.DuplicateCount },
                    _hqBatchChanges.IsHighlighted(b.BatchId, now) ? Theme.Changed : null)).ToList());

                _hqTotalChanges.Update(view.Totals.ToDictionary(t => $"{t.StoreId}|{t.Sku}",
                    t => $"{t.SoldQty}|{t.ReturnedQty}|{t.NetRevenue}"), now);
                GridFiller.Fill(_hqTotalGrid, view.Totals.Select(t =>
                {
                    var key = $"{t.StoreId}|{t.Sku}";
                    return new GridRow(key,
                        new object?[] { t.StoreId, t.Sku, t.SoldQty, t.ReturnedQty, t.NetRevenue.ToString("N0", CultureInfo.InvariantCulture) },
                        _hqTotalChanges.IsHighlighted(key, now) ? Theme.Changed : null);
                }).ToList());
                _hqTotalLine.Text = $"   Tổng ở HQ: {view.Batches.Count} batch, {view.Batches.Sum(b => b.TxnCount)} giao dịch, bán {view.Totals.Sum(t => t.SoldQty)}, trả {view.Totals.Sum(t => t.ReturnedQty)}, doanh thu ròng {view.Totals.Sum(t => t.NetRevenue).ToString("N0", CultureInfo.InvariantCulture)}";
            }
            catch (FormatException error)
            {
                errors.Add($"HQ: {error.Message}");
            }
        }
        else
        {
            errors.Add($"HQ /demo/batches: {hq.Summary}");
        }

        _hqModeLine.Text = $"Chế độ HQ: {_hqMode}";
        return errors.Count == 0 ? null : string.Join("; ", errors);
    }

    private async Task<string?> RefreshJobsAsync()
    {
        if (_sql is null)
        {
            return "không có MSSQL_SA_PASSWORD nên không đọc được cảnh báo và dự báo";
        }

        var now = DateTime.UtcNow;
        var errors = new List<string>();
        try
        {
            var alerts = await _sql.OpenAlertsAsync(BusinessClock.Today(now));
            _alertChanges.Update(alerts.ToDictionary(a => a.BatchId, a => $"{a.AlertType}|{a.RemainingQty}|{a.DaysLeft}"), now);
            GridFiller.Fill(_alertGrid, alerts.Select(a => new GridRow(a.BatchId,
                new object?[] { a.StoreId, a.Sku, SkuName(a.Sku), a.BatchId, a.ExpiryDate.ToString("yyyy-MM-dd"), a.DaysLeft, a.RemainingQty, a.AlertType, a.Status },
                _alertChanges.IsHighlighted(a.BatchId, now) ? Theme.Changed : null,
                a.AlertType == "EXPIRED" ? Theme.Expired : Theme.Near)).ToList());
        }
        catch (Exception error)
        {
            errors.Add($"cảnh báo: {error.Message}");
        }

        try
        {
            var forecasts = await _sql.LatestForecastsAsync();
            _forecastEmpty.Text = forecasts.Count == 0 ? "  (bảng forecast chưa có dòng nào)" : $"  ({forecasts.Count} dòng)";
            GridFiller.Fill(_forecastGrid, forecasts.Select(f => new GridRow($"{f.StoreId}|{f.Sku}",
                new object?[]
                {
                    f.StoreId, f.Sku, SkuName(f.Sku), f.HorizonDays,
                    f.PredictedDemand.ToString("0.##", CultureInfo.InvariantCulture),
                    f.SurplusShortage.ToString("+0.##;-0.##;0", CultureInfo.InvariantCulture),
                    f.BalanceStatus, f.ModelVersion, LocalTime(f.CreatedAtUtc),
                },
                Fore: f.BalanceStatus switch { "SHORTAGE" => Theme.Expired, "SURPLUS" => Theme.Near, _ => null })).ToList());
        }
        catch (Exception error)
        {
            errors.Add($"dự báo: {error.Message}");
        }

        return errors.Count == 0 ? null : string.Join("; ", errors);
    }

    // --- Feature availability (404 rule) ------------------------------------

    private async Task ProbeFeaturesAsync()
    {
        var sync = _api.ProbeSyncRunAsync();
        var snapshot = _api.ProbeSnapshotAsync();
        var thresholds = _api.ProbeThresholdsAsync();
        await Task.WhenAll(sync, snapshot, thresholds);
        _syncFeature = Merge(_syncFeature, FeatureAvailability.FromProbe(sync.Result));
        _snapshotFeature = Merge(_snapshotFeature, FeatureAvailability.FromProbe(snapshot.Result));
        _nearExpiryFeature = Merge(_nearExpiryFeature, FeatureAvailability.FromProbe(thresholds.Result));
        UpdateFeatureControls();
    }

    private static FeatureState Merge(FeatureState current, FeatureState probed) =>
        probed == FeatureState.Unknown ? current : probed;

    private void UpdateFeatureControls()
    {
        _runSync.Enabled = _syncFeature != FeatureState.NotDeployed && !IsBusy(_runSync);
        _sendSnapshot.Enabled = _snapshotFeature != FeatureState.NotDeployed && !IsBusy(_sendSnapshot);
        _runNearExpiry.Enabled = _nearExpiryFeature != FeatureState.NotDeployed && !IsBusy(_runNearExpiry);
        _setThreshold.Enabled = _nearExpiryFeature != FeatureState.NotDeployed && !IsBusy(_setThreshold);
        _runForecast.Enabled = _forecastFeature != FeatureState.NotDeployed && !IsBusy(_runForecast);

        var syncReasons = new[]
        {
            _syncFeature == FeatureState.NotDeployed ? "Chạy đồng bộ: /sync/run chưa có trên middleware (404), chờ chu kỳ SYNC_INTERVAL." : null,
            _snapshotFeature == FeatureState.NotDeployed ? "Gửi snapshot: /hq/snapshot chưa có (404)." : null,
        }.Where(text => text is not null);
        _syncFeatureLine.Text = string.Join("   ", syncReasons);

        var jobReasons = new[]
        {
            _nearExpiryFeature == FeatureState.NotDeployed ? "Cận hạn và ngưỡng: chưa có trên middleware (404, chờ #43)." : null,
            _forecastFeature == FeatureState.NotDeployed ? "Dự báo: chưa có job forecast (404, chờ PB-22/23); mở lại bảng điều khiển sau khi merge." : null,
        }.Where(text => text is not null);
        _jobFeatureLine.Text = string.Join("   ", jobReasons);
    }

    // --- Actions --------------------------------------------------------------

    private async Task RunSyncAsync()
    {
        var answer = await RunActionAsync(_runSync, "Chạy đồng bộ", () => _api.RunSyncAsync());
        _syncFeature = FeatureAvailability.FromAction(answer, _syncFeature);
        if (answer.IsSuccess)
        {
            try
            {
                var run = ApiParsers.SyncRun(answer.Body);
                ShowResult($"Chạy đồng bộ: HTTP {answer.Status}, tạo {run.BatchesCreated} batch, gửi {run.BatchesSent}, còn chờ {run.BatchesPending}", Theme.Ok);
            }
            catch (FormatException error)
            {
                ShowResult($"Chạy đồng bộ: HTTP {answer.Status}, không đọc được câu trả lời: {error.Message}", Theme.Warn);
            }
        }

        UpdateFeatureControls();
        await RefreshAllAsync();
    }

    private async Task SetHqModeAsync(string mode)
    {
        var button = _modeButtons.First(item => item.Text == mode);
        var answer = await RunActionAsync(button, $"HQ {mode}", () => _api.SetHqModeAsync(mode));
        if (answer.IsSuccess)
        {
            try
            {
                _hqMode = $"{ApiParsers.DemoMode(answer.Body)} (đặt lúc {LocalTime(DateTime.UtcNow)})";
            }
            catch (FormatException)
            {
                _hqMode = $"{mode} (đặt lúc {LocalTime(DateTime.UtcNow)})";
            }

            foreach (var item in _modeButtons)
            {
                item.BackColor = item == button ? Theme.Changed : Color.FromArgb(230, 236, 245);
            }
        }

        await RefreshAllAsync();
    }

    private async Task SendSnapshotAsync()
    {
        var answer = await RunActionAsync(_sendSnapshot, "Gửi snapshot", () => _api.SendSnapshotAsync(DateTime.UtcNow));
        _snapshotFeature = FeatureAvailability.FromAction(answer, _snapshotFeature);
        if (answer.Status == 422 && answer.Code == "SNAPSHOT_REJECTED")
        {
            ShowResult($"Gửi snapshot: HTTP 422 SNAPSHOT_REJECTED, đúng như mong đợi: tồn không đổi, có audit SNAPSHOT_REJECTED", Theme.Ok);
        }

        UpdateFeatureControls();
        await RefreshAllAsync();
    }

    private async Task RunJobAsync(string name)
    {
        var button = name == "forecast" ? _runForecast : _runNearExpiry;
        var label = name == "forecast" ? "Chạy dự báo" : "Chạy kiểm tra cận hạn";
        var answer = await RunActionAsync(button, label, () => _api.RunJobAsync(name));
        if (answer.Status == 404 && answer.Code == "NOT_FOUND")
        {
            if (name == "forecast")
            {
                _forecastFeature = FeatureState.NotDeployed;
            }
            else
            {
                _nearExpiryFeature = FeatureState.NotDeployed;
            }
        }
        else if (answer.IsSuccess)
        {
            try
            {
                var run = ApiParsers.JobRun(answer.Body);
                ShowResult($"{label}: HTTP {answer.Status}, job {run.Job} {run.Status} ({answer.ElapsedMs / 1000:0.0} s)", Theme.Ok);
            }
            catch (FormatException error)
            {
                ShowResult($"{label}: HTTP {answer.Status}, không đọc được câu trả lời: {error.Message}", Theme.Warn);
            }
        }

        UpdateFeatureControls();
        await RefreshAllAsync();
    }

    private async Task SetThresholdAsync()
    {
        var category = (string)_thresholdCategory.SelectedItem!;
        var days = (int)_thresholdDays.Value;
        var answer = await RunActionAsync(_setThreshold, $"Ngưỡng {category} = {days}",
            () => _api.SetThresholdAsync(category, days));
        if (answer.Status == 404)
        {
            _nearExpiryFeature = FeatureState.NotDeployed;
        }

        UpdateFeatureControls();
    }

    /// <summary>Disables the button while the call runs and writes the answer to the result line.</summary>
    private async Task<ApiResult> RunActionAsync(Button button, string label, Func<Task<ApiResult>> call)
    {
        button.Enabled = false;
        button.Tag = "busy";
        ShowResult($"{label}: đang gửi...", Theme.Muted);
        try
        {
            var answer = await call();
            var colour = answer.IsSuccess ? Theme.Ok : answer.IsUnreachable || answer.Status >= 500 ? Theme.Error : Theme.Warn;
            ShowResult($"{label}: {answer.Summary}", colour);
            return answer;
        }
        finally
        {
            button.Tag = null;
            button.Enabled = true;
            UpdateFeatureControls();
        }
    }

    private static bool IsBusy(Control button) => Equals(button.Tag, "busy");

    private void ShowResult(string text, Color colour)
    {
        _resultLine.Text = $"[{LocalTime(DateTime.UtcNow)}] {text}";
        _resultLine.ForeColor = colour;
    }

    // --- Small helpers ------------------------------------------------------

    private static string StockKey(StockLine line) => $"{line.StoreId}|{line.Sku}";

    private string StoreLabel(string storeId) =>
        _storeNames.TryGetValue(storeId, out var name) && name.Length > 0 ? $"{storeId} {name}" : storeId;

    private string SkuName(string sku) => _productNames.TryGetValue(sku, out var name) ? name : string.Empty;

    private static string LocalTime(DateTime utc) =>
        BusinessClock.ToLocal(utc).ToString("HH:mm:ss", CultureInfo.InvariantCulture);

    private static Color? AuditColour(string action) => action switch
    {
        "EVENT_REJECTED" or "SNAPSHOT_REJECTED" => Theme.Expired,
        "DUPLICATE_EVENT" => Theme.Near,
        _ => null,
    };

    private static Color? SyncColour(string status) => status switch
    {
        "ACKED" => Theme.Ok,
        "FAILED" => Theme.Expired,
        "PENDING" => Theme.Near,
        _ => null,
    };

    private Label StatusLine()
    {
        var label = Theme.Line(_font);
        label.Dock = DockStyle.Top;
        label.Text = "Đang tải...";
        label.ForeColor = Theme.Muted;
        return label;
    }

    private Label Title(string text)
    {
        var label = Theme.Line(_font, bold: true);
        label.Text = text;
        return label;
    }

    private static FlowLayoutPanel ButtonRow(params Button[] buttons)
    {
        var row = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = true };
        row.Controls.AddRange(buttons);
        return row;
    }

    private TabPage Page(string title, Label status, Control content)
    {
        var page = new TabPage(title) { BackColor = Theme.Background, Padding = new Padding(8) };
        content.Font = Theme.Regular(_font);
        page.Controls.Add(content);
        page.Controls.Add(status);
        status.Font = Theme.Regular(_font);
        return page;
    }
}
