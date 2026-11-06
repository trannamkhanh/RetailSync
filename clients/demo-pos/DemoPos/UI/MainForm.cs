using System.ComponentModel;
using System.Security.Cryptography.X509Certificates;
using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Security;
using DemoPos.Services;

namespace DemoPos.UI;

/// <summary>The demo screen: POS, monitor panels, terminals table and request log.</summary>
public sealed class MainForm : Form
{
    private sealed record PendingRequest(TerminalConfig Terminal, string RawBody, bool ClearCartOnSuccess);

    private readonly LoadedConfig _loaded;
    private readonly AppConfig _config;
    private readonly RequestLog _requestLog = new();
    private readonly Dictionary<string, List<TxnRecord>> _historyByPos = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, TerminalClient> _liveClients = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, ClientCertificateInfo> _certificates = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, TerminalRow> _terminalRows = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, ProductConfig> _productConfigs;
    private readonly List<ProductRow> _allProducts;
    private readonly BindingList<ProductRow> _productView = new();
    private readonly BindingList<CartItem> _cart = new();
    private readonly BindingList<TxnRecord> _historyView = new();
    private readonly BindingList<TerminalRow> _terminalsView = new();
    private readonly BindingList<RequestLogEntry> _logView = new();
    private readonly BindingList<StockRow> _stockView = new();
    private readonly BindingList<AuditRow> _auditView = new();
    private readonly MockPosBackend _mockBackend;
    private readonly System.Windows.Forms.Timer _monitorTimer = new() { Interval = 2000 };
    private readonly System.Windows.Forms.Timer _statusTimer = new() { Interval = 5000 };

    private X509Certificate2? _authority;
    private MonitorApiClient? _monitorClient;
    private GatewayProbe? _gatewayProbe;
    private bool _mockMode;
    private bool _busy;
    private bool _monitorBusy;
    private bool _statusBusy;
    private bool _closing;
    private PendingRequest? _pendingRetry;

    private readonly ComboBox _terminalCombo = new();
    private readonly Label _terminalInfo = new();
    private readonly Label _modeLabel = new();
    private readonly TabControl _tabs = new();
    private readonly TextBox _searchBox = new();
    private readonly DataGridView _productGrid = new();
    private readonly Button _addButton = new();
    private readonly DataGridView _cartGrid = new();
    private readonly Button _payButton = new();
    private readonly Button _clearButton = new();
    private readonly Label _cartTotal = new();
    private readonly ResultPanel _resultPanel = new();
    private readonly DataGridView _historyGrid = new();
    private readonly Button _returnButton = new();
    private readonly Button _cancelButton = new();
    private readonly Button _sendAgainButton = new();
    private readonly ScenarioPanel _scenarioPanel = new();
    private readonly DataGridView _terminalsGrid = new();
    private readonly DataGridView _stockGrid = new();
    private readonly DataGridView _auditGrid = new();
    private readonly Label _stockStatus = new();
    private readonly Label _auditStatus = new();
    private readonly Button _refreshMonitor = new();
    private readonly DataGridView _logGrid = new();
    private readonly ComboBox _logFilter = new();
    private readonly TextBox _logDetails = new();
    private readonly StatusStrip _statusStrip = new();
    private readonly ToolStripStatusLabel _middlewareStatus = new();
    private readonly ToolStripStatusLabel _gatewayStatus = new();
    private readonly ToolStripStatusLabel _filesStatus = new();
    private readonly ToolStripStatusLabel _modeStatus = new();
    private readonly ToolStripStatusLabel _clockStatus = new();
    private RowStyle? _scenarioRowStyle;

    public MainForm(LoadedConfig loaded)
    {
        _loaded = loaded;
        _config = loaded.Config;
        _mockMode = _config.UseMock;
        _productConfigs = _config.Products.ToDictionary(product => product.Sku,
            product => product, StringComparer.OrdinalIgnoreCase);
        _allProducts = _config.Products
            .Select(product => new ProductRow
            {
                Sku = product.Sku,
                Name = product.Name,
                Barcode = product.Barcode,
                UnitPrice = product.UnitPrice,
            })
            .ToList();
        _mockBackend = new MockPosBackend(_config, _requestLog);

        BuildUi();
        LoadCertificates();
        PopulateTerminals();
        WireEvents();

        if (!_mockMode)
        {
            _authority = ServerCertificateValidator.LoadAuthority(_loaded.Paths.CaCertificate);
            _monitorClient = new MonitorApiClient(_config.MonitorBaseUrl, _authority, _requestLog);
            _gatewayProbe = new GatewayProbe(_authority);
        }

        ApplyMode();
        RefreshProducts();
        UpdateCartTotal();
        RefreshLogView();
        _monitorTimer.Start();
        _statusTimer.Start();

        Shown += async (_, _) =>
        {
            await RefreshStatusAsync();
            await RefreshMonitorAsync();
        };
        FormClosing += OnFormClosing;
    }

    internal TabControl Tabs => _tabs;

    internal ComboBox TerminalCombo => _terminalCombo;

    internal DataGridView ProductGrid => _productGrid;

    internal DataGridView CartGrid => _cartGrid;

    internal DataGridView HistoryGrid => _historyGrid;

    internal ResultPanel Result => _resultPanel;

    internal DataGridView TerminalsGrid => _terminalsGrid;

    internal DataGridView RequestLogGrid => _logGrid;

    internal ScenarioPanel Scenarios => _scenarioPanel;

    internal bool IsMockMode => _mockMode;

    internal RequestLog RequestLog => _requestLog;

    internal void SelectTerminal(string posId)
    {
        var index = _config.Terminals.FindIndex(terminal =>
            string.Equals(terminal.PosId, posId, StringComparison.OrdinalIgnoreCase));
        if (index >= 0)
        {
            _terminalCombo.SelectedIndex = index;
        }
    }

    internal void AddProductToCart(string sku, int quantity = 1)
    {
        var product = _allProducts.FirstOrDefault(item =>
            string.Equals(item.Sku, sku, StringComparison.OrdinalIgnoreCase));
        if (product is not null)
        {
            AddToCart(product, quantity);
        }
    }

    internal Task<PosResult> PayAsync() => PayCoreAsync();

    internal async Task ToggleMockAsync()
    {
        if (_closing)
        {
            return;
        }

        if (!_mockMode)
        {
            _mockMode = true;
            _config.UseMock = true;
            ApplyMode();
            _resultPanel.ShowInfo("Đang ở chế độ MOCK — dữ liệu không đến middleware.");
            await RefreshMonitorAsync();
            await RefreshStatusAsync();
            return;
        }

        if (!CanUseLive(out var reason))
        {
            MessageBox.Show(this, reason, "Chưa thể chuyển sang LIVE",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        _authority ??= ServerCertificateValidator.LoadAuthority(_loaded.Paths.CaCertificate);
        _monitorClient ??= new MonitorApiClient(_config.MonitorBaseUrl, _authority, _requestLog);
        _gatewayProbe ??= new GatewayProbe(_authority);
        _mockMode = false;
        _config.UseMock = false;
        ApplyMode();
        _resultPanel.ShowInfo("Đang ở chế độ LIVE — mọi request đi vào middleware thật.");
        await RefreshMonitorAsync();
        await RefreshStatusAsync();
    }

    private void BuildUi()
    {
        Text = "RetailSync Demo POS";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(1200, 760);
        Size = new Size(1420, 900);
        KeyPreview = true;
        AutoScaleMode = AutoScaleMode.Dpi;
        Font = new Font("Segoe UI", 9.5F);

        var toolbar = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            Height = 46,
            Padding = new Padding(10, 8, 10, 4),
            WrapContents = false,
            BackColor = Color.FromArgb(245, 247, 250),
        };
        toolbar.Controls.Add(new Label
        {
            Text = "Terminal",
            AutoSize = true,
            Margin = new Padding(3, 8, 6, 3),
            Font = new Font("Segoe UI", 9.5F, FontStyle.Bold),
        });
        _terminalCombo.DropDownStyle = ComboBoxStyle.DropDownList;
        _terminalCombo.DisplayMember = nameof(TerminalConfig.DisplayName);
        _terminalCombo.Width = 300;
        _terminalCombo.Margin = new Padding(3, 6, 12, 3);
        toolbar.Controls.Add(_terminalCombo);

        _terminalInfo.AutoSize = true;
        _terminalInfo.Margin = new Padding(3, 9, 16, 3);
        _terminalInfo.ForeColor = Color.FromArgb(70, 70, 70);
        toolbar.Controls.Add(_terminalInfo);

        _modeLabel.AutoSize = true;
        _modeLabel.Margin = new Padding(3, 7, 3, 3);
        _modeLabel.Font = new Font("Segoe UI", 11F, FontStyle.Bold);
        toolbar.Controls.Add(_modeLabel);

        _tabs.Dock = DockStyle.Fill;
        _tabs.Font = new Font("Segoe UI", 9.5F);
        _tabs.Padding = new Point(14, 4);
        _tabs.TabPages.Add(BuildPosPage());
        _tabs.TabPages.Add(BuildMonitorPage());
        _tabs.TabPages.Add(BuildTerminalsPage());
        _tabs.TabPages.Add(BuildLogPage());

        _statusStrip.Dock = DockStyle.Bottom;
        _statusStrip.SizingGrip = false;
        _middlewareStatus.Text = "Middleware: —";
        _gatewayStatus.Text = "Gateway: —";
        _filesStatus.Text = "CA: — · tokens: —";
        _modeStatus.Text = "LIVE";
        _clockStatus.Text = string.Empty;
        _clockStatus.Spring = true;
        _clockStatus.TextAlign = ContentAlignment.MiddleRight;
        _statusStrip.Items.AddRange(new ToolStripItem[]
        {
            _middlewareStatus,
            new ToolStripSeparator(),
            _gatewayStatus,
            new ToolStripSeparator(),
            _filesStatus,
            new ToolStripSeparator(),
            _modeStatus,
            _clockStatus,
        });

        Controls.Add(_tabs);
        Controls.Add(toolbar);
        Controls.Add(_statusStrip);
        KeyDown += OnFormKeyDown;
    }

    private TabPage BuildPosPage()
    {
        var page = new TabPage("Bán hàng") { Padding = new Padding(6) };
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 4,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 54));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 46));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 44));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 125));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 56));
        _scenarioRowStyle = new RowStyle(SizeType.Absolute, 0);
        layout.RowStyles.Add(_scenarioRowStyle);

        var products = new GroupBox { Text = "Sản phẩm", Dock = DockStyle.Fill, Padding = new Padding(8) };
        var productLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        productLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        productLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        productLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));

        var search = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        search.Controls.Add(new Label { Text = "Tìm", AutoSize = true, Margin = new Padding(3, 8, 4, 3) });
        _searchBox.Width = 240;
        _searchBox.PlaceholderText = "SKU, tên hoặc barcode";
        _searchBox.Margin = new Padding(3, 4, 3, 3);
        search.Controls.Add(_searchBox);
        productLayout.Controls.Add(search, 0, 0);

        ConfigureGrid(_productGrid);
        AddColumn(_productGrid, nameof(ProductRow.Sku), "SKU", 70);
        AddColumn(_productGrid, nameof(ProductRow.Name), "Tên", 210);
        AddColumn(_productGrid, nameof(ProductRow.Barcode), "Barcode", 110);
        AddColumn(_productGrid, nameof(ProductRow.UnitPriceText), "Giá", 70);
        _productGrid.DataSource = _productView;
        productLayout.Controls.Add(_productGrid, 0, 1);

        _addButton.Text = "Thêm vào giỏ (Enter)";
        _addButton.Dock = DockStyle.Left;
        _addButton.AutoSize = true;
        productLayout.Controls.Add(_addButton, 0, 2);
        products.Controls.Add(productLayout);

        var cartGroup = new GroupBox { Text = "Giỏ hàng", Dock = DockStyle.Fill, Padding = new Padding(8) };
        var cartLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        cartLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        cartLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
        ConfigureGrid(_cartGrid);
        _cartGrid.ReadOnly = false;
        AddColumn(_cartGrid, nameof(CartItem.Sku), "SKU", 70, readOnly: true);
        AddColumn(_cartGrid, nameof(CartItem.Name), "Tên", 170, readOnly: true);
        AddColumn(_cartGrid, nameof(CartItem.Quantity), "SL", 45, readOnly: false);
        AddColumn(_cartGrid, nameof(CartItem.UnitPrice), "Đơn giá", 70, readOnly: true);
        AddColumn(_cartGrid, nameof(CartItem.LineTotal), "Thành tiền", 80, readOnly: true);
        _cartGrid.DataSource = _cart;
        cartLayout.Controls.Add(_cartGrid, 0, 0);

        var cartButtons = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight };
        _cartTotal.AutoSize = true;
        _cartTotal.Font = new Font("Segoe UI", 10F, FontStyle.Bold);
        _cartTotal.Margin = new Padding(4, 10, 14, 3);
        cartButtons.Controls.Add(_cartTotal);
        _clearButton.Text = "Xóa giỏ";
        _clearButton.AutoSize = true;
        cartButtons.Controls.Add(_clearButton);
        _payButton.Text = "Pay · gửi SALE (F9)";
        _payButton.AutoSize = true;
        _payButton.BackColor = Color.FromArgb(30, 122, 52);
        _payButton.ForeColor = Color.White;
        _payButton.FlatStyle = FlatStyle.Flat;
        cartButtons.Controls.Add(_payButton);
        cartLayout.Controls.Add(cartButtons, 0, 1);
        cartGroup.Controls.Add(cartLayout);

        layout.Controls.Add(products, 0, 0);
        layout.Controls.Add(cartGroup, 1, 0);

        _resultPanel.Dock = DockStyle.Fill;
        layout.Controls.Add(_resultPanel, 0, 1);
        layout.SetColumnSpan(_resultPanel, 2);

        var historyGroup = new GroupBox { Text = "Lịch sử sự kiện của terminal", Dock = DockStyle.Fill, Padding = new Padding(8) };
        var historyLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        historyLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        historyLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var historyButtons = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        _returnButton.Text = "Return…";
        _returnButton.AutoSize = true;
        _returnButton.Enabled = false;
        _cancelButton.Text = "Cancel";
        _cancelButton.AutoSize = true;
        _cancelButton.Enabled = false;
        _sendAgainButton.Text = "Send again (cùng transaction_id)";
        _sendAgainButton.AutoSize = true;
        _sendAgainButton.Enabled = false;
        historyButtons.Controls.Add(_returnButton);
        historyButtons.Controls.Add(_cancelButton);
        historyButtons.Controls.Add(_sendAgainButton);
        historyButtons.Controls.Add(new Label
        {
            Text = "Chọn một dòng SALE đã OK để Return/Cancel.",
            AutoSize = true,
            ForeColor = Color.FromArgb(90, 90, 90),
            Margin = new Padding(12, 8, 3, 3),
        });
        historyLayout.Controls.Add(historyButtons, 0, 0);

        ConfigureGrid(_historyGrid);
        AddColumn(_historyGrid, nameof(TxnRecord.TimeText), "Giờ", 65);
        AddColumn(_historyGrid, nameof(TxnRecord.TypeText), "Loại", 90);
        AddColumn(_historyGrid, nameof(TxnRecord.TransactionId), "Transaction id", 230);
        AddColumn(_historyGrid, nameof(TxnRecord.ItemsText), "Items", 200);
        AddColumn(_historyGrid, nameof(TxnRecord.Outcome), "Kết quả", 85);
        AddColumn(_historyGrid, nameof(TxnRecord.Code), "Code", 150);
        _historyGrid.DataSource = _historyView;
        historyLayout.Controls.Add(_historyGrid, 0, 1);
        historyGroup.Controls.Add(historyLayout);

        layout.Controls.Add(historyGroup, 0, 2);
        layout.SetColumnSpan(historyGroup, 2);

        _scenarioPanel.Dock = DockStyle.Fill;
        _scenarioPanel.Visible = false;
        layout.Controls.Add(_scenarioPanel, 0, 3);
        layout.SetColumnSpan(_scenarioPanel, 2);

        page.Controls.Add(layout);
        return page;
    }

    private TabPage BuildMonitorPage()
    {
        var page = new TabPage("Monitor (chỉ đọc)") { Padding = new Padding(6) };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        _refreshMonitor.Text = "Refresh ngay";
        _refreshMonitor.AutoSize = true;
        top.Controls.Add(_refreshMonitor);
        top.Controls.Add(new Label
        {
            Text = "Tự động mỗi 2 giây · tồn kho dùng staff_dn*, audit dùng auditor",
            AutoSize = true,
            Margin = new Padding(12, 8, 3, 3),
            ForeColor = Color.FromArgb(90, 90, 90),
        });
        layout.Controls.Add(top, 0, 0);

        var columns = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1 };
        columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 42));
        columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 58));

        var stockGroup = new GroupBox { Text = "Tồn kho của store", Dock = DockStyle.Fill, Padding = new Padding(8) };
        var stockLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        stockLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        stockLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
        ConfigureGrid(_stockGrid);
        AddColumn(_stockGrid, nameof(StockRow.Sku), "SKU", 80);
        AddColumn(_stockGrid, nameof(StockRow.Name), "Tên", 210);
        AddColumn(_stockGrid, nameof(StockRow.Quantity), "SL", 60);
        _stockGrid.DataSource = _stockView;
        stockLayout.Controls.Add(_stockGrid, 0, 0);
        _stockStatus.AutoSize = true;
        _stockStatus.ForeColor = Color.FromArgb(90, 90, 90);
        stockLayout.Controls.Add(_stockStatus, 0, 1);
        stockGroup.Controls.Add(stockLayout);

        var auditGroup = new GroupBox { Text = "Audit log — 20 dòng mới nhất", Dock = DockStyle.Fill, Padding = new Padding(8) };
        var auditLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        auditLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        auditLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 24));
        ConfigureGrid(_auditGrid);
        AddColumn(_auditGrid, nameof(AuditRow.TimeText), "Giờ", 70);
        AddColumn(_auditGrid, nameof(AuditRow.Action), "Action", 120);
        AddColumn(_auditGrid, nameof(AuditRow.EntityKey), "Entity key", 220);
        AddColumn(_auditGrid, nameof(AuditRow.Details), "Details", 260);
        _auditGrid.DataSource = _auditView;
        auditLayout.Controls.Add(_auditGrid, 0, 0);
        _auditStatus.AutoSize = true;
        _auditStatus.ForeColor = Color.FromArgb(90, 90, 90);
        auditLayout.Controls.Add(_auditStatus, 0, 1);
        auditGroup.Controls.Add(auditLayout);

        columns.Controls.Add(stockGroup, 0, 0);
        columns.Controls.Add(auditGroup, 1, 0);
        layout.Controls.Add(columns, 0, 1);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage BuildTerminalsPage()
    {
        var page = new TabPage("Terminals") { Padding = new Padding(6) };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.Controls.Add(new Label
        {
            Text = "6 máy POS đã cấu hình. Fingerprint là 12 ký tự đầu của SHA-256 (DER).",
            AutoSize = true,
            Margin = new Padding(3, 8, 3, 3),
            ForeColor = Color.FromArgb(70, 70, 70),
        }, 0, 0);
        ConfigureGrid(_terminalsGrid);
        AddColumn(_terminalsGrid, nameof(TerminalRow.StoreName), "Store", 160);
        AddColumn(_terminalsGrid, nameof(TerminalRow.PosId), "POS id", 110);
        AddColumn(_terminalsGrid, nameof(TerminalRow.CertificateText), "Cert", 60);
        AddColumn(_terminalsGrid, nameof(TerminalRow.KeyText), "Key", 60);
        AddColumn(_terminalsGrid, nameof(TerminalRow.Fingerprint), "Fingerprint (12)", 130);
        AddColumn(_terminalsGrid, nameof(TerminalRow.LastResult), "Kết quả gần nhất", 150);
        AddColumn(_terminalsGrid, nameof(TerminalRow.LastTime), "Lúc", 80);
        _terminalsGrid.DataSource = _terminalsView;
        layout.Controls.Add(_terminalsGrid, 0, 1);
        page.Controls.Add(layout);
        return page;
    }

    private TabPage BuildLogPage()
    {
        var page = new TabPage("Request log") { Padding = new Padding(6) };
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 60));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 40));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false };
        top.Controls.Add(new Label { Text = "Hiển thị", AutoSize = true, Margin = new Padding(3, 8, 4, 3) });
        _logFilter.DropDownStyle = ComboBoxStyle.DropDownList;
        _logFilter.Items.AddRange(new object[]
        {
            "POS event + kịch bản",
            "Tất cả (kể cả monitor/health)",
            "Chỉ monitor/health",
        });
        _logFilter.SelectedIndex = 0;
        _logFilter.Width = 240;
        _logFilter.Margin = new Padding(3, 5, 12, 3);
        top.Controls.Add(_logFilter);
        var clear = new Button { Text = "Xóa log", AutoSize = true };
        clear.Click += (_, _) => _requestLog.Clear();
        top.Controls.Add(clear);
        top.Controls.Add(new Label
        {
            Text = "Không bao giờ hiển thị bearer token; chỉ role/subject. Giữ 200 dòng mới nhất.",
            AutoSize = true,
            Margin = new Padding(12, 8, 3, 3),
            ForeColor = Color.FromArgb(90, 90, 90),
        });
        layout.Controls.Add(top, 0, 0);

        ConfigureGrid(_logGrid);
        AddColumn(_logGrid, nameof(RequestLogEntry.TimeText), "Giờ", 65);
        AddColumn(_logGrid, nameof(RequestLogEntry.Method), "Method", 55);
        AddColumn(_logGrid, nameof(RequestLogEntry.Url), "URL", 300);
        AddColumn(_logGrid, nameof(RequestLogEntry.StatusText), "Status", 65);
        AddColumn(_logGrid, nameof(RequestLogEntry.ElapsedText), "Thời gian", 70);
        AddColumn(_logGrid, nameof(RequestLogEntry.CertificateText), "Cert", 95);
        AddColumn(_logGrid, nameof(RequestLogEntry.IdentityText), "Role / subject", 130);
        _logGrid.DataSource = _logView;
        layout.Controls.Add(_logGrid, 0, 1);

        _logDetails.Multiline = true;
        _logDetails.ReadOnly = true;
        _logDetails.ScrollBars = ScrollBars.Both;
        _logDetails.WordWrap = false;
        _logDetails.Font = new Font("Consolas", 9F);
        _logDetails.Dock = DockStyle.Fill;
        _logDetails.BackColor = Color.FromArgb(250, 250, 250);
        layout.Controls.Add(_logDetails, 0, 2);
        page.Controls.Add(layout);
        return page;
    }

    private void WireEvents()
    {
        _terminalCombo.SelectedIndexChanged += (_, _) => OnTerminalChanged();
        _searchBox.TextChanged += (_, _) => RefreshProducts();
        _addButton.Click += (_, _) => AddSelectedProduct();
        _productGrid.CellDoubleClick += (_, _) => AddSelectedProduct();
        _clearButton.Click += (_, _) => ClearCart();
        _payButton.Click += async (_, _) => await PayCoreAsync();
        _cartGrid.CellEndEdit += (_, _) => OnCartEdited();
        _cartGrid.DataError += (_, _) => { };
        _resultPanel.RetryRequested += async (_, _) => await RetryAsync();
        _historyGrid.SelectionChanged += (_, _) => UpdateHistoryButtons();
        _returnButton.Click += async (_, _) => await ReturnAsync();
        _cancelButton.Click += async (_, _) => await CancelAsync();
        _sendAgainButton.Click += async (_, _) => await SendAgainAsync();
        _scenarioPanel.ScenarioRequested += async (_, kind) => await RunScenarioAsync(kind);
        _scenarioPanel.MockToggleRequested += async (_, _) => await ToggleMockAsync();
        _refreshMonitor.Click += async (_, _) => await RefreshMonitorAsync();
        _logFilter.SelectedIndexChanged += (_, _) => RefreshLogView();
        _logGrid.SelectionChanged += (_, _) => ShowLogDetails();
        _requestLog.Changed += (_, _) => OnRequestLogChanged();
        _monitorTimer.Tick += async (_, _) => await RefreshMonitorAsync();
        _statusTimer.Tick += async (_, _) => await RefreshStatusAsync();
    }

    private void LoadCertificates()
    {
        foreach (var terminal in _config.Terminals)
        {
            var info = ClientCertificateLoader.Load(terminal, _loaded.Paths);
            _certificates[terminal.PosId] = info;
        }
    }

    private void PopulateTerminals()
    {
        foreach (var terminal in _config.Terminals)
        {
            _terminalCombo.Items.Add(terminal);
            var info = _certificates[terminal.PosId];
            var row = new TerminalRow
            {
                StoreName = terminal.StoreName,
                PosId = terminal.PosId,
                CertificateText = info.CertificateExists ? (info.IsUsable ? "OK" : "Lỗi") : "Thiếu",
                KeyText = info.KeyExists ? "OK" : "Thiếu",
                Fingerprint = info.FingerprintPrefix,
            };
            _terminalRows[terminal.PosId] = row;
            _terminalsView.Add(row);
            _historyByPos[terminal.PosId] = new List<TxnRecord>();
        }

        if (_terminalCombo.Items.Count > 0)
        {
            _terminalCombo.SelectedIndex = 0;
        }

        UpdateTerminalHighlight();
    }

    private void ApplyMode()
    {
        Text = _mockMode ? "RetailSync Demo POS — MOCK" : "RetailSync Demo POS";
        _modeLabel.Text = _mockMode ? "● MOCK" : "● LIVE";
        _modeLabel.ForeColor = _mockMode ? Color.FromArgb(199, 119, 0) : Color.FromArgb(30, 122, 52);
        _modeStatus.Text = _mockMode ? "MOCK" : "LIVE";
        _modeStatus.ForeColor = _modeLabel.ForeColor;
        _resultPanel.SetMock(_mockMode);
        _scenarioPanel.SetMockMode(_mockMode);
        _terminalInfo.Text = CurrentTerminal is { } terminal
            ? $"{terminal.StoreId} · {terminal.StoreName} · {terminal.PosId}"
            : string.Empty;
    }

    private TerminalConfig? CurrentTerminal => _terminalCombo.SelectedItem as TerminalConfig;

    private void OnTerminalChanged()
    {
        if (CurrentTerminal is not { } terminal)
        {
            return;
        }

        _cart.Clear();
        UpdateCartTotal();
        _resultPanel.Clear();
        _pendingRetry = null;
        _historyView.Clear();
        foreach (var record in _historyByPos[terminal.PosId])
        {
            _historyView.Add(record);
        }

        UpdateTerminalHighlight();
        UpdateHistoryButtons();
        ApplyMode();
        _ = RefreshMonitorAsync();
    }

    private void UpdateTerminalHighlight()
    {
        var selected = CurrentTerminal?.PosId;
        foreach (DataGridViewRow row in _terminalsGrid.Rows)
        {
            if (row.DataBoundItem is not TerminalRow terminal)
            {
                continue;
            }

            var isSelected = string.Equals(terminal.PosId, selected, StringComparison.OrdinalIgnoreCase);
            row.DefaultCellStyle.BackColor = isSelected
                ? Color.FromArgb(220, 237, 255)
                : Color.White;
            row.DefaultCellStyle.Font = isSelected
                ? new Font(_terminalsGrid.Font, FontStyle.Bold)
                : _terminalsGrid.Font;
        }

        _terminalsGrid.Refresh();
    }

    private void RefreshProducts()
    {
        var keyword = _searchBox.Text.Trim();
        var rows = keyword.Length == 0
            ? _allProducts
            : _allProducts.Where(product =>
                product.SearchText.Contains(keyword, StringComparison.OrdinalIgnoreCase)).ToList();
        _productView.Clear();
        foreach (var product in rows)
        {
            _productView.Add(product);
        }
    }

    private void AddSelectedProduct()
    {
        if (_productGrid.CurrentRow?.DataBoundItem is not ProductRow product)
        {
            _resultPanel.ShowInfo("Chọn một sản phẩm trong danh sách trước.");
            return;
        }

        AddToCart(product, 1);
    }

    private void AddToCart(ProductRow product, int quantity)
    {
        var existing = _cart.FirstOrDefault(item =>
            string.Equals(item.Sku, product.Sku, StringComparison.OrdinalIgnoreCase));
        if (existing is not null)
        {
            existing.Quantity += quantity;
            _cart.ResetBindings();
        }
        else
        {
            _cart.Add(new CartItem
            {
                Sku = product.Sku,
                Name = product.Name,
                UnitPrice = product.UnitPrice,
                Quantity = quantity,
            });
        }

        UpdateCartTotal();
        _resultPanel.Clear();
    }

    private void OnCartEdited()
    {
        foreach (var item in _cart)
        {
            if (item.Quantity <= 0)
            {
                item.Quantity = 1;
            }
        }

        _cart.ResetBindings();
        UpdateCartTotal();
    }

    private void ClearCart()
    {
        _cart.Clear();
        UpdateCartTotal();
        _resultPanel.Clear();
        _pendingRetry = null;
    }

    private void UpdateCartTotal()
    {
        var total = _cart.Sum(item => item.LineTotal);
        _cartTotal.Text = $"Tổng: {total:N0} đ · {_cart.Sum(item => item.Quantity)} món";
    }

    private async Task<PosResult> PayCoreAsync()
    {
        if (_busy)
        {
            return default!;
        }

        if (CurrentTerminal is not { } terminal)
        {
            return default!;
        }

        if (_cart.Count == 0)
        {
            _resultPanel.ShowInfo("Giỏ hàng đang trống.");
            return default!;
        }

        _busy = true;
        SetBusy(true);
        try
        {
            var eventItems = _cart.Select(item => new PosEventItem
            {
                Sku = item.Sku,
                Quantity = item.Quantity,
                UnitPrice = item.UnitPrice,
            }).ToList();
            var posEvent = PosEvents.Sale(terminal.StoreId, terminal.PosId, eventItems);
            var raw = PosEventJson.Serialize(posEvent);
            return await SendCoreAsync(terminal, posEvent, raw, addHistory: true,
                clearCartOnSuccess: true);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
            return default!;
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task<PosResult> SendCoreAsync(TerminalConfig terminal, PosEvent posEvent,
                                                string rawBody, bool addHistory,
                                                TerminalClient? clientOverride = null,
                                                bool clearCartOnSuccess = false)
    {
        PosResult result;
        if (_mockMode)
        {
            result = await _mockBackend.SendAsync(rawBody);
        }
        else
        {
            var client = clientOverride ?? GetLiveClient(terminal);
            result = await client.SendAsync(rawBody);
        }

        _resultPanel.ShowResult(result);
        UpdateTerminalResult(terminal, result);
        _pendingRetry = result.CanRetry
            ? new PendingRequest(terminal, rawBody, clearCartOnSuccess)
            : null;

        // Keep Pay and Retry consistent: a successful SALE empties the cart
        // exactly once, whether it succeeded on the first send or on Retry.
        if (clearCartOnSuccess && posEvent.EventType == EventTypes.Sale && result.IsSuccess)
        {
            _cart.Clear();
            UpdateCartTotal();
        }

        if (addHistory)
        {
            var record = new TxnRecord
            {
                Time = DateTime.Now,
                EventType = posEvent.EventType,
                TransactionId = posEvent.TransactionId,
                StoreId = posEvent.StoreId,
                PosId = posEvent.PosId,
                OriginalTransactionId = posEvent.OriginalTransactionId,
                ItemsText = ItemsText(posEvent),
                Outcome = result.Outcome.ToString(),
                Code = result.Code,
                RawBody = rawBody,
                Items = posEvent.Items?.ToList() ?? new List<PosEventItem>(),
            };
            AddHistory(record);
        }

        await RefreshMonitorAsync();
        return result;
    }

    private TerminalClient GetLiveClient(TerminalConfig terminal)
    {
        if (_liveClients.TryGetValue(terminal.PosId, out var existing))
        {
            return existing;
        }

        var info = _certificates[terminal.PosId];
        if (!info.IsUsable)
        {
            throw new ConfigurationException(
                $"Terminal {terminal.PosId} cannot send: {info.Error ?? "certificate missing"}.\n" +
                $"Run:\n  {SetupCommands.GenerateCertificates}\n" +
                $"Then:\n  {SetupCommands.RegisterFingerprints}");
        }

        var token = _loaded.TokenForTerminal(terminal)
                    ?? throw new ConfigurationException(
                        $"Missing token '{terminal.PosId}'.\nRun:\n  {SetupCommands.IssueTokens}");
        var client = new TerminalClient(_config.PosBaseUrl, _authority!, info.Certificate,
            terminal.PosId, token, _requestLog);
        _liveClients[terminal.PosId] = client;
        return client;
    }

    private void AddHistory(TxnRecord record)
    {
        _historyByPos[record.PosId].Insert(0, record);
        if (CurrentTerminal is { } terminal
            && string.Equals(terminal.PosId, record.PosId, StringComparison.OrdinalIgnoreCase))
        {
            _historyView.Insert(0, record);
            if (_historyGrid.Rows.Count > 0)
            {
                _historyGrid.ClearSelection();
                _historyGrid.Rows[0].Selected = true;
                _historyGrid.CurrentCell = _historyGrid.Rows[0].Cells[0];
            }
        }

        UpdateHistoryButtons();
    }

    private static string ItemsText(PosEvent posEvent)
    {
        if (posEvent.Items is null || posEvent.Items.Count == 0)
        {
            return posEvent.EventType == EventTypes.Cancellation
                ? $"hủy {posEvent.OriginalTransactionId}"
                : "—";
        }

        return string.Join(", ", posEvent.Items.Select(item => $"{item.Sku}×{item.Quantity}"));
    }

    private void UpdateTerminalResult(TerminalConfig terminal, PosResult result)
    {
        if (!_terminalRows.TryGetValue(terminal.PosId, out var row))
        {
            return;
        }

        row.LastResult = $"{result.Outcome} {result.Code}";
        row.LastTime = DateTime.Now.ToString("HH:mm:ss");
        _terminalsView.ResetBindings();
        UpdateTerminalHighlight();
    }

    private TxnRecord? SelectedHistory =>
        _historyGrid.CurrentRow?.DataBoundItem as TxnRecord;

    private void UpdateHistoryButtons()
    {
        var record = SelectedHistory;
        _returnButton.Enabled = record?.CanReturnOrCancel == true;
        _cancelButton.Enabled = record?.CanReturnOrCancel == true;
        _sendAgainButton.Enabled = record is not null;
    }

    private async Task SendAgainAsync()
    {
        if (_busy || SelectedHistory is not { } record)
        {
            return;
        }

        var terminal = _config.Terminals.FirstOrDefault(item =>
            string.Equals(item.PosId, record.PosId, StringComparison.OrdinalIgnoreCase));
        if (terminal is null)
        {
            _resultPanel.ShowInfo($"Terminal {record.PosId} không còn trong cấu hình.");
            return;
        }

        _busy = true;
        SetBusy(true);
        try
        {
            var posEvent = PosEventJson.Deserialize(record.RawBody);
            await SendCoreAsync(terminal, posEvent, record.RawBody, addHistory: true);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task ReturnAsync()
    {
        if (_busy || SelectedHistory is not { } record || !record.CanReturnOrCancel)
        {
            return;
        }

        using var dialog = new ReturnDialog(record, _config.Products.ToDictionary(
            product => product.Sku, product => product.Name, StringComparer.OrdinalIgnoreCase));
        if (dialog.ShowDialog(this) != DialogResult.OK)
        {
            return;
        }

        var soldItem = record.Items.FirstOrDefault(item =>
            string.Equals(item.Sku, dialog.SelectedSku, StringComparison.OrdinalIgnoreCase));
        if (soldItem is null)
        {
            _resultPanel.ShowInfo($"SKU {dialog.SelectedSku} không có trong đơn gốc.");
            return;
        }

        var terminal = _config.Terminals.FirstOrDefault(item =>
            string.Equals(item.PosId, record.PosId, StringComparison.OrdinalIgnoreCase));
        if (terminal is null)
        {
            _resultPanel.ShowInfo($"Terminal {record.PosId} không còn trong cấu hình.");
            return;
        }

        var posEvent = PosEvents.Return(record.StoreId, record.PosId, record.TransactionId,
            new[]
            {
                new PosEventItem
                {
                    Sku = dialog.SelectedSku,
                    Quantity = dialog.Quantity,
                    UnitPrice = soldItem.UnitPrice,
                },
            });
        var raw = PosEventJson.Serialize(posEvent);

        _busy = true;
        SetBusy(true);
        try
        {
            await SendCoreAsync(terminal, posEvent, raw, addHistory: true);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task CancelAsync()
    {
        if (_busy || SelectedHistory is not { } record || !record.CanReturnOrCancel)
        {
            return;
        }

        if (MessageBox.Show(this,
                $"Hủy toàn bộ đơn {record.TransactionId}?\nTồn kho sẽ được hoàn lại.",
                "Xác nhận CANCELLATION", MessageBoxButtons.YesNo, MessageBoxIcon.Question)
            != DialogResult.Yes)
        {
            return;
        }

        var terminal = _config.Terminals.FirstOrDefault(item =>
            string.Equals(item.PosId, record.PosId, StringComparison.OrdinalIgnoreCase));
        if (terminal is null)
        {
            _resultPanel.ShowInfo($"Terminal {record.PosId} không còn trong cấu hình.");
            return;
        }

        var posEvent = PosEvents.Cancellation(record.StoreId, record.PosId, record.TransactionId);
        var raw = PosEventJson.Serialize(posEvent);

        _busy = true;
        SetBusy(true);
        try
        {
            await SendCoreAsync(terminal, posEvent, raw, addHistory: true);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task RetryAsync()
    {
        if (_busy || _pendingRetry is not { } pending)
        {
            _resultPanel.ShowInfo("Không có request nào để Retry.");
            return;
        }

        _busy = true;
        SetBusy(true);
        try
        {
            var posEvent = PosEventJson.Deserialize(pending.RawBody);
            await SendCoreAsync(pending.Terminal, posEvent, pending.RawBody, addHistory: true,
                clearCartOnSuccess: pending.ClearCartOnSuccess);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task RunScenarioAsync(ScenarioKind kind)
    {
        if (_busy || CurrentTerminal is not { } terminal)
        {
            return;
        }

        _busy = true;
        SetBusy(true);
        try
        {
            await RunScenarioCoreAsync(kind, terminal);
        }
        catch (Exception error)
        {
            _resultPanel.ShowInfo(error.Message);
        }
        finally
        {
            _busy = false;
            SetBusy(false);
        }
    }

    private async Task RunScenarioCoreAsync(ScenarioKind kind, TerminalConfig terminal)
    {
        var product = _config.Products[0];
        var lastSale = _historyByPos[terminal.PosId]
            .FirstOrDefault(record => record.IsSale && record.Outcome == nameof(PosOutcome.OK));

        switch (kind)
        {
            case ScenarioKind.Conflict:
                if (lastSale is null || lastSale.Items.Count == 0)
                {
                    _resultPanel.ShowInfo("Cần một SALE đã OK trước khi chạy Conflict.");
                    return;
                }

                var conflictEvent = PosEvents.Sale(lastSale.StoreId, lastSale.PosId,
                    new[]
                    {
                        new PosEventItem
                        {
                            Sku = lastSale.Items[0].Sku,
                            Quantity = lastSale.Items[0].Quantity + 1,
                            UnitPrice = lastSale.Items[0].UnitPrice,
                        },
                    },
                    lastSale.TransactionId);
                await SendCoreAsync(terminal, conflictEvent, PosEventJson.Serialize(conflictEvent),
                    addHistory: false);
                return;

            case ScenarioKind.InsufficientStock:
                var big = PosEvents.Sale(terminal.StoreId, terminal.PosId, new[]
                {
                    new PosEventItem { Sku = product.Sku, Quantity = 999, UnitPrice = product.UnitPrice },
                });
                await SendCoreAsync(terminal, big, PosEventJson.Serialize(big), addHistory: false);
                return;

            case ScenarioKind.UnregisteredStore:
                var unknown = PosEvents.Sale("STORE-XX", terminal.PosId, new[]
                {
                    new PosEventItem { Sku = product.Sku, Quantity = 1, UnitPrice = product.UnitPrice },
                });
                await SendCoreAsync(terminal, unknown, PosEventJson.Serialize(unknown),
                    addHistory: false);
                return;

            case ScenarioKind.ReturnLimit:
                if (lastSale is null || lastSale.Items.Count == 0)
                {
                    _resultPanel.ShowInfo("Cần một SALE đã OK trước khi chạy Return limit.");
                    return;
                }

                var sold = lastSale.Items[0];
                var overReturn = PosEvents.Return(lastSale.StoreId, lastSale.PosId,
                    lastSale.TransactionId,
                    new[]
                    {
                        new PosEventItem
                        {
                            Sku = sold.Sku,
                            Quantity = sold.Quantity + 1,
                            UnitPrice = sold.UnitPrice,
                        },
                    });
                await SendCoreAsync(terminal, overReturn, PosEventJson.Serialize(overReturn),
                    addHistory: false);
                return;
        }

        if (_mockMode)
        {
            _resultPanel.ShowInfo("Kịch bản chứng chỉ/gateway chỉ chạy ở chế độ LIVE.");
            return;
        }

        _authority ??= ServerCertificateValidator.LoadAuthority(_loaded.Paths.CaCertificate);
        var token = _loaded.TokenForTerminal(terminal)
                    ?? throw new ConfigurationException(
                        $"Missing token '{terminal.PosId}'.\nRun:\n  {SetupCommands.IssueTokens}");

        switch (kind)
        {
            case ScenarioKind.WrongCertificate:
                var other = _config.Terminals.FirstOrDefault(item =>
                    !string.Equals(item.PosId, terminal.PosId, StringComparison.OrdinalIgnoreCase)
                    && _certificates[item.PosId].IsUsable);
                if (other is null)
                {
                    _resultPanel.ShowInfo("Không có certificate của terminal khác để chạy kịch bản này.");
                    return;
                }

                var wrongCert = _certificates[other.PosId];
                var wrongEvent = PosEvents.Sale(terminal.StoreId, terminal.PosId, new[]
                {
                    new PosEventItem { Sku = product.Sku, Quantity = 1, UnitPrice = product.UnitPrice },
                });
                using (var wrongClient = new TerminalClient(_config.PosBaseUrl, _authority,
                           wrongCert.Certificate, other.PosId, token, _requestLog))
                {
                    await SendCoreAsync(terminal, wrongEvent, PosEventJson.Serialize(wrongEvent),
                        addHistory: false, wrongClient);
                }

                return;

            case ScenarioKind.NoCertificate:
                var noCertEvent = PosEvents.Sale(terminal.StoreId, terminal.PosId, new[]
                {
                    new PosEventItem { Sku = product.Sku, Quantity = 1, UnitPrice = product.UnitPrice },
                });
                using (var noCertClient = new TerminalClient(_config.PosBaseUrl, _authority,
                           null, null, token, _requestLog))
                {
                    await SendCoreAsync(terminal, noCertEvent, PosEventJson.Serialize(noCertEvent),
                        addHistory: false, noCertClient);
                }

                return;

            case ScenarioKind.SkipGateway:
                var skipEvent = PosEvents.Sale(terminal.StoreId, terminal.PosId, new[]
                {
                    new PosEventItem { Sku = product.Sku, Quantity = 1, UnitPrice = product.UnitPrice },
                });
                using (var skipClient = new TerminalClient(_config.MonitorBaseUrl, _authority,
                           null, null, token, _requestLog))
                {
                    await SendCoreAsync(terminal, skipEvent, PosEventJson.Serialize(skipEvent),
                        addHistory: false, skipClient);
                }

                return;
        }
    }

    private async Task RefreshMonitorAsync()
    {
        if (_monitorBusy || _closing || CurrentTerminal is not { } terminal)
        {
            return;
        }

        _monitorBusy = true;
        try
        {
            if (_mockMode)
            {
                ReplaceStock(_mockBackend.GetStock(terminal.StoreId));
                ReplaceAudit(_mockBackend.GetAudit());
                _stockStatus.Text = "MOCK · dữ liệu trong bộ nhớ";
                _auditStatus.Text = "MOCK · không có audit thật";
                return;
            }

            if (_monitorClient is null)
            {
                _stockStatus.Text = "Chưa có monitor client.";
                return;
            }

            var staffToken = _loaded.StaffTokenForStore(terminal.StoreId);
            var auditorToken = _loaded.AuditorToken;
            if (staffToken is null || auditorToken is null)
            {
                _stockStatus.Text = "Thiếu token staff/auditor.";
                _auditStatus.Text = "Thiếu token auditor.";
                return;
            }

            var stockTask = _monitorClient.GetStockAsync(terminal.StoreId, staffToken);
            var auditTask = _monitorClient.GetAuditAsync(auditorToken);
            await Task.WhenAll(stockTask, auditTask);
            var stock = await stockTask;
            var audit = await auditTask;

            if (stock.IsSuccess && stock.Data is { } inventory)
            {
                ReplaceStock(inventory.Items.Select(line => new StockRow
                {
                    Sku = line.Sku,
                    Name = _productConfigs.TryGetValue(line.Sku, out var value) ? value.Name : line.Sku,
                    Quantity = line.Quantity,
                }).ToList());
                _stockStatus.Text = $"{terminal.StoreId} · {stock.ElapsedMs:0} ms · cập nhật {DateTime.Now:HH:mm:ss}";
            }
            else
            {
                _stockStatus.Text = stock.Error ?? "Không đọc được tồn kho.";
            }

            if (audit.IsSuccess && audit.Data is { } entries)
            {
                ReplaceAudit(entries.Items.Select(entry => AuditRow.From(entry)).ToList());
                _auditStatus.Text = $"{audit.Data.Items.Count} dòng · {audit.ElapsedMs:0} ms · cập nhật {DateTime.Now:HH:mm:ss}";
            }
            else
            {
                _auditStatus.Text = audit.Error ?? "Không đọc được audit log.";
            }
        }
        catch (Exception error)
        {
            _stockStatus.Text = error.Message;
            _auditStatus.Text = error.Message;
        }
        finally
        {
            _monitorBusy = false;
        }
    }

    private void ReplaceStock(IEnumerable<StockRow> rows)
    {
        _stockView.Clear();
        foreach (var row in rows)
        {
            _stockView.Add(row);
        }
    }

    private void ReplaceAudit(IEnumerable<AuditRow> rows)
    {
        _auditView.Clear();
        foreach (var row in rows)
        {
            _auditView.Add(row);
        }
    }

    private async Task RefreshStatusAsync()
    {
        if (_statusBusy || _closing)
        {
            return;
        }

        _statusBusy = true;
        try
        {
            _clockStatus.Text = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
            _filesStatus.Text = $"CA: {(File.Exists(_loaded.Paths.CaCertificate) ? "OK" : "thiếu")} · " +
                                $"tokens: {(File.Exists(_loaded.Paths.TokensFile) ? $"{_loaded.Tokens.Count} khóa" : "thiếu")}";
            _modeStatus.Text = _mockMode ? "MOCK" : "LIVE";
            _modeStatus.ForeColor = _mockMode ? Color.FromArgb(199, 119, 0) : Color.FromArgb(30, 122, 52);

            if (_mockMode)
            {
                _middlewareStatus.Text = "Middleware: MOCK";
                _gatewayStatus.Text = "Gateway: MOCK";
                _middlewareStatus.ForeColor = Color.FromArgb(199, 119, 0);
                _gatewayStatus.ForeColor = Color.FromArgb(199, 119, 0);
                return;
            }

            if (_monitorClient is null)
            {
                _middlewareStatus.Text = "Middleware: —";
                _gatewayStatus.Text = "Gateway: —";
                return;
            }

            var health = await _monitorClient.GetHealthAsync();
            if (health.IsSuccess && string.Equals(health.Data?.Status, "ok", StringComparison.OrdinalIgnoreCase))
            {
                _middlewareStatus.Text = $"Middleware: OK ({health.ElapsedMs:0} ms)";
                _middlewareStatus.ForeColor = Color.FromArgb(30, 122, 52);
            }
            else
            {
                _middlewareStatus.Text = $"Middleware: DOWN ({health.Error ?? "no answer"})";
                _middlewareStatus.ForeColor = Color.FromArgb(179, 38, 30);
            }

            var root = new Uri(_config.PosBaseUrl).GetLeftPart(UriPartial.Authority);
            _gatewayProbe ??= new GatewayProbe(_authority!);
            var gateway = await _gatewayProbe.CheckAsync(root, _requestLog);
            if (gateway.Up)
            {
                _gatewayStatus.Text = $"Gateway: UP (400, {gateway.ElapsedMs:0} ms)";
                _gatewayStatus.ForeColor = Color.FromArgb(30, 122, 52);
            }
            else
            {
                _gatewayStatus.Text = $"Gateway: DOWN ({gateway.Status}, {gateway.Error ?? "no answer"})";
                _gatewayStatus.ForeColor = Color.FromArgb(179, 38, 30);
            }
        }
        catch (Exception error)
        {
            _middlewareStatus.Text = $"Middleware: error — {error.Message}";
            _middlewareStatus.ForeColor = Color.FromArgb(179, 38, 30);
        }
        finally
        {
            _statusBusy = false;
        }
    }

    private void OnRequestLogChanged()
    {
        if (_closing)
        {
            return;
        }

        if (InvokeRequired)
        {
            try
            {
                BeginInvoke(new Action(RefreshLogView));
            }
            catch (InvalidOperationException)
            {
                // The form is closing.
            }

            return;
        }

        RefreshLogView();
    }

    private void RefreshLogView()
    {
        var filter = _logFilter.SelectedIndex;
        var entries = _requestLog.Snapshot().Where(entry => filter switch
        {
            0 => entry.Kind is RequestKind.Pos or RequestKind.Mock,
            2 => entry.Kind is RequestKind.Monitor or RequestKind.Probe,
            _ => true,
        });
        _logView.Clear();
        foreach (var entry in entries)
        {
            _logView.Add(entry);
        }

        if (_logView.Count > 0 && _logGrid.CurrentRow is null)
        {
            _logGrid.Rows[0].Selected = true;
            ShowLogDetails();
        }
    }

    private void ShowLogDetails()
    {
        _logDetails.Text = _logGrid.CurrentRow?.DataBoundItem is RequestLogEntry entry
            ? entry.DetailsText
            : string.Empty;
    }

    private void OnFormKeyDown(object? sender, KeyEventArgs e)
    {
        switch (e.KeyCode)
        {
            case Keys.F12:
                ToggleScenarios();
                e.Handled = true;
                break;
            case Keys.F9:
                _ = PayCoreAsync();
                e.Handled = true;
                break;
            case Keys.Escape:
                _resultPanel.Clear();
                e.Handled = true;
                break;
            case Keys.F2:
                _searchBox.Focus();
                _searchBox.SelectAll();
                e.Handled = true;
                break;
        }
    }

    private void ToggleScenarios()
    {
        var visible = !_scenarioPanel.Visible;
        _scenarioPanel.Visible = visible;
        if (_scenarioRowStyle is not null)
        {
            _scenarioRowStyle.Height = visible ? 125 : 0;
        }

        _scenarioPanel.SetMockMode(_mockMode);
    }

    private void SetBusy(bool busy)
    {
        UseWaitCursor = busy;
        _payButton.Enabled = !busy;
        _returnButton.Enabled = !busy && SelectedHistory?.CanReturnOrCancel == true;
        _cancelButton.Enabled = !busy && SelectedHistory?.CanReturnOrCancel == true;
        _sendAgainButton.Enabled = !busy && SelectedHistory is not null;
        _addButton.Enabled = !busy;
    }

    private bool CanUseLive(out string reason)
    {
        var problems = new List<string>();
        if (!File.Exists(_loaded.Paths.CaCertificate))
        {
            problems.Add($"Thiếu CA: {_loaded.Paths.CaCertificate}\nChạy:\n  {SetupCommands.GenerateCertificates}");
        }

        foreach (var terminal in _config.Terminals)
        {
            if (!_certificates[terminal.PosId].IsUsable)
            {
                problems.Add($"Terminal {terminal.PosId} thiếu certificate/key.\nChạy:\n  {SetupCommands.GenerateCertificates}");
            }

            if (_loaded.TokenForTerminal(terminal) is null)
            {
                problems.Add($"Thiếu token {terminal.PosId}.\nChạy:\n  {SetupCommands.IssueTokens}");
            }

            if (_loaded.StaffTokenForStore(terminal.StoreId) is null)
            {
                problems.Add($"Thiếu token staff cho {terminal.StoreId}.\nChạy:\n  {SetupCommands.IssueTokens}");
            }
        }

        if (_loaded.AuditorToken is null)
        {
            problems.Add($"Thiếu token auditor.\nChạy:\n  {SetupCommands.IssueTokens}");
        }

        reason = problems.Count == 0
            ? string.Empty
            : string.Join("\n\n", problems.Distinct());
        return problems.Count == 0;
    }

    private static void ConfigureGrid(DataGridView grid)
    {
        grid.Dock = DockStyle.Fill;
        grid.AutoGenerateColumns = false;
        grid.AllowUserToAddRows = false;
        grid.AllowUserToDeleteRows = false;
        grid.AllowUserToResizeRows = false;
        grid.RowHeadersVisible = false;
        grid.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
        grid.MultiSelect = false;
        grid.ReadOnly = true;
        grid.BackgroundColor = Color.White;
        grid.BorderStyle = BorderStyle.FixedSingle;
        grid.ColumnHeadersHeight = 28;
        grid.RowTemplate.Height = 25;
        grid.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill;
        grid.EnableHeadersVisualStyles = false;
        grid.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(235, 238, 242);
        grid.ColumnHeadersDefaultCellStyle.Font = new Font("Segoe UI", 9F, FontStyle.Bold);
        grid.AlternatingRowsDefaultCellStyle.BackColor = Color.FromArgb(250, 251, 252);
        grid.DefaultCellStyle.Font = new Font("Segoe UI", 9F);
    }

    private static void AddColumn(DataGridView grid, string property, string header,
                                  int fillWeight, bool readOnly = true)
    {
        grid.Columns.Add(new DataGridViewTextBoxColumn
        {
            DataPropertyName = property,
            HeaderText = header,
            FillWeight = fillWeight,
            ReadOnly = readOnly,
            SortMode = DataGridViewColumnSortMode.NotSortable,
        });
    }

    private void OnFormClosing(object? sender, FormClosingEventArgs e)
    {
        _closing = true;
        _monitorTimer.Stop();
        _statusTimer.Stop();
        foreach (var client in _liveClients.Values)
        {
            client.Dispose();
        }

        _liveClients.Clear();
        _monitorClient?.Dispose();
        _gatewayProbe?.Dispose();
        _authority?.Dispose();
        foreach (var certificate in _certificates.Values)
        {
            certificate.Dispose();
        }

        _certificates.Clear();
    }
}
