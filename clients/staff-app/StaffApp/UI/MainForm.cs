using System.Globalization;
using StaffApp.Configuration;
using StaffApp.Models;
using StaffApp.Services;

namespace StaffApp.UI;

/// <summary>
/// DS-08: one window, four tabs (Tra cứu, Cảnh báo cận hạn, Đề xuất, Giảm giá), labels in Vietnamese. The title bar
/// shows the store and the staff account of the token; the status bar shows loading, errors,
/// the last refresh time and Retry after a connection error. Every call is asynchronous.
/// </summary>
public sealed class MainForm : Form
{
    private static readonly CultureInfo Numbers = CultureInfo.GetCultureInfo("en-US");
    private static readonly Color ExpiredColor = Color.FromArgb(253, 226, 226);
    private static readonly Color SoonColor = Color.FromArgb(255, 243, 205);

    private readonly StaffApiClient _api;
    private readonly string _storeId;
    private readonly RecommendationBoard _board = new();

    private readonly ToolStripStatusLabel _status = new() { Spring = true, TextAlign = ContentAlignment.MiddleLeft };
    private readonly ToolStripStatusLabel _updated = new();
    private readonly ToolStripButton _retry = new("Thử lại") { Visible = false };
    private Func<Task>? _lastAction;

    // Lookup
    private readonly TextBox _barcode = new() { Width = 260 };
    private readonly Button _search = new() { Text = "Tìm", AutoSize = true };
    private readonly Label _product = new() { AutoSize = true };
    private readonly DataGridView _batches = Grid("Lô", "HSD", "SL");
    private readonly DataGridView _nearby = Grid("Cửa hàng", "Khoảng cách", "Số lượng");
    private readonly Label _nearbyNote = new() { AutoSize = true, ForeColor = Color.DimGray };
    private readonly LatestRequest _searchRequests = new();

    // Alerts
    private readonly Label _alertCount = new() { AutoSize = true };
    private readonly DataGridView _alerts = Grid("Mức độ", "Sản phẩm", "Lô", "HSD", "Còn (ngày)", "SL");
    private readonly Label _alertsEmpty = new() { AutoSize = true, ForeColor = Color.DimGray };

    // Recommendations
    private readonly DataGridView _recommendations = Grid("Hành động", "Sản phẩm", "Mức");
    private readonly Label _recommendationsEmpty = new() { AutoSize = true, ForeColor = Color.DimGray };
    private readonly Label _detailTitle = new() { AutoSize = true, MaximumSize = new Size(500, 0) };
    private readonly Label _detailExpiry = new() { AutoSize = true };
    private readonly Label _detailReason = new() { AutoSize = true, MaximumSize = new Size(500, 0) };
    private readonly ListBox _guardrails = new() { Height = 120, Width = 500, IntegralHeight = false };
    private readonly Button _accept = new() { Text = "Chấp nhận", AutoSize = true, Enabled = false };
    private readonly Button _reject = new() { Text = "Từ chối", AutoSize = true, Enabled = false };
    private RecommendationDetail? _detail;
    private readonly LatestRequest _detailRequests = new();
    // True while the grid is rebuilt: Rows.Add selects row 0 and fires SelectionChanged.
    private bool _binding;

    // Discounts (PB-50-3): read-only.
    private readonly RadioButton _ownStore = new() { Text = "Cửa hàng của tôi", AutoSize = true, Checked = true };
    private readonly RadioButton _allStores = new() { Text = "Tất cả cửa hàng", AutoSize = true };
    private readonly DataGridView _discounts = Grid(DiscountRows.Columns);
    private readonly Label _discountsEmpty = new() { AutoSize = true, ForeColor = Color.DimGray };
    private readonly LatestRequest _discountRequests = new();

    private bool _alertsLoaded;
    private bool _recommendationsLoaded;
    private bool _discountsLoaded;
    // A cell draws its text inside borders and margins that its padding does not count.
    private const int HeaderSlack = 12;
    // Cửa hàng and Sản phẩm wrap onto two lines, so the nine columns fit 1280 px at 125 % scaling.
    private static readonly int[] WrappedDiscountColumns = { 0, 2 };

    public MainForm(LoadedConfig config, StaffApiClient api)
    {
        _api = api;
        _storeId = config.TokenInfo.StoreId!;
        Text = $"RetailSync Staff App - {_storeId} | Nhân viên: {config.TokenInfo.Subject}";
        Font = new Font("Segoe UI", config.Settings.FontSize);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1000, 680);
        Size = new Size(1280, 780);  // the nine Giảm giá columns fit without a scroll bar

        var tabs = new TabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(LookupTab());
        tabs.TabPages.Add(AlertsTab());
        tabs.TabPages.Add(RecommendationsTab());
        tabs.TabPages.Add(DiscountsTab());
        tabs.SelectedIndexChanged += async (_, _) => await OnTabChangedAsync(tabs.SelectedIndex);

        var statusBar = new StatusStrip();
        statusBar.Items.AddRange(new ToolStripItem[] { _status, _retry, _updated });
        _retry.Click += async (_, _) => { if (_lastAction is not null) { await RunAsync(_lastAction); } };

        Controls.Add(tabs);
        Controls.Add(statusBar);
        if (config.TokenInfo.IsExpired(DateTimeOffset.UtcNow))
        {
            SetStatus(UserMessages.TokenInvalid, error: true);
        }
        else
        {
            SetStatus("Sẵn sàng. Quét hoặc nhập mã vạch.", error: false);
        }

        Shown += (_, _) => _barcode.Focus();
    }

    // --- Layout -------------------------------------------------------------

    private TabPage LookupTab()
    {
        var page = new TabPage("Tra cứu") { Padding = new Padding(12) };
        _product.Font = new Font(Font.FontFamily, Font.Size + 2, FontStyle.Bold);
        var searchRow = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
        searchRow.Controls.Add(new Label { Text = "Quét hoặc nhập mã vạch", AutoSize = true, Margin = new Padding(0, 8, 8, 0) });
        searchRow.Controls.Add(_barcode);
        searchRow.Controls.Add(_search);
        _search.Click += async (_, _) => await RunAsync(SearchAsync);
        _barcode.KeyDown += async (_, args) =>
        {
            if (args.KeyCode == Keys.Enter)
            {
                args.SuppressKeyPress = true;
                await RunAsync(SearchAsync);
            }
        };

        var layout = Column(searchRow, _product, Heading("Các lô tại cửa hàng này"), _batches,
            Heading("Cửa hàng lân cận (gần nhất trước)"), _nearbyNote, _nearby);
        layout.RowStyles[3] = new RowStyle(SizeType.Percent, 45);
        layout.RowStyles[6] = new RowStyle(SizeType.Percent, 55);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage AlertsTab()
    {
        var page = new TabPage("Cảnh báo cận hạn") { Padding = new Padding(12) };
        var refresh = new Button { Text = "Làm mới", AutoSize = true };
        refresh.Click += async (_, _) => await RunAsync(LoadAlertsAsync);
        var header = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
        _alertCount.Margin = new Padding(0, 8, 16, 0);
        header.Controls.Add(_alertCount);
        header.Controls.Add(refresh);
        var layout = Column(header, _alertsEmpty, _alerts);
        layout.RowStyles[2] = new RowStyle(SizeType.Percent, 100);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage RecommendationsTab()
    {
        var page = new TabPage("Đề xuất") { Padding = new Padding(12) };
        var refresh = new Button { Text = "Làm mới", AutoSize = true };
        refresh.Click += async (_, _) => await RunAsync(LoadRecommendationsAsync);
        var left = Column(refresh, _recommendationsEmpty, _recommendations);
        left.RowStyles[2] = new RowStyle(SizeType.Percent, 100);
        _recommendations.SelectionChanged += async (_, _) =>
        {
            if (!_binding)
            {
                await RunAsync(ShowSelectedAsync);
            }
        };

        _detailTitle.Font = new Font(Font.FontFamily, Font.Size + 1, FontStyle.Bold);
        var buttons = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
        buttons.Controls.Add(_accept);
        buttons.Controls.Add(_reject);
        _accept.Click += async (_, _) => await RunAsync(() => DecideAsync(accept: true));
        _reject.Click += async (_, _) => await RunAsync(() => DecideAsync(accept: false));
        var right = Column(Heading("Chi tiết"), _detailTitle, _detailExpiry, Heading("Lý do"), _detailReason,
            Heading("Quy tắc kiểm soát"), _guardrails, buttons);

        // Two columns: the list and the details, as in DS-08 screen 3.
        var columns = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 52));
        columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 48));
        right.Padding = new Padding(12, 0, 0, 0);
        columns.Controls.Add(left, 0, 0);
        columns.Controls.Add(right, 1, 0);
        page.Controls.Add(columns);
        ClearDetail();
        return page;
    }

    private TabPage DiscountsTab()
    {
        var page = new TabPage("Giảm giá") { Padding = new Padding(12) };
        var refresh = new Button { Text = "Làm mới", AutoSize = true };
        refresh.Click += async (_, _) => await RunAsync(LoadDiscountsAsync);
        // Only the button that becomes checked reloads, so one click is one call.
        _ownStore.CheckedChanged += async (_, _) => { if (_ownStore.Checked) { await RunAsync(LoadDiscountsAsync); } };
        _allStores.CheckedChanged += async (_, _) => { if (_allStores.Checked) { await RunAsync(LoadDiscountsAsync); } };
        var header = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
        _ownStore.Margin = _allStores.Margin = new Padding(0, 6, 16, 0);
        header.Controls.Add(_ownStore);
        header.Controls.Add(_allStores);
        header.Controls.Add(refresh);

        foreach (DataGridViewColumn column in _discounts.Columns)
        {
            column.SortMode = DataGridViewColumnSortMode.NotSortable;  // no room kept for a sort arrow
        }

        foreach (var index in WrappedDiscountColumns)
        {
            _discounts.Columns[index].DefaultCellStyle.WrapMode = DataGridViewTriState.True;
        }

        _discounts.AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.AllCells;

        var layout = Column(header, _discountsEmpty, _discounts);
        layout.RowStyles[2] = new RowStyle(SizeType.Percent, 100);
        page.Controls.Add(layout);
        return page;
    }

    private static TableLayoutPanel Column(params Control[] controls)
    {
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = controls.Length };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        foreach (var control in controls)
        {
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            control.Dock = control is DataGridView ? DockStyle.Fill : control.Dock;
            layout.Controls.Add(control);
        }

        return layout;
    }

    private static Label Heading(string text) =>
        new() { Text = text, AutoSize = true, Margin = new Padding(0, 12, 0, 4), ForeColor = Color.FromArgb(40, 70, 120) };

    private static DataGridView Grid(params string[] columns)
    {
        var grid = new DataGridView
        {
            ReadOnly = true,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            AllowUserToResizeRows = false,
            RowHeadersVisible = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            MultiSelect = false,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            BackgroundColor = SystemColors.Window,
            MinimumSize = new Size(0, 120),
            ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.AutoSize,
            EnableHeadersVisualStyles = false,
        };
        grid.DataBindingComplete += (_, _) => grid.ClearSelection();
        foreach (var column in columns)
        {
            var index = grid.Columns.Add(column.Replace(" ", string.Empty), column);
            // Batch ids such as B-STORE-DN1-SKU-0001-2 need more room than the figures.
            grid.Columns[index].FillWeight = column == "Lô" ? 220 : 100;
        }

        return grid;
    }

    // --- Actions ------------------------------------------------------------

    /// <summary>True once the window is closed: an answer that arrives later must not touch any control.</summary>
    private bool Gone => IsDisposed || Disposing;

    private async Task RunAsync(Func<Task> action)
    {
        _lastAction = action;
        _retry.Visible = false;
        try
        {
            await action();
        }
        catch (Exception) when (Gone)
        {
            // The window closed while the call ran (the client may be disposed too): nothing to show.
        }
        catch (FormatException error)
        {
            Fail(UserMessages.Unexpected(error));
        }
        catch (Exception error)
        {
            // A UI action must never close the app.
            SetStatus($"Lỗi: {error.Message}", error: true);
        }
    }

    private async Task OnTabChangedAsync(int index)
    {
        // Retry belongs to the screen that failed; a new tab starts without it.
        _retry.Visible = false;
        _lastAction = null;
        if (index == 1 && !_alertsLoaded)
        {
            await RunAsync(LoadAlertsAsync);
        }
        else if (index == 2 && !_recommendationsLoaded)
        {
            await RunAsync(LoadRecommendationsAsync);
        }
        else if (index == 3 && !_discountsLoaded)
        {
            await RunAsync(LoadDiscountsAsync);
        }
    }

    private async Task SearchAsync()
    {
        // A second Enter or scan makes the first search stale, so its answers never mix into the grids.
        var ticket = _searchRequests.Next();
        var barcode = _barcode.Text.Trim();
        _batches.Rows.Clear();
        _nearby.Rows.Clear();
        _nearbyNote.Text = string.Empty;
        if (!StaffApiClient.IsValidBarcode(barcode))
        {
            _product.Text = UserMessages.InvalidBarcode;
            return;
        }

        SetStatus($"Đang tra cứu {barcode}...", error: false);
        var result = await _api.GetProductAsync(barcode);
        if (!_searchRequests.Applies(ticket, Gone))
        {
            return;
        }

        if (!result.IsSuccess)
        {
            var message = UserMessages.For(result, ApiArea.Lookup);
            _product.Text = message.Text;
            Fail(message);
            return;
        }

        var product = ApiParsers.Product(result.Body);
        _product.Text = $"{product.Name}\n{product.Sku} | {DisplayNames.Category(product.Category)} | " +
                        $"{product.UnitPrice.ToString("N0", Numbers)} VND\nTại cửa hàng này: {product.Quantity}";
        foreach (var batch in product.Batches)
        {
            _batches.Rows.Add(batch.BatchId, Date(batch.ExpiryDate), batch.Quantity);
        }

        _batches.ClearSelection();

        var stock = await _api.GetCrossStoreStockAsync(barcode, _storeId);
        if (!_searchRequests.Applies(ticket, Gone))
        {
            return;
        }

        if (!stock.IsSuccess)
        {
            var message = UserMessages.For(stock, ApiArea.Lookup);
            _nearbyNote.Text = stock.Status == 404 ? UserMessages.NoStores : message.Text;
            Fail(message with { Text = $"Cửa hàng lân cận: {message.Text}" });
            return;
        }

        var stores = ApiParsers.CrossStore(stock.Body).Stores;
        foreach (var store in stores)
        {
            _nearby.Rows.Add(store.Name, $"{store.DistanceKm.ToString("0.0", Numbers)} km", store.Qty);
        }

        _nearby.ClearSelection();
        _nearbyNote.Text = stores.Count == 0 ? UserMessages.NoStores
            : stores.All(store => store.Qty == 0) ? UserMessages.NoStock : string.Empty;
        Done($"Đã tìm thấy {product.Sku}.");
    }

    private async Task LoadAlertsAsync()
    {
        SetStatus("Đang tải cảnh báo cận hạn...", error: false);
        var result = await _api.GetAlertsAsync();
        if (Gone)
        {
            return;
        }

        if (!result.IsSuccess)
        {
            Fail(UserMessages.For(result, ApiArea.Alerts));
            return;
        }

        var alerts = ApiParsers.Alerts(result.Body);
        _alertsLoaded = true;
        _alerts.Rows.Clear();
        foreach (var alert in alerts)
        {
            var row = _alerts.Rows[_alerts.Rows.Add(alert.Urgency, alert.Sku, alert.BatchId, Date(alert.ExpiryDate),
                alert.DaysToExpiry, alert.RemainingQty)];
            row.DefaultCellStyle.BackColor = alert.IsExpired ? ExpiredColor
                : alert.DaysToExpiry <= 1 ? SoonColor : SystemColors.Window;
        }

        _alerts.ClearSelection();
        _alertCount.Text = $"{alerts.Count} cảnh báo đang mở";
        _alertsEmpty.Text = alerts.Count == 0 ? UserMessages.NoAlerts : string.Empty;
        Done("Đã tải cảnh báo cận hạn.");
    }

    private async Task LoadRecommendationsAsync()
    {
        SetStatus("Đang tải đề xuất...", error: false);
        var result = await _api.GetRecommendationsAsync();
        if (Gone)
        {
            return;
        }

        if (!result.IsSuccess)
        {
            Fail(UserMessages.For(result, ApiArea.Recommendations));
            return;
        }

        _board.Replace(ApiParsers.Recommendations(result.Body));
        _recommendationsLoaded = true;
        BindRecommendations();
        Done("Đã tải đề xuất.");
    }

    private async Task LoadDiscountsAsync()
    {
        var all = _allStores.Checked;
        var ticket = _discountRequests.Next();
        SetStatus("Đang tải giảm giá...", error: false);
        var result = await _api.GetDiscountsAsync(all);
        if (!_discountRequests.Applies(ticket, Gone))
        {
            return;  // the scope changed or the window closed while this answer was on its way
        }

        if (!result.IsSuccess)
        {
            // Never leave the previous scope's rows under the new choice; the next visit reloads.
            _discounts.Rows.Clear();
            _discountsEmpty.Text = string.Empty;
            _discountsLoaded = false;
            Fail(UserMessages.For(result, ApiArea.Discounts));
            return;
        }

        var lines = ApiParsers.Discounts(result.Body);
        _discountsLoaded = true;
        _discounts.Rows.Clear();
        foreach (var line in lines)
        {
            _discounts.Rows.Add(DiscountRows.Cells(line, _storeId, TimeZoneInfo.Local));
        }

        // Nine columns in one width: no cell text is cut, each header takes at most two lines,
        // the rest of the width is shared.
        foreach (DataGridViewColumn column in _discounts.Columns)
        {
            var style = column.HeaderCell.InheritedStyle;
            var header = DiscountRows.TwoLineWidth(column.HeaderText,
                text => TextRenderer.MeasureText(text, style.Font ?? _discounts.Font).Width)
                + style.Padding.Horizontal + HeaderSlack;
            var cells = WrappedDiscountColumns.Contains(column.Index)
                ? TwoLineCellWidth(column)
                : column.GetPreferredWidth(DataGridViewAutoSizeColumnMode.AllCellsExceptHeader, true);
            column.MinimumWidth = Math.Max(header, cells);
            // Share the spare width in the same proportion, so no column is pushed past the grid.
            column.FillWeight = column.MinimumWidth;
        }

        _discounts.ClearSelection();
        _discountsEmpty.Text = lines.Count == 0 ? UserMessages.NoDiscounts : string.Empty;
        Done(all ? "Đã tải giảm giá của tất cả cửa hàng." : "Đã tải giảm giá của cửa hàng.");
    }

    /// <summary>The width that shows every cell of a wrapping column in at most two lines.</summary>
    private int TwoLineCellWidth(DataGridViewColumn column) =>
        _discounts.Rows.Cast<DataGridViewRow>()
            .Select(row => row.Cells[column.Index])
            .Select(cell => DiscountRows.TwoLineWidth(cell.FormattedValue?.ToString() ?? string.Empty,
                    text => TextRenderer.MeasureText(text, cell.InheritedStyle.Font ?? _discounts.Font).Width)
                + cell.InheritedStyle.Padding.Horizontal + HeaderSlack)
            .DefaultIfEmpty(0)
            .Max();

    private void BindRecommendations()
    {
        _binding = true;
        try
        {
            _recommendations.Rows.Clear();
            foreach (var line in _board.Rows)
            {
                var index = _recommendations.Rows.Add(line.ActionLabel, line.Sku, line.Level);
                _recommendations.Rows[index].Tag = line.RecId;
            }

            _recommendations.ClearSelection();
        }
        finally
        {
            _binding = false;
        }

        _recommendationsEmpty.Text = _board.Rows.Count == 0 ? UserMessages.NoRecommendations : string.Empty;
        ClearDetail();
    }

    private async Task ShowSelectedAsync()
    {
        if (_recommendations.SelectedRows.Count == 0 || _recommendations.SelectedRows[0].Tag is not long recId)
        {
            ClearDetail();
            return;
        }

        if (_detail?.Summary.RecId == recId)
        {
            return;
        }

        ClearDetail();
        var ticket = _detailRequests.Next();
        SetStatus($"Đang tải đề xuất {recId}...", error: false);
        var result = await _api.GetRecommendationAsync(recId);
        if (!_detailRequests.Applies(ticket, Gone))
        {
            return;  // the user selected another row, the list was rebuilt, or the window closed
        }

        if (!result.IsSuccess)
        {
            var message = UserMessages.For(result, ApiArea.Detail);
            Fail(message);
            if (message.Refresh)
            {
                await LoadRecommendationsAsync();
            }

            return;
        }

        _detail = ApiParsers.Detail(result.Body);
        _detailTitle.Text = _detail.Title;
        _detailExpiry.Text = _detail.ExpiryDate is { } expiry ? $"HSD {Date(expiry)}" : "Không theo lô";
        _detailReason.Text = _detail.Reason;
        _guardrails.Items.Clear();
        foreach (var line in _detail.GuardrailResults)
        {
            _guardrails.Items.Add(line.Text);
        }

        if (_detail.GuardrailResults.Count == 0)
        {
            _guardrails.Items.Add("Không có quy tắc nào áp dụng");
        }

        _accept.Enabled = _reject.Enabled = true;
        Done($"Đề xuất {recId}.");
    }

    private async Task DecideAsync(bool accept)
    {
        if (_detail is null)
        {
            return;
        }

        var recId = _detail.Summary.RecId;
        var verb = accept ? "Chấp nhận" : "Từ chối";
        var answer = MessageBox.Show(this, $"{verb} đề xuất này?\n\n{_detail.Title}\n\nQuyết định không thể thay đổi.",
            $"{verb} đề xuất", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes)
        {
            return;
        }

        _accept.Enabled = _reject.Enabled = false;
        SetStatus($"Đang gửi quyết định {verb.ToLowerInvariant()} đề xuất {recId}...", error: false);
        var result = await _api.DecideAsync(recId, accept);
        if (Gone)
        {
            return;
        }

        var outcome = _board.Apply(recId, result);
        if (outcome.Removed)
        {
            BindRecommendations();
        }

        if (result.IsSuccess)
        {
            if (accept)
            {
                _discountsLoaded = false;  // an accepted discount shows when the Giảm giá tab is opened again
            }

            Done(outcome.Message);
            return;
        }

        var message = UserMessages.For(result, ApiArea.Decision);
        Fail(message);
        if (!outcome.Removed)
        {
            _accept.Enabled = _reject.Enabled = true;
        }

        if (outcome.Refresh)
        {
            MessageBox.Show(this, message.Text, "RetailSync Staff App", MessageBoxButtons.OK, MessageBoxIcon.Information);
            await LoadRecommendationsAsync();
            if (!Gone)
            {
                SetStatus(message.Text, error: true);
            }
        }
    }

    private void ClearDetail()
    {
        _detailRequests.Invalidate();
        _detail = null;
        _detailTitle.Text = "Chọn một đề xuất";
        _detailExpiry.Text = string.Empty;
        _detailReason.Text = string.Empty;
        _guardrails.Items.Clear();
        _accept.Enabled = _reject.Enabled = false;
    }

    // --- Status bar ---------------------------------------------------------

    private void Done(string text)
    {
        SetStatus(text, error: false);
        _updated.Text = $"Cập nhật lúc {DateTime.Now:HH:mm:ss}";
    }

    private void Fail(UserMessage message)
    {
        SetStatus(message.Text, error: true);
        _retry.Visible = message.CanRetry;
    }

    private void SetStatus(string text, bool error)
    {
        _status.Text = text;
        _status.ForeColor = error ? Color.Firebrick : SystemColors.ControlText;
    }

    private static string Date(DateOnly date) => date.ToString("dd/MM/yyyy", CultureInfo.InvariantCulture);
}
