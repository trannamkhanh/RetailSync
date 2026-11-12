using System.Reflection;

namespace DemoConsole.UI;

/// <summary>High-contrast colours and large fonts for a projector.</summary>
internal static class Theme
{
    public static readonly Color Background = Color.White;
    public static readonly Color Text = Color.Black;
    public static readonly Color Header = Color.FromArgb(0, 32, 96);
    public static readonly Color HeaderText = Color.White;
    public static readonly Color Selection = Color.FromArgb(0, 84, 166);
    public static readonly Color Changed = Color.FromArgb(255, 236, 0);
    public static readonly Color ChangedSelected = Color.FromArgb(230, 180, 0);
    public static readonly Color Expired = Color.FromArgb(200, 0, 0);
    public static readonly Color Near = Color.FromArgb(200, 90, 0);
    public static readonly Color Ok = Color.FromArgb(0, 120, 0);
    public static readonly Color Warn = Color.FromArgb(180, 90, 0);
    public static readonly Color Error = Color.FromArgb(200, 0, 0);
    public static readonly Color Muted = Color.FromArgb(70, 70, 70);

    public static Font Regular(float size) => new("Segoe UI", size, FontStyle.Regular);

    public static Font Bold(float size) => new("Segoe UI", size, FontStyle.Bold);

    public static DataGridView Grid(float fontSize, params (string Name, string Header, int Weight)[] columns)
    {
        var grid = new DataGridView
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            AllowUserToAddRows = false,
            AllowUserToDeleteRows = false,
            AllowUserToResizeRows = false,
            AllowUserToOrderColumns = false,
            MultiSelect = false,
            SelectionMode = DataGridViewSelectionMode.FullRowSelect,
            RowHeadersVisible = false,
            BackgroundColor = Background,
            BorderStyle = BorderStyle.FixedSingle,
            GridColor = Color.FromArgb(160, 160, 160),
            EnableHeadersVisualStyles = false,
            AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill,
            AutoSizeRowsMode = DataGridViewAutoSizeRowsMode.AllCells,
            ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.AutoSize,
            Font = Regular(fontSize),
        };
        grid.ColumnHeadersDefaultCellStyle.BackColor = Header;
        grid.ColumnHeadersDefaultCellStyle.ForeColor = HeaderText;
        grid.ColumnHeadersDefaultCellStyle.Font = Bold(fontSize);
        grid.ColumnHeadersDefaultCellStyle.SelectionBackColor = Header;
        grid.DefaultCellStyle.BackColor = Background;
        grid.DefaultCellStyle.ForeColor = Text;
        grid.DefaultCellStyle.SelectionBackColor = Selection;
        grid.DefaultCellStyle.SelectionForeColor = Color.White;
        grid.DefaultCellStyle.Padding = new Padding(2);
        foreach (var (name, header, weight) in columns)
        {
            var column = new DataGridViewTextBoxColumn
            {
                Name = name,
                HeaderText = header,
                FillWeight = weight,
                SortMode = DataGridViewColumnSortMode.NotSortable,
            };
            grid.Columns.Add(column);
        }

        GridFiller.TrackUserSelection(grid);

        // Double buffering stops the flicker of a refresh every few seconds.
        typeof(DataGridView).GetProperty("DoubleBuffered", BindingFlags.Instance | BindingFlags.NonPublic)
            ?.SetValue(grid, true);
        return grid;
    }

    public static Button ActionButton(string text, float fontSize)
    {
        var button = new Button
        {
            Text = text,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            Font = Bold(fontSize),
            Padding = new Padding(10, 4, 10, 4),
            Margin = new Padding(4),
            BackColor = Color.FromArgb(230, 236, 245),
            ForeColor = Text,
            FlatStyle = FlatStyle.Flat,
            UseVisualStyleBackColor = false,
        };
        button.FlatAppearance.BorderColor = Header;
        button.FlatAppearance.BorderSize = 2;
        return button;
    }

    public static Label Line(float fontSize, bool bold = false) => new()
    {
        AutoSize = true,
        Font = bold ? Bold(fontSize) : Regular(fontSize),
        ForeColor = Text,
        Margin = new Padding(4, 6, 4, 4),
    };
}
