namespace DemoConsole.UI;

/// <summary>One grid row: its key (kept selected across refreshes), its cells and its colours.</summary>
internal sealed record GridRow(string Key, object?[] Cells, Color? Back = null, Color? Fore = null);

/// <summary>
/// Refills a grid every refresh without losing the row the presenter picked or the
/// scroll position. Only a row picked with the mouse or the keyboard stays selected;
/// the grid's own automatic first-row selection is cleared, so the change highlight
/// is never hidden behind the selection colour.
/// </summary>
internal static class GridFiller
{
    private const string NoSelection = "";

    /// <summary>Remembers the row the presenter picks; call once per grid.</summary>
    public static void TrackUserSelection(DataGridView grid)
    {
        grid.Tag = NoSelection;
        grid.CellMouseDown += (_, e) =>
        {
            if (e.RowIndex >= 0 && e.RowIndex < grid.Rows.Count)
            {
                Pick(grid, grid.Rows[e.RowIndex]);
            }
        };
        grid.KeyUp += (_, _) =>
        {
            if (grid.CurrentRow is { } row)
            {
                Pick(grid, row);
            }
        };
        // A hidden tab selects its first row when it is shown; undo that.
        grid.VisibleChanged += (_, _) =>
        {
            if (SelectedKey(grid) is null)
            {
                grid.ClearSelection();
            }
        };
    }

    private static void Pick(DataGridView grid, DataGridViewRow row)
    {
        grid.Tag = row.Tag as string ?? NoSelection;
        row.DefaultCellStyle.SelectionBackColor = Theme.Selection;
        row.DefaultCellStyle.SelectionForeColor = Color.White;
    }

    /// <summary>The key of the row the presenter picked, or null.</summary>
    public static string? SelectedKey(DataGridView grid) =>
        grid.Tag is string key && key.Length > 0 ? key : null;

    public static void Fill(DataGridView grid, IReadOnlyList<GridRow> rows)
    {
        var selectedKey = SelectedKey(grid);
        var firstRow = grid.FirstDisplayedScrollingRowIndex;

        grid.SuspendLayout();
        try
        {
            if (grid.Rows.Count != rows.Count)
            {
                grid.Rows.Clear();
                if (rows.Count > 0)
                {
                    grid.Rows.Add(rows.Count);
                }
            }

            for (var index = 0; index < rows.Count; index++)
            {
                var row = grid.Rows[index];
                var data = rows[index];
                row.Tag = data.Key;
                for (var cell = 0; cell < data.Cells.Length && cell < row.Cells.Count; cell++)
                {
                    if (!Equals(row.Cells[cell].Value, data.Cells[cell]))
                    {
                        row.Cells[cell].Value = data.Cells[cell];
                    }
                }

                var highlighted = data.Back == Theme.Changed;
                var back = data.Back ?? Theme.Background;
                var fore = data.Fore ?? Theme.Text;
                row.DefaultCellStyle.BackColor = back;
                row.DefaultCellStyle.ForeColor = fore;
                if (selectedKey is not null && data.Key == selectedKey)
                {
                    row.DefaultCellStyle.SelectionBackColor = highlighted ? Theme.ChangedSelected : Theme.Selection;
                    row.DefaultCellStyle.SelectionForeColor = highlighted ? Theme.Text : Color.White;
                }
                else
                {
                    // The grid selects a row by itself when a tab is first shown; such a
                    // selection must not hide the colours, so it looks like no selection.
                    row.DefaultCellStyle.SelectionBackColor = back;
                    row.DefaultCellStyle.SelectionForeColor = fore;
                }
            }

            if (firstRow >= 0 && firstRow < grid.Rows.Count)
            {
                grid.FirstDisplayedScrollingRowIndex = firstRow;
            }

            DataGridViewRow? picked = null;
            if (selectedKey is not null)
            {
                foreach (DataGridViewRow row in grid.Rows)
                {
                    if (Equals(row.Tag, selectedKey))
                    {
                        picked = row;
                        break;
                    }
                }
            }

            if (picked is null)
            {
                grid.CurrentCell = null;
                grid.ClearSelection();
            }
            else if (!picked.Selected)
            {
                grid.CurrentCell = picked.Cells[0];
                picked.Selected = true;
            }
        }
        finally
        {
            grid.ResumeLayout();
        }
    }
}
