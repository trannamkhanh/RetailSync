using DemoPos.Models;

namespace DemoPos.UI;

/// <summary>Outcome, code, message, stock and latency, with the colours the brief asks for.</summary>
public sealed class ResultPanel : UserControl
{
    private static readonly Color OkColor = Color.FromArgb(30, 122, 52);
    private static readonly Color DuplicateColor = Color.FromArgb(21, 101, 192);
    private static readonly Color RejectedColor = Color.FromArgb(179, 38, 30);
    private static readonly Color ErrorColor = Color.FromArgb(199, 119, 0);
    private static readonly Color NeutralColor = Color.FromArgb(90, 90, 90);

    private readonly Label _outcome = new();
    private readonly Label _code = new();
    private readonly Label _message = new();
    private readonly Label _stock = new();
    private readonly Label _time = new();
    private readonly Label _mock = new();
    private readonly Button _retry = new();

    public ResultPanel()
    {
        BorderStyle = BorderStyle.FixedSingle;
        BackColor = Color.White;
        Padding = new Padding(10, 8, 10, 8);
        MinimumSize = new Size(400, 115);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 1,
            BackColor = Color.White,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 78));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 22));

        var left = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            BackColor = Color.White,
        };
        left.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
        left.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        left.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        left.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));

        _outcome.Dock = DockStyle.Fill;
        _outcome.Font = new Font("Segoe UI", 15F, FontStyle.Bold);
        _outcome.Text = "—";
        _code.Dock = DockStyle.Fill;
        _code.Font = new Font("Consolas", 10F, FontStyle.Bold);
        _message.Dock = DockStyle.Fill;
        _message.Font = new Font("Segoe UI", 9.5F);
        _message.AutoEllipsis = true;
        _stock.Dock = DockStyle.Fill;
        _stock.Font = new Font("Consolas", 9F);

        left.Controls.Add(_outcome, 0, 0);
        left.Controls.Add(_code, 0, 1);
        left.Controls.Add(_message, 0, 2);
        left.Controls.Add(_stock, 0, 3);

        var right = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 3,
            BackColor = Color.White,
        };
        right.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));

        _mock.Dock = DockStyle.Fill;
        _mock.TextAlign = ContentAlignment.MiddleRight;
        _mock.Font = new Font("Segoe UI", 20F, FontStyle.Bold);
        _mock.ForeColor = Color.FromArgb(199, 119, 0);
        _mock.Text = string.Empty;
        _time.Dock = DockStyle.Fill;
        _time.TextAlign = ContentAlignment.MiddleRight;
        _time.Font = new Font("Consolas", 9F);
        _time.Text = string.Empty;

        _retry.Dock = DockStyle.Fill;
        _retry.Text = "Retry";
        _retry.Visible = false;
        _retry.Click += (_, _) => RetryRequested?.Invoke(this, EventArgs.Empty);

        right.Controls.Add(_mock, 0, 0);
        right.Controls.Add(_time, 0, 1);
        right.Controls.Add(_retry, 0, 2);

        layout.Controls.Add(left, 0, 0);
        layout.Controls.Add(right, 1, 0);
        Controls.Add(layout);
    }

    public event EventHandler? RetryRequested;

    public bool RetryVisible => _retry.Visible;

    public void ShowResult(PosResult result)
    {
        var (color, background) = result.Outcome switch
        {
            PosOutcome.OK => (OkColor, Color.FromArgb(232, 246, 234)),
            PosOutcome.DUPLICATE => (DuplicateColor, Color.FromArgb(232, 240, 253)),
            PosOutcome.REJECTED => (RejectedColor, Color.FromArgb(252, 235, 233)),
            _ => (ErrorColor, Color.FromArgb(255, 244, 224)),
        };

        _outcome.Text = result.Outcome == PosOutcome.OK ? "OK" : result.Outcome.ToString();
        _code.Text = result.Code;
        _message.Text = result.Message;
        _stock.Text = result.CurrentStock.Count == 0
            ? string.Empty
            : "current_stock: " + result.StockText;
        _time.Text = $"{result.ElapsedMs:0} ms · HTTP {result.HttpStatus}";
        _retry.Visible = result.CanRetry;
        ApplyColors(color, background);
    }

    public void ShowInfo(string message)
    {
        _outcome.Text = "INFO";
        _code.Text = string.Empty;
        _message.Text = message;
        _stock.Text = string.Empty;
        _time.Text = string.Empty;
        _retry.Visible = false;
        ApplyColors(NeutralColor, Color.FromArgb(245, 245, 245));
    }

    public void Clear()
    {
        _outcome.Text = "—";
        _code.Text = string.Empty;
        _message.Text = string.Empty;
        _stock.Text = string.Empty;
        _time.Text = string.Empty;
        _retry.Visible = false;
        ApplyColors(NeutralColor, Color.White);
    }

    public void SetMock(bool mock)
    {
        _mock.Text = mock ? "MOCK" : string.Empty;
    }

    private void ApplyColors(Color color, Color background)
    {
        _outcome.ForeColor = color;
        _code.ForeColor = color;
        _message.ForeColor = color;
        _stock.ForeColor = color;
        _time.ForeColor = color;
        BackColor = background;
        SetBackground(this, background);
    }

    private static void SetBackground(Control control, Color background)
    {
        foreach (Control child in control.Controls)
        {
            if (child is Button)
            {
                continue;
            }

            child.BackColor = background;
            SetBackground(child, background);
        }
    }
}
