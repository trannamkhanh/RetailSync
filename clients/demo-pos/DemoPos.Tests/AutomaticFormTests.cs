using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Services;
using DemoPos.UI;
using Xunit;

namespace DemoPos.Tests;

public sealed class AutomaticFormTests
{
    private static void OnStaThread(Action action)
    {
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try { action(); }
            catch (Exception error) { failure = error; }
        });
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        if (failure is not null)
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
    }

    private static LoadedConfig Configuration(string directory, bool mock)
    {
        using var authority = TestCertificates.CreateAuthority();
        var caPath = Path.Combine(directory, "ca.crt");
        File.WriteAllText(caPath, authority.ExportCertificatePem());
        return new LoadedConfig
        {
            Config = new AppConfig
            {
                UseMock = mock,
                Terminals = new() { new() { PosId = "TEST-POS", StoreId = "TEST-STORE" } },
                Products = new() { new() { Sku = "TEST-SKU", Name = "Test", UnitPrice = 100m } },
            },
            Paths = new AppPaths
            {
                RepoRoot = directory, CaCertificate = caPath, ClientCertificateDir = directory,
                TokensFile = Path.Combine(directory, "tokens.json"),
                SettingsFile = Path.Combine(directory, "settings.json"),
                LocalSettingsFile = Path.Combine(directory, "local.json"),
            },
            Tokens = new Dictionary<string, string>(),
            Problems = Array.Empty<string>(),
        };
    }

    [Fact]
    public void Pb45_2_AutomaticTickPreservesManualCart()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            using var form = new MainForm(Configuration(directory.Path, mock: true), directory.Path);
            form.AddProductToCart("TEST-SKU", 4);
            form.AutomaticToggle.Checked = true;

            form.RunAutomaticTickAsync().GetAwaiter().GetResult();

            Assert.Equal(4, Assert.Single(form.CartItems).Quantity);
            Assert.Equal(0, form.HistoryCount);
            Assert.True(form.AutomaticToggle.Checked);
        });
    }

    [Fact]
    public void Pb45_2_QueueWriteFailureStopsAutomaticModeAndKeepsSaleInCart()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            using var form = new MainForm(Configuration(directory.Path, mock: false), directory.Path);
            // Deny access to the real journal so the queue append fails.
            using var lockedJournal = new FileStream(Path.Combine(directory.Path, "TEST-POS.jsonl"),
                FileMode.Open, FileAccess.ReadWrite, FileShare.None);
            form.AutomaticToggle.Checked = true;

            form.RunAutomaticTickAsync().GetAwaiter().GetResult();

            Assert.False(form.AutomaticToggle.Checked);
            var quantity = Assert.Single(form.CartItems).Quantity;
            Assert.InRange(quantity, 1, 2);
            form.RunAutomaticTickAsync().GetAwaiter().GetResult();
            Assert.Equal(quantity, Assert.Single(form.CartItems).Quantity);
            Assert.Equal(0, form.HistoryCount);
        });
    }

    [Fact]
    public void Pos45_5_FormQueuesTwoAutomaticSalesAndStopsWhenToggledOff()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            using var form = new MainForm(Configuration(directory.Path, mock: false), directory.Path);
            // Hold the sender lease to leave the real journal entries pending for inspection.
            using var sender = new FileStream(Path.Combine(directory.Path, "TEST-POS.sender.lock"),
                FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            form.AutomaticToggle.Checked = true;
            form.RunAutomaticTickAsync().GetAwaiter().GetResult();
            form.RunAutomaticTickAsync().GetAwaiter().GetResult();
            var queue = new DurableEventQueue(directory.Path, "TEST-POS");
            Assert.Equal(2, queue.Count);
            var sales = File.ReadAllLines(Path.Combine(directory.Path, "TEST-POS.jsonl"))
                .Select(line => System.Text.Json.JsonDocument.Parse(line))
                .Where(record => record.RootElement.GetProperty("Kind").GetString() == "enqueue")
                .Select(record => PosEventJson.Deserialize(
                    record.RootElement.GetProperty("Entry").GetProperty("Body").GetString()!))
                .ToList();
            Assert.Equal(2, sales.Count);
            Assert.All(sales, sale => Assert.Equal(EventTypes.Sale, sale.EventType));
            Assert.Empty(form.CartItems);
            form.AutomaticToggle.Checked = false;
            form.RunAutomaticTickAsync().GetAwaiter().GetResult();
            Assert.Equal(2, queue.Count);
            Assert.Empty(form.CartItems);
        });
    }

    [Fact]
    public void Pb45_2_MockRejectionStopsAutomaticModeAndPreservesCart()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            using var form = new MainForm(Configuration(directory.Path, mock: true), directory.Path);
            form.AutomaticToggle.Checked = true;
            for (var tick = 0; tick < 32 && form.AutomaticToggle.Checked; tick++)
                form.RunAutomaticTickAsync().GetAwaiter().GetResult();
            Assert.False(form.AutomaticToggle.Checked);
            Assert.Single(form.CartItems);
        });
    }
}
