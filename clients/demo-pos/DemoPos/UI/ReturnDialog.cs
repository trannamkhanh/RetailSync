using DemoPos.Models;

namespace DemoPos.UI;

/// <summary>Choose one sold SKU and a quantity to return.</summary>
public sealed class ReturnDialog : Form
{
    private readonly ComboBox _sku = new();
    private readonly NumericUpDown _quantity = new();
    private readonly List<PosEventItem> _items;

    public ReturnDialog(TxnRecord sale, IReadOnlyDictionary<string, string> productNames)
    {
        _items = sale.Items;
        Text = $"Trả hàng cho {sale.TransactionId}";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(460, 170);
        Font = new Font("Segoe UI", 9.5F);

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 2,
            RowCount = 3,
            Padding = new Padding(14),
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));

        _sku.DropDownStyle = ComboBoxStyle.DropDownList;
        _sku.Dock = DockStyle.Fill;
        foreach (var item in _items)
        {
            var name = productNames.TryGetValue(item.Sku, out var value) ? value : item.Sku;
            _sku.Items.Add(new SkuChoice(item.Sku, $"{item.Sku} — {name} (đã bán {item.Quantity})"));
        }

        if (_sku.Items.Count > 0)
        {
            _sku.SelectedIndex = 0;
        }

        _quantity.Minimum = 1;
        _quantity.Maximum = 1_000_000;
        _quantity.Value = 1;
        _quantity.Dock = DockStyle.Left;
        _quantity.Width = 120;

        layout.Controls.Add(new Label { Text = "SKU", TextAlign = ContentAlignment.MiddleLeft, Dock = DockStyle.Fill }, 0, 0);
        layout.Controls.Add(_sku, 1, 0);
        layout.Controls.Add(new Label { Text = "Số lượng trả", TextAlign = ContentAlignment.MiddleLeft, Dock = DockStyle.Fill }, 0, 1);
        layout.Controls.Add(_quantity, 1, 1);

        var buttons = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            Dock = DockStyle.Fill,
        };
        var ok = new Button { Text = "Gửi RETURN", DialogResult = DialogResult.OK, AutoSize = true };
        var cancel = new Button { Text = "Hủy", DialogResult = DialogResult.Cancel, AutoSize = true };
        ok.Click += (_, _) => ValidateSelection();
        buttons.Controls.Add(ok);
        buttons.Controls.Add(cancel);
        layout.Controls.Add(buttons, 0, 2);
        layout.SetColumnSpan(buttons, 2);

        Controls.Add(layout);
        AcceptButton = ok;
        CancelButton = cancel;
    }

    public string SelectedSku { get; private set; } = string.Empty;

    public int Quantity { get; private set; } = 1;

    private void ValidateSelection()
    {
        if (_sku.SelectedItem is not SkuChoice choice)
        {
            DialogResult = DialogResult.None;
            return;
        }

        SelectedSku = choice.Sku;
        Quantity = (int)_quantity.Value;
    }

    private sealed record SkuChoice(string Sku, string Text)
    {
        public override string ToString() => Text;
    }
}
