using DemoPos.Configuration;
using DemoPos.Models;
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
    public void AutomaticTickPreservesManualCart()
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
    public void QueueWriteFailureStopsAutomaticModeAndKeepsSaleInCart()
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
}
