using System.Net;
using System.Text;
using StaffApp.Configuration;
using StaffApp.Services;
using StaffApp.UI;
using Xunit;

namespace StaffApp.Tests;

/// <summary>
/// PB-50-3 follow-up: at the default 1280 x 780 window and the default 12 pt font, the nine Giảm giá
/// columns fit the grid with batch-level rows of three stores, and no cell text is cut. The form runs
/// on its own STA thread against a fake API; nothing needs the running stack.
/// </summary>
public class DiscountsLayoutTests
{
    private const string Body = """
        {"items":[
          {"store_id":"STORE-DN1","store_name":"Cửa hàng Hải Châu","distance_km":null,"sku":"SKU-0001",
           "name":"Fresh milk 1L","batch_id":"B-STORE-DN1-SKU-0001-1","expiry_date":"2026-11-27",
           "discount_pct":30.0,"list_price":32000.0,"discounted_price":22400.0,
           "decided_at":"2026-11-24T16:06:00Z","sold_at_discount":false},
          {"store_id":"STORE-DN3","store_name":"Cửa hàng Sơn Trà","distance_km":1.72,"sku":"SKU-0002",
           "name":"Yogurt 100g","batch_id":"B-STORE-DN3-SKU-0002-1","expiry_date":"2026-11-28",
           "discount_pct":30.0,"list_price":7000.0,"discounted_price":4900.0,
           "decided_at":"2026-11-24T16:07:00Z","sold_at_discount":true},
          {"store_id":"STORE-DN2","store_name":"Cửa hàng Thanh Khê","distance_km":4.42,"sku":"SKU-0002",
           "name":"Yogurt 100g","batch_id":"B-STORE-DN2-SKU-0002-1","expiry_date":"2026-11-28",
           "discount_pct":30.0,"list_price":7000.0,"discounted_price":4900.0,
           "decided_at":"2026-11-24T16:08:00Z","sold_at_discount":false}]}
        """;

    // DataGridView draws cell text inside a few pixels of its own margins on top of the padding.
    private const int TextMargin = 4;

    private sealed class FakeApi : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(Body, Encoding.UTF8, "application/json"),
            });
    }

    private static void OnSta(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try
            {
                action();
            }
            catch (Exception error)
            {
                failure = error;
            }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
        {
            throw new Xunit.Sdk.XunitException(failure.ToString());
        }
    }

    private static IEnumerable<Control> Descendants(Control root) =>
        root.Controls.Cast<Control>().SelectMany(child => new[] { child }.Concat(Descendants(child)));

    // 12 pt is the default font at 100 % display scaling; 15 pt gives the same pixels as 12 pt at
    // 125 %, where the app (PerMonitorV2) draws larger text but keeps the 1280 px window.
    [Theory]
    [InlineData(false, 12f)]
    [InlineData(true, 12f)]
    [InlineData(false, 15f)]
    [InlineData(true, 15f)]
    public void Pb50_3_nine_columns_fit_the_default_window_and_cut_no_text(bool allStores, float fontSize)
    {
        OnSta(() =>
        {
            var config = new LoadedConfig(new AppSettings { FontSize = fontSize }, "ca.crt", "token",
                new TokenInfo("staff_dn1", "Staff", "STORE-DN1", null));
            using var api = new StaffApiClient(new HttpClient(new FakeApi()), "https://localhost:8443/api/v1", "token");
            using var form = new MainForm(config, api)
            {
                StartPosition = FormStartPosition.Manual, Location = new Point(-3000, -3000), ShowInTaskbar = false,
            };
            Assert.Equal(new Size(1280, 780), form.Size);
            form.Show();
            var grid = Descendants(form).OfType<DataGridView>().Single(g => g.Columns.Count == 9);
            if (allStores)
            {
                Descendants(form).OfType<RadioButton>().Single(r => r.Text == "Tất cả cửa hàng").Checked = true;
            }

            Descendants(form).OfType<TabControl>().Single().SelectedIndex = 3;
            var deadline = DateTime.UtcNow.AddSeconds(10);
            while (grid.Rows.Count < 3 && DateTime.UtcNow < deadline)
            {
                Application.DoEvents();
            }

            for (var i = 0; i < 20; i++)
            {
                Application.DoEvents();
            }

            Assert.Equal(3, grid.Rows.Count);
            var columnsWidth = grid.Columns.GetColumnsWidth(DataGridViewElementStates.Visible);
            Assert.True(columnsWidth <= grid.DisplayRectangle.Width,
                $"columns {columnsWidth} px > grid {grid.DisplayRectangle.Width} px");

            foreach (DataGridViewRow row in grid.Rows)
            {
                foreach (DataGridViewCell cell in row.Cells)
                {
                    var style = cell.InheritedStyle;
                    var text = cell.FormattedValue?.ToString() ?? string.Empty;
                    var room = cell.OwningColumn.Width - style.Padding.Horizontal - TextMargin;
                    var wraps = style.WrapMode == DataGridViewTriState.True;
                    var needed = wraps
                        ? TextRenderer.MeasureText(text, style.Font, new Size(room, int.MaxValue),
                            TextFormatFlags.WordBreak)
                        : TextRenderer.MeasureText(text, style.Font);
                    var where = $"'{text}' in {cell.OwningColumn.HeaderText}";
                    Assert.True(needed.Width <= room, $"{where}: needs {needed.Width} px, has {room} px");
                    Assert.True(needed.Height <= row.Height, $"{where}: needs {needed.Height} px high, row {row.Height} px");
                }
            }
        });
    }
}
