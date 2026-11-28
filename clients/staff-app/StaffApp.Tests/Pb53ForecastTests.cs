using System.Net;
using System.Text;
using StaffApp.Configuration;
using StaffApp.Models;
using StaffApp.Services;
using StaffApp.UI;
using Xunit;

namespace StaffApp.Tests;

public class Pb53ForecastTests
{
    private static string Body(string sku = "SKU-0001") => $$"""
        {"business_date":"2026-11-28","items":[{"sku":"{{sku}}","name":"Sữa tươi 1L","category":"Dairy",
         "horizon_days":7,"predicted_demand":12.5,"sellable_stock":4,"surplus_shortage":-8.5,
         "balance_status":"SHORTAGE","model_version":"hgb-v1","created_at":"2026-11-28T01:00:00Z",
         "sold_last_7_days":9}]}
        """;

    private static ForecastLine Line(int index) => new($"SKU-{index:00}", "Sản phẩm " + index, "Dairy", 7,
        index / 2, 10, -index, index % 3 == 0 ? "SHORTAGE" : "SURPLUS", "hgb-v1",
        DateTimeOffset.Parse("2026-11-28T01:00:00Z"), index);

    [Fact]
    public void Pb53_3_parses_all_forecast_fields_and_shared_display_names()
    {
        var data = ApiParsers.Forecasts(Body());
        Assert.Equal(new DateOnly(2026, 11, 28), data.BusinessDate);
        var line = Assert.Single(data.Items);
        Assert.Equal((12.5m, 4, -8.5m, 9, 7), (line.PredictedDemand, line.SellableStock,
            line.SurplusShortage, line.SoldLast7Days, line.HorizonDays));
        Assert.Equal("hgb-v1", line.ModelVersion);
        var cells = ForecastRows.Cells(line, TimeZoneInfo.Utc);
        Assert.Equal("Sữa", cells[1]);
        Assert.Equal("12.5", cells[2]);
        Assert.Equal("Thiếu hàng", cells[5]);
        Assert.Equal("28/11 01:00", cells[7]);
    }

    [Theory]
    [InlineData("\"predicted_demand\":12.5,", "")]
    [InlineData("\"category\":\"Dairy\"", "\"category\":7")]
    [InlineData("\"sold_last_7_days\":9", "\"sold_last_7_days\":\"nine\"")]
    public void Pb53_3_bad_or_missing_fields_are_errors(string from, string to) =>
        Assert.Throws<FormatException>(() => ApiParsers.Forecasts(Body().Replace(from, to)));

    [Fact]
    public void Pb53_3_top_ten_and_shortages_are_deterministic_without_mutating_table_order()
    {
        var rows = Enumerable.Range(0, 12).Select(Line).ToArray();
        var original = rows.Select(x => x.Sku).ToArray();
        Assert.Equal(new[] { "SKU-10", "SKU-11", "SKU-08", "SKU-09", "SKU-06", "SKU-07",
            "SKU-04", "SKU-05", "SKU-02", "SKU-03" }, ForecastRows.Top10(rows).Select(x => x.Sku));
        Assert.Equal(new[] { "SKU-09", "SKU-06", "SKU-03", "SKU-00" },
            ForecastRows.Shortages(rows).Select(x => x.Sku));
        Assert.Equal(original, rows.Select(x => x.Sku));
        Assert.Empty(ForecastRows.Top10(Array.Empty<ForecastLine>()));
    }

    private sealed class GatedApi : HttpMessageHandler
    {
        public List<TaskCompletionSource<string>> Answers { get; } = new();
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Assert.EndsWith("/staff/forecasts", request.RequestUri!.AbsolutePath);
            var answer = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            lock (Answers) Answers.Add(answer);
            return new HttpResponseMessage(HttpStatusCode.OK) {
                Content = new StringContent(await answer.Task.WaitAsync(token), Encoding.UTF8, "application/json")
            };
        }
    }

    private static IEnumerable<Control> All(Control root) =>
        root.Controls.Cast<Control>().SelectMany(c => new[] { c }.Concat(All(c)));

    private static void PumpUntil(Func<bool> ready)
    {
        var until = DateTime.UtcNow.AddSeconds(10);
        while (!ready())
        {
            Assert.True(DateTime.UtcNow < until, "Timed out waiting for UI");
            Application.DoEvents();
            Thread.Sleep(5);
        }
        for (var i = 0; i < 10; i++) { Application.DoEvents(); Thread.Sleep(5); }
    }

    [Fact]
    public void Pb53_3_stale_or_disposed_forecast_answers_never_replace_the_current_view()
    {
        Exception? failure = null;
        var thread = new Thread(() => {
            try
            {
                using var handler = new GatedApi();
                using var api = new StaffApiClient(new HttpClient(handler), "https://localhost/api/v1", "test");
                var config = new LoadedConfig(new AppSettings(), "ca.crt", "test",
                    new TokenInfo("staff", "Staff", "STORE-DN1", null));
                using var form = new MainForm(config, api) {
                    Location = new Point(-3000,-3000), StartPosition = FormStartPosition.Manual, ShowInTaskbar = false
                };
                form.Show();
                var tabs = form.Controls.OfType<TabControl>().Single();
                tabs.SelectedIndex = 4;
                PumpUntil(() => handler.Answers.Count == 1);
                tabs.SelectedIndex = 0;
                tabs.SelectedIndex = 4;
                PumpUntil(() => handler.Answers.Count == 2);
                handler.Answers[1].SetResult(Body("NEW-SKU"));
                var grid = All(tabs.TabPages[4]).OfType<DataGridView>().Single();
                PumpUntil(() => grid.Rows.Count == 1 && grid.Rows[0].Cells[0].Value?.ToString()?.Contains("NEW-SKU") == true);
                Assert.Equal(Color.FromArgb(255,229,180), grid.Rows[0].DefaultCellStyle.BackColor);
                Assert.All(All(tabs.TabPages[4]).OfType<LiveChartsCore.SkiaSharpView.WinForms.CartesianChart>(),
                    chart => Assert.Equal(0d, chart.XAxes.Single().MinLimit));
                handler.Answers[0].SetResult(Body("OLD-SKU"));
                for (var i=0;i<30;i++){Application.DoEvents();Thread.Sleep(5);}
                Assert.Contains("NEW-SKU",grid.Rows[0].Cells[0].Value!.ToString());
                var refresh = All(tabs.TabPages[4]).OfType<Button>().Single();
                refresh.PerformClick();
                PumpUntil(() => handler.Answers.Count == 3);
                handler.Answers[2].SetResult("{\"business_date\":\"2026-11-28\",\"items\":[]}");
                PumpUntil(() => grid.Rows.Count == 0);
                Assert.Contains(All(tabs.TabPages[4]).OfType<Label>(), x => x.Text == "Chưa có dự báo cho cửa hàng này.");
                tabs.TabPages[4].Controls.OfType<ForecastTab>().Single().Clear();
                Assert.DoesNotContain(All(tabs.TabPages[4]).OfType<Label>(), x => x.Text == "Chưa có dự báo cho cửa hàng này.");
                refresh.PerformClick();
                PumpUntil(() => handler.Answers.Count == 4);
                form.Close();
                handler.Answers[3].SetResult(Body("LATE-SKU"));
                for(var i=0;i<30;i++){Application.DoEvents();Thread.Sleep(5);}
                Assert.True(form.IsDisposed);
            }
            catch(Exception error){failure=error;}
        });
        thread.SetApartmentState(ApartmentState.STA);thread.Start();thread.Join();
        Assert.Null(failure);
    }
}
