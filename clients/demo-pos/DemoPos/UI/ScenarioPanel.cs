namespace DemoPos.UI;

public enum ScenarioKind
{
    Conflict,
    InsufficientStock,
    UnregisteredStore,
    ReturnLimit,
    WrongCertificate,
    NoCertificate,
    SkipGateway,
}

/// <summary>The Scenarios menu, hidden until F12, with one button per expected answer.</summary>
public sealed class ScenarioPanel : UserControl
{
    private readonly Button _mockButton;

    public ScenarioPanel()
    {
        var group = new GroupBox
        {
            Text = "Kịch bản (F12) — mỗi nút gửi một request thật và hiện mã mong đợi",
            Dock = DockStyle.Fill,
            Padding = new Padding(8),
            Font = new Font("Segoe UI", 9F),
        };

        var flow = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            WrapContents = true,
            Padding = new Padding(2),
        };

        Add(flow, ScenarioKind.Conflict, "Conflict → 409 CONFLICT");
        Add(flow, ScenarioKind.InsufficientStock, "Bán 999 → 409 INSUFFICIENT_STOCK");
        Add(flow, ScenarioKind.UnregisteredStore, "Store lạ → 422 UNREGISTERED");
        Add(flow, ScenarioKind.ReturnLimit, "Trả quá số → 409 RETURN_QTY_EXCEEDED");
        Add(flow, ScenarioKind.WrongCertificate, "Sai chứng chỉ → 403");
        Add(flow, ScenarioKind.NoCertificate, "Không chứng chỉ → 400 gateway");
        Add(flow, ScenarioKind.SkipGateway, "Bỏ qua gateway → 403");

        _mockButton = new Button
        {
            Text = "Bật MOCK (dự phòng)",
            AutoSize = true,
            BackColor = Color.FromArgb(255, 244, 224),
            Margin = new Padding(12, 3, 3, 3),
        };
        _mockButton.Click += (_, _) => MockToggleRequested?.Invoke(this, EventArgs.Empty);
        flow.Controls.Add(_mockButton);

        group.Controls.Add(flow);
        Controls.Add(group);
        Height = 125;
    }

    public event EventHandler<ScenarioKind>? ScenarioRequested;

    public event EventHandler? MockToggleRequested;

    public void SetMockMode(bool mock)
    {
        _mockButton.Text = mock ? "Đang MOCK — tắt MOCK" : "Bật MOCK (dự phòng)";
        _mockButton.BackColor = mock
            ? Color.FromArgb(252, 235, 233)
            : Color.FromArgb(255, 244, 224);
    }

    private void Add(FlowLayoutPanel flow, ScenarioKind kind, string text)
    {
        var button = new Button
        {
            Text = text,
            AutoSize = true,
            Margin = new Padding(3),
        };
        button.Click += (_, _) => ScenarioRequested?.Invoke(this, kind);
        flow.Controls.Add(button);
    }
}
