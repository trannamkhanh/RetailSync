using System.Globalization;
using StaffApp.Configuration;
using StaffApp.Models;
using StaffApp.Services;

namespace StaffApp.UI;

/// <summary>
/// DS-08: one window, three tabs (Lookup, Near-expiry alerts, Recommendations). The title bar
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
    private readonly ToolStripButton _retry = new("Retry") { Visible = false };
    private Func<Task>? _lastAction;

    // Lookup
    private readonly TextBox _barcode = new() { Width = 260 };
    private readonly Button _search = new() { Text = "Search", AutoSize = true };
    private readonly Label _product = new() { AutoSize = true };
    private readonly DataGridView _batches = Grid("Batch", "Expiry", "Qty");
    private readonly DataGridView _nearby = Grid("Store", "Distance", "Quantity");
    private readonly Label _nearbyNote = new() { AutoSize = true, ForeColor = Color.DimGray };

    // Alerts
    private readonly Label _alertCount = new() { AutoSize = true };
    private readonly DataGridView _alerts = Grid("Urgency", "Product", "Batch", "Expiry", "Days left", "Qty");
    private readonly Label _alertsEmpty = new() { AutoSize = true, ForeColor = Color.DimGray };

    // Recommendations
    private readonly DataGridView _recommendations = Grid("Action", "Product", "Level");
    private readonly Label _recommendationsEmpty = new() { AutoSize = true, ForeColor = Color.DimGray };
    private readonly Label _detailTitle = new() { AutoSize = true, MaximumSize = new Size(500, 0) };
    private readonly Label _detailExpiry = new() { AutoSize = true };
    private readonly Label _detailReason = new() { AutoSize = true, MaximumSize = new Size(500, 0) };
    private readonly ListBox _guardrails = new() { Height = 120, Width = 500, IntegralHeight = false };
    private readonly Button _accept = new() { Text = "Accept", AutoSize = true, Enabled = false };
    private readonly Button _reject = new() { Text = "Reject", AutoSize = true, Enabled = false };
    private RecommendationDetail? _detail;

    private bool _alertsLoaded;
    private bool _recommendationsLoaded;

    public MainForm(LoadedConfig config, StaffApiClient api)
    {
        _api = api;
        _storeId = config.TokenInfo.StoreId!;
        Text = $"RetailSync Staff App - {_storeId} | Staff: {config.TokenInfo.Subject}";
        Font = new Font("Segoe UI", config.Settings.FontSize);
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1000, 680);
        Size = new Size(1180, 780);

        var tabs = new TabControl { Dock = DockStyle.Fill };
        tabs.TabPages.Add(LookupTab());
        tabs.TabPages.Add(AlertsTab());
        tabs.TabPages.Add(RecommendationsTab());
        tabs.SelectedIndexChanged += async (_, _) => await OnTabChangedAsync(tabs.SelectedIndex);

        var statusBar = new StatusStrip();
        statusBar.Items.AddRange(new ToolStripItem[] { _status, _retry, _updated });
        _retry.Click += async (_, _) => { if (_lastAction is not null) { await _lastAction(); } };

        Controls.Add(tabs);
        Controls.Add(statusBar);
        if (config.TokenInfo.IsExpired(DateTimeOffset.UtcNow))
        {
            SetStatus(UserMessages.TokenInvalid, error: true);
        }
        else
        {
            SetStatus("Ready. Scan or enter a barcode.", error: false);
        }

        Shown += (_, _) => _barcode.Focus();
    }

    // --- Layout -------------------------------------------------------------

    private TabPage LookupTab()
    {
        var page = new TabPage("Lookup") { Padding = new Padding(12) };
        _product.Font = new Font(Font.FontFamily, Font.Size + 2, FontStyle.Bold);
        var searchRow = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, WrapContents = false };
        searchRow.Controls.Add(new Label { Text = "Scan or enter barcode", AutoSize = true, Margin = new Padding(0, 8, 8, 0) });
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

        var layout = Column(searchRow, _product, Heading("Batches in this store"), _batches,
            Heading("Nearby stores (nearest first)"), _nearbyNote, _nearby);
        layout.RowStyles[3] = new RowStyle(SizeType.Percent, 45);
        layout.RowStyles[6] = new RowStyle(SizeType.Percent, 55);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage AlertsTab()
    {
        var page = new TabPage("Near-expiry alerts") { Padding = new Padding(12) };
        var refresh = new Button { Text = "Refresh", AutoSize = true };
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
        var page = new TabPage("Recommendations") { Padding = new Padding(12) };
        var refresh = new Button { Text = "Refresh", AutoSize = true };
        refresh.Click += async (_, _) => await RunAsync(LoadRecommendationsAsync);
        var left = Column(refresh, _recommendationsEmpty, _recommendations);
        left.RowStyles[2] = new RowStyle(SizeType.Percent, 100);
        _recommendations.SelectionChanged += async (_, _) => await RunAsync(ShowSelectedAsync);

        _detailTitle.Font = new Font(Font.FontFamily, Font.Size + 1, FontStyle.Bold);
        var buttons = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
        buttons.Controls.Add(_accept);
        buttons.Controls.Add(_reject);
        _accept.Click += async (_, _) => await RunAsync(() => DecideAsync(accept: true));
        _reject.Click += async (_, _) => await RunAsync(() => DecideAsync(accept: false));
        var right = Column(Heading("Details"), _detailTitle, _detailExpiry, Heading("Reason"), _detailReason,
            Heading("Guardrails"), _guardrails, buttons);

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
            grid.Columns[index].FillWeight = column == "Batch" ? 220 : 100;
        }

        return grid;
    }

    // --- Actions ------------------------------------------------------------

    private async Task RunAsync(Func<Task> action)
    {
        _lastAction = action;
        _retry.Visible = false;
        try
        {
            await action();
        }
        catch (FormatException error)
        {
            Fail(UserMessages.Unexpected(error));
        }
        catch (Exception error)
        {
            // A UI action must never close the app.
            SetStatus($"Error: {error.Message}", error: true);
        }
    }

    private async Task OnTabChangedAsync(int index)
    {
        if (index == 1 && !_alertsLoaded)
        {
            await RunAsync(LoadAlertsAsync);
        }
        else if (index == 2 && !_recommendationsLoaded)
        {
            await RunAsync(LoadRecommendationsAsync);
        }
    }

    private async Task SearchAsync()
    {
        var barcode = _barcode.Text.Trim();
        _batches.Rows.Clear();
        _nearby.Rows.Clear();
        _nearbyNote.Text = string.Empty;
        if (!StaffApiClient.IsValidBarcode(barcode))
        {
            _product.Text = UserMessages.InvalidBarcode;
            return;
        }

        SetStatus($"Looking up {barcode}...", error: false);
        var result = await _api.GetProductAsync(barcode);
        if (!result.IsSuccess)
        {
            var message = UserMessages.For(result, ApiArea.Lookup);
            _product.Text = message.Text;
            Fail(message);
            return;
        }

        var product = ApiParsers.Product(result.Body);
        _product.Text = $"{product.Name}\n{product.Sku} | {product.Category} | " +
                        $"{product.UnitPrice.ToString("N0", Numbers)} VND\nIn this store: {product.Quantity}";
        foreach (var batch in product.Batches)
        {
            _batches.Rows.Add(batch.BatchId, Date(batch.ExpiryDate), batch.Quantity);
        }

        _batches.ClearSelection();

        var stock = await _api.GetCrossStoreStockAsync(barcode, _storeId);
        if (!stock.IsSuccess)
        {
            var message = UserMessages.For(stock, ApiArea.Lookup);
            _nearbyNote.Text = stock.Status == 404 ? UserMessages.NoStores : message.Text;
            Fail(message with { Text = $"Nearby stores: {message.Text}" });
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
        Done($"Found {product.Sku}.");
    }

    private async Task LoadAlertsAsync()
    {
        SetStatus("Loading near-expiry alerts...", error: false);
        var result = await _api.GetAlertsAsync();
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
            row.DefaultCellStyle.BackColor = alert.Urgency == "EXPIRED" ? ExpiredColor
                : alert.Urgency == "Today or tomorrow" ? SoonColor : SystemColors.Window;
        }

        _alerts.ClearSelection();
        _alertCount.Text = $"{alerts.Count} open alert{(alerts.Count == 1 ? string.Empty : "s")}";
        _alertsEmpty.Text = alerts.Count == 0 ? UserMessages.NoAlerts : string.Empty;
        Done("Near-expiry alerts loaded.");
    }

    private async Task LoadRecommendationsAsync()
    {
        SetStatus("Loading recommendations...", error: false);
        var result = await _api.GetRecommendationsAsync();
        if (!result.IsSuccess)
        {
            Fail(UserMessages.For(result, ApiArea.Recommendations));
            return;
        }

        _board.Replace(ApiParsers.Recommendations(result.Body));
        _recommendationsLoaded = true;
        BindRecommendations();
        Done("Recommendations loaded.");
    }

    private void BindRecommendations()
    {
        _recommendations.Rows.Clear();
        foreach (var line in _board.Rows)
        {
            var index = _recommendations.Rows.Add(line.ActionType, line.Sku, line.Level);
            _recommendations.Rows[index].Tag = line.RecId;
        }

        _recommendations.ClearSelection();
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
        SetStatus($"Loading recommendation {recId}...", error: false);
        var result = await _api.GetRecommendationAsync(recId);
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
        _detailExpiry.Text = _detail.ExpiryDate is { } expiry ? $"Expiry {Date(expiry)}" : "No batch";
        _detailReason.Text = _detail.Reason;
        _guardrails.Items.Clear();
        foreach (var line in _detail.GuardrailResults)
        {
            _guardrails.Items.Add(line.Text);
        }

        if (_detail.GuardrailResults.Count == 0)
        {
            _guardrails.Items.Add("No rule applies");
        }

        _accept.Enabled = _reject.Enabled = true;
        Done($"Recommendation {recId}.");
    }

    private async Task DecideAsync(bool accept)
    {
        if (_detail is null)
        {
            return;
        }

        var recId = _detail.Summary.RecId;
        var verb = accept ? "Accept" : "Reject";
        var answer = MessageBox.Show(this, $"{verb} this recommendation?\n\n{_detail.Title}\n\nA decision is final.",
            $"{verb} recommendation", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
        if (answer != DialogResult.Yes)
        {
            return;
        }

        _accept.Enabled = _reject.Enabled = false;
        SetStatus($"Sending {verb.ToLowerInvariant()} for recommendation {recId}...", error: false);
        var result = await _api.DecideAsync(recId, accept);
        var outcome = _board.Apply(recId, result);
        if (outcome.Removed)
        {
            BindRecommendations();
        }

        if (result.IsSuccess)
        {
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
            SetStatus(message.Text, error: true);
        }
    }

    private void ClearDetail()
    {
        _detail = null;
        _detailTitle.Text = "Select a recommendation";
        _detailExpiry.Text = string.Empty;
        _detailReason.Text = string.Empty;
        _guardrails.Items.Clear();
        _accept.Enabled = _reject.Enabled = false;
    }

    // --- Status bar ---------------------------------------------------------

    private void Done(string text)
    {
        SetStatus(text, error: false);
        _updated.Text = $"Updated {DateTime.Now:HH:mm:ss}";
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
