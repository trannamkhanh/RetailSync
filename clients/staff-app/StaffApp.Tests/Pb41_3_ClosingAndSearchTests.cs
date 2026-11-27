using System.Net;
using System.Text;
using StaffApp.Configuration;
using StaffApp.Services;
using StaffApp.UI;
using Xunit;

namespace StaffApp.Tests;

/// <summary>
/// PB-41-3: a Search answer that is no longer the latest is dropped, and an answer that arrives after the
/// window closed changes nothing and throws nothing. The form runs on its own STA thread against a fake
/// API whose answers the test releases; nothing needs the running stack.
/// </summary>
public class Pb41_3_ClosingAndSearchTests
{
    /// <summary>Answers each request path with the task the test registered for it (200 OK).</summary>
    private sealed class GatedApi : HttpMessageHandler
    {
        private readonly Dictionary<string, TaskCompletionSource<string>> _answers = new();

        public List<string> Requests { get; } = new();

        public TaskCompletionSource<string> On(string pathAndQuery)
        {
            var answer = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
            _answers[pathAndQuery] = answer;
            return answer;
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            var key = request.RequestUri!.PathAndQuery.Replace("/api/v1", string.Empty);
            lock (Requests)
            {
                Requests.Add(key);
            }

            var body = await _answers[key].Task.WaitAsync(token);
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }

    private static string Product(string sku, string barcode, string batch) =>
        $$"""
        {"sku":"{{sku}}","barcode":"{{barcode}}","name":"Product {{sku}}","category":"Dairy","unit_price":1000.0,
         "quantity":5,"batches":[{"batch_id":"{{batch}}","expiry_date":"2026-12-01","quantity":5}]}
        """;

    private static string Stores(string sku, string name) =>
        $$"""{"sku":"{{sku}}","stores":[{"store_id":"STORE-DN2","name":"{{name}}","qty":3,"distance_km":4.4}]}""";

    private const string BarcodeA = "8930000000011";
    private const string BarcodeB = "8930000000028";

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

    private static void PumpUntil(Func<bool> done, string what)
    {
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (!done())
        {
            Assert.True(DateTime.UtcNow < deadline, $"timed out waiting for {what}");
            Application.DoEvents();
            Thread.Sleep(5);
        }

        Pump(TimeSpan.FromMilliseconds(100));
    }

    /// <summary>Lets late answers come back through the thread pool and the UI message queue.</summary>
    private static void Pump(TimeSpan time)
    {
        var until = DateTime.UtcNow + time;
        while (DateTime.UtcNow < until)
        {
            Application.DoEvents();
            Thread.Sleep(5);
        }
    }

    /// <summary>Runs <paramref name="body"/> with a shown form; exceptions of async UI handlers are collected.</summary>
    private static void WithForm(GatedApi api, Action<MainForm, List<Exception>, StaffApiClient> body)
    {
        OnSta(() =>
        {
            var errors = new List<Exception>();
            ThreadExceptionEventHandler collect = (_, args) => errors.Add(args.Exception);
            Application.ThreadException += collect;
            try
            {
                var config = new LoadedConfig(new AppSettings(), "ca.crt", "token",
                    new TokenInfo("staff_dn1", "Staff", "STORE-DN1", null));
                using var client = new StaffApiClient(new HttpClient(api), "https://localhost:8443/api/v1", "token");
                var form = new MainForm(config, client)
                {
                    StartPosition = FormStartPosition.Manual, Location = new Point(-3000, -3000), ShowInTaskbar = false,
                };
                form.Show();
                body(form, errors, client);
                if (!form.IsDisposed)
                {
                    form.Dispose();
                }
            }
            finally
            {
                Application.ThreadException -= collect;
            }
        });
    }

    private static void Search(MainForm form, string barcode)
    {
        Descendants(form).OfType<TextBox>().Single().Text = barcode;
        Descendants(form).OfType<Button>().Single(button => button.Text == "Tìm").PerformClick();
    }

    private static DataGridView BatchGrid(MainForm form) =>
        Descendants(form).OfType<DataGridView>().Single(grid => grid.Columns.Count == 3 && grid.Columns[0].HeaderText == "Lô");

    private static DataGridView NearbyGrid(MainForm form) =>
        Descendants(form).OfType<DataGridView>().Single(grid => grid.Columns.Count == 3 && grid.Columns[0].HeaderText == "Cửa hàng");

    private static IEnumerable<string> Column0(DataGridView grid) =>
        grid.Rows.Cast<DataGridViewRow>().Select(row => row.Cells[0].Value?.ToString() ?? string.Empty);

    [Fact]
    public void Pb41_3_a_stale_search_answer_is_dropped()
    {
        var api = new GatedApi();
        var productA = api.On($"/products/barcode/{BarcodeA}");
        var stockA = api.On($"/products/barcode/{BarcodeA}/stock?from_store=STORE-DN1");
        api.On($"/products/barcode/{BarcodeB}").SetResult(Product("SKU-0002", BarcodeB, "B-NEW"));
        api.On($"/products/barcode/{BarcodeB}/stock?from_store=STORE-DN1").SetResult(Stores("SKU-0002", "Store new"));

        WithForm(api, (form, errors, _) =>
        {
            Search(form, BarcodeA);
            PumpUntil(() => api.Requests.Count == 1, "the first lookup");
            Search(form, BarcodeB);
            PumpUntil(() => NearbyGrid(form).Rows.Count == 1, "the second search to finish");

            // The first scan answers last: its product, then its stores.
            productA.SetResult(Product("SKU-0001", BarcodeA, "B-OLD"));
            stockA.SetResult(Stores("SKU-0001", "Store old"));
            Pump(TimeSpan.FromSeconds(1));

            Assert.Equal(new[] { "B-NEW" }, Column0(BatchGrid(form)));
            Assert.Equal(new[] { "Store new" }, Column0(NearbyGrid(form)));
            Assert.StartsWith("Product SKU-0002", Descendants(form).OfType<Label>().Single(l => l.Text.StartsWith("Product ")).Text);
            Assert.DoesNotContain($"/products/barcode/{BarcodeA}/stock?from_store=STORE-DN1", api.Requests);
            Assert.Empty(errors);
        });
    }

    [Fact]
    public void Pb41_3_a_stale_cross_store_answer_is_dropped()
    {
        var api = new GatedApi();
        api.On($"/products/barcode/{BarcodeA}").SetResult(Product("SKU-0001", BarcodeA, "B-OLD"));
        var stockA = api.On($"/products/barcode/{BarcodeA}/stock?from_store=STORE-DN1");
        api.On($"/products/barcode/{BarcodeB}").SetResult(Product("SKU-0002", BarcodeB, "B-NEW"));
        api.On($"/products/barcode/{BarcodeB}/stock?from_store=STORE-DN1").SetResult(Stores("SKU-0002", "Store new"));

        WithForm(api, (form, errors, _) =>
        {
            Search(form, BarcodeA);
            PumpUntil(() => api.Requests.Count == 2, "the first cross-store call");
            Search(form, BarcodeB);
            PumpUntil(() => NearbyGrid(form).Rows.Count == 1, "the second search to finish");

            stockA.SetResult(Stores("SKU-0001", "Store old"));
            Pump(TimeSpan.FromSeconds(1));

            Assert.Equal(new[] { "B-NEW" }, Column0(BatchGrid(form)));
            Assert.Equal(new[] { "Store new" }, Column0(NearbyGrid(form)));
            Assert.Empty(errors);
        });
    }

    [Theory]
    [InlineData("product")]
    [InlineData("stock")]
    [InlineData("alerts")]
    public void Pb41_3_an_answer_after_the_window_closed_changes_nothing_and_throws_nothing(string pending)
    {
        var api = new GatedApi();
        var product = api.On($"/products/barcode/{BarcodeA}");
        var stock = api.On($"/products/barcode/{BarcodeA}/stock?from_store=STORE-DN1");
        var alerts = api.On("/near-expiry-alerts");
        if (pending != "product")
        {
            product.SetResult(Product("SKU-0001", BarcodeA, "B-OLD"));
        }

        WithForm(api, (form, errors, client) =>
        {
            if (pending == "alerts")
            {
                Descendants(form).OfType<TabControl>().Single().SelectedIndex = 1;
                PumpUntil(() => api.Requests.Contains("/near-expiry-alerts"), "the alerts call");
            }
            else
            {
                Search(form, BarcodeA);
                PumpUntil(() => api.Requests.Count == (pending == "product" ? 1 : 2), "the pending call");
            }

            var status = Descendants(form).OfType<StatusStrip>().Single().Items[0];
            var statusAtClose = status.Text;
            var requestsAtClose = api.Requests.Count;
            form.Close();
            form.Dispose();
            client.Dispose();  // as Program.Main does once the window is gone

            product.TrySetResult(Product("SKU-0001", BarcodeA, "B-OLD"));
            stock.TrySetResult(Stores("SKU-0001", "Store old"));
            alerts.TrySetResult("""{"items":[]}""");
            Pump(TimeSpan.FromSeconds(1));

            Assert.True(form.IsDisposed);
            Assert.Equal(requestsAtClose, api.Requests.Count);  // no call starts after the window closed
            Assert.Equal(statusAtClose, status.Text);
            Assert.Empty(errors);
        });
    }

    [Fact]
    public void Pb41_3_the_guard_drops_answers_for_a_closed_window_or_a_newer_request()
    {
        var requests = new LatestRequest();
        var ticket = requests.Next();

        Assert.True(requests.Applies(ticket, windowGone: false));
        Assert.False(requests.Applies(ticket, windowGone: true));
        requests.Next();
        Assert.False(requests.Applies(ticket, windowGone: false));
    }
}
