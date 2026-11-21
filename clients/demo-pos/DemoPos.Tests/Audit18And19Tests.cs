using System.ComponentModel;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Security;
using DemoPos.Services;
using DemoPos.UI;
using Xunit;

namespace DemoPos.Tests;

public sealed class Audit18And19Tests
{
    private static void OnStaThread(Action action)
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
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        }
    }

    private static void PumpUntil(Func<bool> condition, int timeoutMs = 5000)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        while (!condition())
        {
            Application.DoEvents();
            if (Environment.TickCount64 > deadline)
            {
                throw new TimeoutException("Timed out waiting for UI condition.");
            }

            Thread.Sleep(5);
        }

        Application.DoEvents();
    }

    private static T GetPrivateField<T>(object target, string fieldName)
    {
        var field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic)
                    ?? throw new MissingFieldException(target.GetType().FullName, fieldName);
        return (T)field.GetValue(target)!;
    }

    private static void SetPrivateField(object target, string fieldName, object? value)
    {
        var field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic)
                    ?? throw new MissingFieldException(target.GetType().FullName, fieldName);
        field.SetValue(target, value);
    }

    private static object? InvokePrivate(object target, string methodName, params object?[] args)
    {
        var method = target.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.NonPublic)
                     ?? throw new MissingMethodException(target.GetType().FullName, methodName);
        return method.Invoke(target, args);
    }

    private static void InitializeTabsAndStopTimers(MainForm form)
    {
        // Stop background polling timers so tests drive async paths deterministically.
        GetPrivateField<System.Windows.Forms.Timer>(form, "_monitorTimer").Stop();
        GetPrivateField<System.Windows.Forms.Timer>(form, "_statusTimer").Stop();
        GetPrivateField<System.Windows.Forms.Timer>(form, "_queueTimer").Stop();

        // Realize WinForms handles and DataGridView bindings off-screen without flashing UI.
        form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(-32000, -32000);
        form.Show();
        for (var i = 0; i < form.Tabs.TabPages.Count; i++)
        {
            form.Tabs.SelectedIndex = i;
            Application.DoEvents();
        }

        form.Tabs.SelectedIndex = 0;
        Application.DoEvents();
    }

    private static LoadedConfig BuildLiveConfig(string directory, bool mock = false, bool badCa = false)
    {
        using var authority = TestCertificates.CreateAuthority();
        var caPath = Path.Combine(directory, "ca.crt");
        if (badCa)
        {
            using var nonCa = TestCertificates.CreateServerCertificate(authority, "not-a-ca");
            File.WriteAllText(caPath, nonCa.ExportCertificatePem());
        }
        else
        {
            File.WriteAllText(caPath, authority.ExportCertificatePem());
        }

        using var certA = TestCertificates.CreateClientCertificate(authority, "POS-DN1-01");
        TestCertificates.WriteClientPem(directory, certA, "POS-DN1-01");
        using var certB = TestCertificates.CreateClientCertificate(authority, "POS-DN2-01");
        TestCertificates.WriteClientPem(directory, certB, "POS-DN2-01");

        var tokensPath = Path.Combine(directory, "tokens.json");
        var tokens = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["POS-DN1-01"] = "token-pos-1",
            ["POS-DN2-01"] = "token-pos-2",
            ["staff_dn1"] = "token-staff-1",
            ["staff_dn2"] = "token-staff-2",
        };
        File.WriteAllText(tokensPath, JsonSerializer.Serialize(tokens));

        return new LoadedConfig
        {
            Config = new AppConfig
            {
                UseMock = mock,
                PosBaseUrl = "https://127.0.0.1:19443/api/v1",
                MonitorBaseUrl = "https://127.0.0.1:18443/api/v1",
                Terminals = new List<TerminalConfig>
                {
                    new() { StoreId = "STORE-DN1", StoreName = "Hai Chau", PosId = "POS-DN1-01" },
                    new() { StoreId = "STORE-DN2", StoreName = "Thanh Khe", PosId = "POS-DN2-01" },
                },
                Products = new List<ProductConfig>
                {
                    new() { Sku = "SKU-001", Barcode = "8930000000001", Name = "Sua tuoi", UnitPrice = 25000m },
                },
            },
            Paths = new AppPaths
            {
                RepoRoot = directory,
                CaCertificate = caPath,
                ClientCertificateDir = directory,
                TokensFile = tokensPath,
                SettingsFile = Path.Combine(directory, "appsettings.json"),
                LocalSettingsFile = Path.Combine(directory, "appsettings.Local.json"),
            },
            Tokens = tokens,
            Problems = Array.Empty<string>(),
        };
    }

    private sealed class StubHttpHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _responder;

        public StubHttpHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> responder)
        {
            _responder = responder;
        }

        public List<string> Bodies { get; } = new();

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
            Bodies.Add(body);
            return await _responder(request, cancellationToken).ConfigureAwait(false);
        }
    }

    [Fact]
    public void Audit18_F12FailureScenariosBypassDurableQueue()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: false);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var requests = 0;
            using var handler = new StubHttpHandler((_, _) =>
            {
                var n = Interlocked.Increment(ref requests);
                var (status, code) = n switch
                {
                    1 => (HttpStatusCode.Conflict, "CONFLICT"),
                    2 => (HttpStatusCode.Conflict, "INSUFFICIENT_STOCK"),
                    3 => (HttpStatusCode.UnprocessableEntity, "UNREGISTERED_STORE"),
                    _ => (HttpStatusCode.Conflict, "RETURN_QTY_EXCEEDED"),
                };
                var payload = JsonSerializer.Serialize(new
                {
                    code,
                    message = $"Simulated {code}",
                });
                return Task.FromResult(new HttpResponseMessage(status)
                {
                    Content = new StringContent(payload, Encoding.UTF8, "application/json"),
                });
            });

            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, handler);

            // Seed one OK SALE in history so Conflict and ReturnLimit can run.
            var history = GetPrivateField<Dictionary<string, List<TxnRecord>>>(form, "_historyByPos");
            history["POS-DN1-01"].Add(new TxnRecord
            {
                Time = DateTime.Now,
                EventType = EventTypes.Sale,
                TransactionId = "POS-DN1-01-20261121-0001",
                StoreId = "STORE-DN1",
                PosId = "POS-DN1-01",
                Outcome = nameof(PosOutcome.OK),
                Code = "OK",
                ItemsText = "SKU-001×1",
                RawBody = "{}",
                Items = new List<PosEventItem>
                {
                    new() { Sku = "SKU-001", Quantity = 1, UnitPrice = 25000m },
                },
            });

            // Stub monitor client so post-send RefreshMonitorAsync does not hit network.
            var monitor = GetPrivateField<MonitorApiClient>(form, "_monitorClient");
            using var monitorHandler = new StubHttpHandler((_, _) =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("{\"store_id\":\"STORE-DN1\",\"items\":[]}", Encoding.UTF8, "application/json"),
                }));
            SetPrivateField(monitor, "_http", new HttpClient(monitorHandler));

            foreach (var kind in new[]
                     {
                         ScenarioKind.Conflict,
                         ScenarioKind.InsufficientStock,
                         ScenarioKind.UnregisteredStore,
                         ScenarioKind.ReturnLimit,
                     })
            {
                var task = (Task)InvokePrivate(form, "RunScenarioAsync", kind)!;
                PumpUntil(() => task.IsCompleted);
                task.GetAwaiter().GetResult();
            }

            // Wait briefly in case a queued background drain ran on unmodified main.
            Thread.Sleep(100);
            Application.DoEvents();

            Assert.Equal(4, handler.Bodies.Count);
            var queue = new DurableEventQueue(directory.Path, "POS-DN1-01");
            Assert.Equal(0, queue.Count);
            Assert.Empty(queue.Rejected);
            var journalPath = Path.Combine(directory.Path, "POS-DN1-01.jsonl");
            var lines = File.Exists(journalPath) ? File.ReadAllLines(journalPath) : Array.Empty<string>();
            Assert.Empty(lines);
        });
    }

    [Fact]
    public void Audit18_SwitchingTerminalDuringPendingDrainDropsStaleResult()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: false);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var sendStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var sendRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            using var handler = new StubHttpHandler((_, _) =>
            {
                sendStarted.TrySetResult(true);
                return sendRelease.Task;
            });

            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, handler);

            var monitor = GetPrivateField<MonitorApiClient>(form, "_monitorClient");
            using var monitorHandler = new StubHttpHandler((_, _) =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("{\"store_id\":\"STORE-DN1\",\"items\":[]}", Encoding.UTF8, "application/json"),
                }));
            SetPrivateField(monitor, "_http", new HttpClient(monitorHandler));

            // Enqueue one sale on POS-DN1-01 and begin draining while POS-DN1-01 is selected.
            var queues = GetPrivateField<Dictionary<string, DurableEventQueue>>(form, "_queues");
            queues["POS-DN1-01"].Enqueue("""{"transaction_id":"TXN-1","event_type":"SALE"}""");
            var terminalA = loaded.Config.Terminals[0];
            var drainTask = (Task)InvokePrivate(form, "DrainTerminalAsync", terminalA)!;

            PumpUntil(() => sendStarted.Task.IsCompleted);

            // Switch away to POS-DN2-01 and back to POS-DN1-01 (which clears ResultPanel to "—").
            form.SelectTerminal("POS-DN2-01");
            form.SelectTerminal("POS-DN1-01");

            var outcomeLabel = GetPrivateField<Label>(form.Result, "_outcome");
            Assert.Equal("—", outcomeLabel.Text);

            // Now complete POS-DN1-01's old drain with HTTP 200 OK.
            sendRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"outcome":"OK","code":"OK","message":"Accepted","current_stock":{"SKU-001":9}}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => drainTask.IsCompleted);
            drainTask.GetAwaiter().GetResult();

            // Switching away during a pending drain must not apply the old result onto the cleared panel.
            Assert.Equal("—", outcomeLabel.Text);
        });
    }

    [Fact]
    public void Audit18_TogglingToMockDuringPendingDrainDropsStaleResult()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: false);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var sendStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var sendRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            using var handler = new StubHttpHandler((_, _) =>
            {
                sendStarted.TrySetResult(true);
                return sendRelease.Task;
            });

            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, handler);

            var queues = GetPrivateField<Dictionary<string, DurableEventQueue>>(form, "_queues");
            queues["POS-DN1-01"].Enqueue("""{"transaction_id":"TXN-MOCK","event_type":"SALE"}""");
            var terminalA = loaded.Config.Terminals[0];
            var drainTask = (Task)InvokePrivate(form, "DrainTerminalAsync", terminalA)!;

            PumpUntil(() => sendStarted.Task.IsCompleted);

            // Toggle to MOCK while the LIVE drain is still in flight.
            var toggleTask = form.ToggleMockAsync();
            PumpUntil(() => toggleTask.IsCompleted);
            toggleTask.GetAwaiter().GetResult();
            Assert.True(form.IsMockMode);

            var outcomeLabel = GetPrivateField<Label>(form.Result, "_outcome");
            Assert.Equal("INFO", outcomeLabel.Text);

            // Complete the stale LIVE drain.
            sendRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"outcome":"OK","code":"OK","message":"Accepted","current_stock":{"SKU-001":9}}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => drainTask.IsCompleted);
            drainTask.GetAwaiter().GetResult();

            // Must NOT overwrite MOCK mode's INFO banner with the stale LIVE OK result.
            Assert.Equal("INFO", outcomeLabel.Text);
        });
    }

    [Fact]
    public void Audit18_SwitchingTerminalDuringMonitorRefreshDropsStaleStock()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: false);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var stockStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var stockRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            var monitor = GetPrivateField<MonitorApiClient>(form, "_monitorClient");
            using var monitorHandler = new StubHttpHandler((req, _) =>
            {
                if (req.RequestUri!.AbsolutePath.Contains("STORE-DN1", StringComparison.OrdinalIgnoreCase))
                {
                    stockStarted.TrySetResult(true);
                    return stockRelease.Task;
                }

                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(
                        """{"store_id":"STORE-DN2","items":[{"sku":"SKU-001","quantity":77}]}""",
                        Encoding.UTF8, "application/json"),
                });
            });
            SetPrivateField(monitor, "_http", new HttpClient(monitorHandler));

            var refreshTask = (Task)InvokePrivate(form, "RefreshMonitorAsync")!;
            PumpUntil(() => stockStarted.Task.IsCompleted);

            // Switch to POS-DN2-01 (STORE-DN2) while STORE-DN1's request is still pending.
            form.SelectTerminal("POS-DN2-01");

            // Now resolve STORE-DN1's stale response.
            stockRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"store_id":"STORE-DN1","items":[{"sku":"SKU-001","quantity":11}]}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => refreshTask.IsCompleted);
            refreshTask.GetAwaiter().GetResult();

            var stockStatus = GetPrivateField<Label>(form, "_stockStatus");
            Assert.DoesNotContain("STORE-DN1", stockStatus.Text, StringComparison.OrdinalIgnoreCase);
            var stockView = GetPrivateField<BindingList<StockRow>>(form, "_stockView");
            Assert.DoesNotContain(stockView, row => row.Quantity == 11);
        });
    }

    [Fact]
    public void Audit18_TogglingToMockDuringStatusRefreshDropsStaleStatus()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: false);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var healthStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var healthRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            var monitor = GetPrivateField<MonitorApiClient>(form, "_monitorClient");
            using var monitorHandler = new StubHttpHandler((req, _) =>
            {
                if (req.RequestUri!.AbsolutePath.EndsWith("/health", StringComparison.OrdinalIgnoreCase))
                {
                    healthStarted.TrySetResult(true);
                    return healthRelease.Task;
                }

                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("""{"store_id":"STORE-DN1","items":[]}""", Encoding.UTF8, "application/json"),
                });
            });
            SetPrivateField(monitor, "_http", new HttpClient(monitorHandler));

            var statusTask = (Task)InvokePrivate(form, "RefreshStatusAsync")!;
            PumpUntil(() => healthStarted.Task.IsCompleted);

            var toggleTask = form.ToggleMockAsync();
            PumpUntil(() => toggleTask.IsCompleted);
            toggleTask.GetAwaiter().GetResult();
            Assert.True(form.IsMockMode);

            healthRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"status":"ok"}""", Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => statusTask.IsCompleted);
            statusTask.GetAwaiter().GetResult();

            // Wait for any coalesced refresh queued during ToggleMockAsync.
            Application.DoEvents();
            var middlewareStatus = GetPrivateField<ToolStripStatusLabel>(form, "_middlewareStatus");
            Assert.Equal("Middleware: MOCK", middlewareStatus.Text);
        });
    }

    [Fact]
    public void Audit18_ToggleMockCatchesBadCaConfigurationException()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: true, badCa: true);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            var warnings = new List<(string Title, string Message)>();
            form.WarningPresenter = (title, message) => warnings.Add((title, message));

            var task = form.ToggleMockAsync();
            PumpUntil(() => task.IsCompleted);
            task.GetAwaiter().GetResult();

            Assert.True(form.IsMockMode);
            var warning = Assert.Single(warnings);
            Assert.Contains("CA", warning.Message, StringComparison.OrdinalIgnoreCase);
            var messageLabel = GetPrivateField<Label>(form.Result, "_message");
            Assert.Equal(warning.Message, messageLabel.Text);
        });
    }

    [Fact]
    public void Audit18_ReturnAndCancelRecheckBusyAfterModal()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: true);
            using var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            // Produce one OK SALE in MOCK mode so Return and Cancel are eligible.
            form.AddProductToCart("SKU-001", 2);
            var payTask = form.PayAsync();
            PumpUntil(() => payTask.IsCompleted);
            var payResult = payTask.GetAwaiter().GetResult();
            Assert.Equal(PosOutcome.OK, payResult.Outcome);
            Assert.Equal(1, form.HistoryCount);

            // Simulate _autoTimer setting _busy = true while ReturnDialog is open.
            form.ReturnPrompt = _ =>
            {
                SetPrivateField(form, "_busy", true);
                return (true, "SKU-001", 1);
            };
            var returnTask = (Task)InvokePrivate(form, "ReturnAsync")!;
            PumpUntil(() => returnTask.IsCompleted);
            returnTask.GetAwaiter().GetResult();

            Assert.Equal(1, form.HistoryCount);
            Assert.True(GetPrivateField<bool>(form, "_busy"));

            // Reset _busy and repeat the same check for CancelAsync.
            SetPrivateField(form, "_busy", false);
            form.CancelPrompt = _ =>
            {
                SetPrivateField(form, "_busy", true);
                return true;
            };
            var cancelTask = (Task)InvokePrivate(form, "CancelAsync")!;
            PumpUntil(() => cancelTask.IsCompleted);
            cancelTask.GetAwaiter().GetResult();

            Assert.Equal(1, form.HistoryCount);
            Assert.True(GetPrivateField<bool>(form, "_busy"));
        });
    }

    [Fact]
    public void Audit18_RefreshLogViewAfterDisposeDoesNotMutateView()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: true);
            var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);
            var logView = GetPrivateField<BindingList<RequestLogEntry>>(form, "_logView");
            Assert.Empty(logView);

            form.Dispose();

            form.RequestLog.Add(new RequestLogEntry
            {
                Method = "POST",
                Url = "mock://pos/events",
                Status = 200,
                ElapsedMs = 1,
                RequestBody = "{}",
                ResponseBody = "{}",
                Role = "MOCK",
                Subject = "mock",
                Kind = RequestKind.Mock,
            });
            InvokePrivate(form, "RefreshLogView");

            Assert.Empty(logView);
        });
    }

    [Fact]
    public void Audit18_UpdateTerminalHighlightReusesCachedBoldFont()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path, mock: true);
            var form = new MainForm(loaded, directory.Path);
            InitializeTabsAndStopTimers(form);

            form.SelectTerminal("POS-DN2-01");
            form.SelectTerminal("POS-DN1-01");
            var firstFont = form.TerminalsGrid.Rows[0].DefaultCellStyle.Font;
            Assert.NotNull(firstFont);
            Assert.True(firstFont!.Bold);

            form.SelectTerminal("POS-DN2-01");
            form.SelectTerminal("POS-DN1-01");
            var secondFont = form.TerminalsGrid.Rows[0].DefaultCellStyle.Font;

            Assert.Same(firstFont, secondFont);

            form.Dispose();
            Assert.Throws<ArgumentException>(() => _ = firstFont.Height);
        });
    }

    [Fact]
    public async Task Audit18_MockPosBackendUsesInvariantCultureForAuditTimestamp()
    {
        var originalCulture = CultureInfo.CurrentCulture;
        var originalUiCulture = CultureInfo.CurrentUICulture;
        try
        {
            foreach (var cultureName in new[] { "fi-FI", "th-TH" })
            {
                var culture = CultureInfo.GetCultureInfo(cultureName);
                CultureInfo.CurrentCulture = culture;
                CultureInfo.CurrentUICulture = culture;

                var config = new AppConfig
                {
                    Terminals = new List<TerminalConfig>
                    {
                        new() { StoreId = "STORE-DN1", StoreName = "Hai Chau", PosId = "POS-DN1-01" },
                    },
                    Products = new List<ProductConfig>
                    {
                        new() { Sku = "SKU-001", Name = "Sua", UnitPrice = 25000m },
                    },
                };
                var backend = new MockPosBackend(config, new RequestLog());
                var sale = PosEvents.Sale("STORE-DN1", "POS-DN1-01", new[]
                {
                    new PosEventItem { Sku = "SKU-001", Quantity = 1, UnitPrice = 25000m },
                });
                await backend.SendAsync(PosEventJson.Serialize(sale));

                var entries = GetPrivateField<List<AuditEntry>>(backend, "_audit");
                var entry = Assert.Single(entries);
                Assert.Matches(new Regex(@"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"), entry.CreatedAt);
                var parsed = DateTime.ParseExact(
                    entry.CreatedAt,
                    "yyyy-MM-dd'T'HH:mm:ss'Z'",
                    CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal);
                Assert.Equal(DateTime.UtcNow.Year, parsed.Year);
                var row = Assert.Single(backend.GetAudit());
                Assert.Matches(new Regex(@"^\d{2}:\d{2}:\d{2}$"), row.TimeText);
            }
        }
        finally
        {
            CultureInfo.CurrentCulture = originalCulture;
            CultureInfo.CurrentUICulture = originalUiCulture;
        }
    }

    [Fact]
    public async Task Audit18_ServerCertificateValidatorDisposesSocketOnCancellation()
    {
        var created = new List<System.Net.Sockets.Socket>();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
            await ServerCertificateValidator.ConnectAddressesAsync(
                new[] { IPAddress.Loopback },
                "127.0.0.1",
                1,
                cts.Token,
                family =>
                {
                    var socket = new System.Net.Sockets.Socket(
                        family,
                        System.Net.Sockets.SocketType.Stream,
                        System.Net.Sockets.ProtocolType.Tcp);
                    created.Add(socket);
                    return socket;
                }));

        var leaked = Assert.Single(created);
        Assert.Throws<ObjectDisposedException>(() => _ = leaked.NoDelay);
    }

    [Fact]
    public async Task Audit19_SnapshotNotRewrittenBelowCompactThreshold()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("""{"transaction_id":"TXN-SMALL","event_type":"SALE"}""");

        await queue.DrainAsync(_ => Task.FromResult(new PosResult
        {
            Outcome = PosOutcome.OK,
            Code = "OK",
            Message = "OK",
            HttpStatus = 200,
        }));

        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        var kinds = File.ReadAllLines(path)
            .Select(line => JsonDocument.Parse(line).RootElement.GetProperty("Kind").GetString())
            .ToList();

        Assert.DoesNotContain("snapshot", kinds);
        Assert.Equal(new[] { "enqueue", "settle" }, kinds);
    }

    [Fact]
    public async Task Audit19_CompactsJournalOncePastCompactThreshold()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        var ok = new PosResult { Outcome = PosOutcome.OK, Code = "OK", Message = "OK", HttpStatus = 200 };

        // Pad body (~1.5 KB each) so ~45 settled events cross the 64 KB threshold quickly.
        var padding = new string('x', 1500);
        var compacted = false;
        for (var i = 0; i < 60; i++)
        {
            queue.Enqueue($$"""{"transaction_id":"TXN-{{i}}","event_type":"SALE","pad":"{{padding}}"}""");
            await queue.DrainAsync(_ => Task.FromResult(ok));
            var lines = File.ReadAllLines(path);
            var hasSnapshot = lines.Any(line => JsonDocument.Parse(line).RootElement.GetProperty("Kind").GetString() == "snapshot");
            if (hasSnapshot)
            {
                // Must only compact after accumulating enough events to cross 64 KB (> 30 events of ~1.7 KB).
                Assert.True(i >= 30, $"Compacted too early at event {i}.");
                Assert.True(new FileInfo(path).Length < 4096);
                compacted = true;
                break;
            }
        }

        Assert.True(compacted, "Expected journal to compact once it exceeded 64 KB.");
    }
}
