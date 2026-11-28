using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Text.Json;
using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Services;
using DemoPos.UI;
using Xunit;

namespace DemoPos.Tests;

public sealed class Pb41DemoPosRetryTests
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

    private static void PumpUntil(Func<bool> condition, int timeoutMs = 10000)
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

    private static void ReplaceHttpClient(object target, HttpMessageHandler handler, bool disposeHandler = false)
    {
        var previous = GetPrivateField<HttpClient>(target, "_http");
        var replacement = new HttpClient(handler, disposeHandler)
        {
            Timeout = previous.Timeout,
        };
        foreach (var header in previous.DefaultRequestHeaders.Accept)
        {
            replacement.DefaultRequestHeaders.Accept.Add(header);
        }

        SetPrivateField(target, "_http", replacement);
        previous.Dispose();
    }

    private sealed class StubHttpHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _responder;

        public StubHttpHandler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> responder)
        {
            _responder = responder;
        }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            _responder(request, cancellationToken);
    }

    private static LoadedConfig BuildLiveConfig(string directory)
    {
        using var authority = TestCertificates.CreateAuthority();
        var caPath = Path.Combine(directory, "ca.crt");
        File.WriteAllText(caPath, authority.ExportCertificatePem());

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
                UseMock = false,
                PosBaseUrl = "https://127.0.0.1:19443/api/v1",
                MonitorBaseUrl = "https://127.0.0.1:18443/api/v1",
                Terminals = new List<TerminalConfig>
                {
                    new() { StoreId = "STORE-DN1", StoreName = "Hai Chau", PosId = "POS-DN1-01" },
                    new() { StoreId = "STORE-DN2", StoreName = "Thanh Khe", PosId = "POS-DN2-01" },
                },
                Products = new List<ProductConfig>
                {
                    new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Fresh milk 1L", UnitPrice = 32000m },
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

    private static void PrepareForm(MainForm form)
    {
        GetPrivateField<System.Windows.Forms.Timer>(form, "_monitorTimer").Stop();
        GetPrivateField<System.Windows.Forms.Timer>(form, "_statusTimer").Stop();
        GetPrivateField<System.Windows.Forms.Timer>(form, "_queueTimer").Stop();
        GetPrivateField<System.Windows.Forms.Timer>(form, "_discountTimer").Stop();

        form.DiscountHandlerFactory = _ => new StubHttpHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""{"business_date":"2026-11-27","items":[]}""", Encoding.UTF8, "application/json"),
            }));

        var monitor = GetPrivateField<MonitorApiClient?>(form, "_monitorClient");
        if (monitor is not null)
        {
            ReplaceHttpClient(monitor, new StubHttpHandler((req, _) =>
            {
                var path = req.RequestUri?.AbsolutePath ?? string.Empty;
                var json = path.EndsWith("/health", StringComparison.OrdinalIgnoreCase)
                    ? """{"status":"ok"}"""
                    : path.Contains("/audit-logs", StringComparison.OrdinalIgnoreCase)
                        ? """{"items":[]}"""
                        : """{"store_id":"STORE-DN1","items":[]}""";
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(json, Encoding.UTF8, "application/json"),
                });
            }), disposeHandler: true);
        }

        var gatewayProbe = GetPrivateField<GatewayProbe?>(form, "_gatewayProbe");
        if (gatewayProbe is not null)
        {
            ReplaceHttpClient(gatewayProbe, new StubHttpHandler((_, _) =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.BadRequest)
                {
                    Content = new StringContent("client certificate required", Encoding.UTF8, "text/plain"),
                })), disposeHandler: true);
        }

        form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(-32000, -32000);
        form.Show();
        Application.DoEvents();

        PumpUntil(() =>
            !GetPrivateField<bool>(form, "_statusBusy")
            && !GetPrivateField<bool>(form, "_monitorBusy")
            && !GetPrivateField<bool>(form, "_discountBusy")
            && GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1);
    }

    [Theory]
    [InlineData(ScenarioKind.NoCertificate, "https://127.0.0.1:19443/api/v1", null, 400)]
    [InlineData(ScenarioKind.WrongCertificate, "https://127.0.0.1:19443/api/v1", "POS-DN2-01", 403)]
    [InlineData(ScenarioKind.SkipGateway, "https://127.0.0.1:18443/api/v1", null, 403)]
    public void Pb41_7_RetryingTimedOutF12SecurityScenarioKeepsDirectClientAndNeverQueues(
        ScenarioKind kind, string expectedBaseUrl, string? expectedCertPosId, int retryHttpStatus)
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path);
            using var form = new MainForm(loaded, directory.Path);
            PrepareForm(form);

            // Real terminal's live client would return 200 OK if ever invoked by a buggy fallback.
            var liveCalls = 0;
            using var liveHandler = new StubHttpHandler((_, _) =>
            {
                Interlocked.Increment(ref liveCalls);
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(
                        """{"outcome":"OK","code":"OK","message":"Accepted","current_stock":{"SKU-0001":39}}""",
                        Encoding.UTF8, "application/json"),
                });
            });
            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, liveHandler);

            // Record every direct client created for this F12 scenario: first call times out (CanRetry=true),
            // second call (Retry) returns the expected security rejection (400/403).
            var scenarioCalls = new List<(ScenarioKind Kind, string BaseUrl, bool HasCert, string? CertPosId, string Body)>();
            form.ScenarioHandlerFactory = (scenarioKind, _, baseUrl, cert, certPosId) =>
                new StubHttpHandler(async (req, _) =>
                {
                    var body = await req.Content!.ReadAsStringAsync();
                    int callNumber;
                    lock (scenarioCalls)
                    {
                        scenarioCalls.Add((scenarioKind, baseUrl, cert is not null, certPosId, body));
                        callNumber = scenarioCalls.Count;
                    }

                    if (callNumber == 1)
                    {
                        throw new HttpRequestException("Simulated timeout/network drop on first F12 send.");
                    }

                    return new HttpResponseMessage((HttpStatusCode)retryHttpStatus)
                    {
                        Content = new StringContent(
                            """{"outcome":"REJECTED","code":"SECURITY_REJECTED","message":"Rejected as expected"}""",
                            Encoding.UTF8, "application/json"),
                    };
                });

            var scenarioTask = (Task)InvokePrivate(form, "RunScenarioAsync", kind)!;
            PumpUntil(() => scenarioTask.IsCompleted);
            scenarioTask.GetAwaiter().GetResult();

            Assert.True(form.Result.RetryVisible);
            Assert.Single(scenarioCalls);

            // Trigger Retry: must re-use the scenario's direct client settings and NEVER touch the queue or live client.
            var retryTask = (Task)InvokePrivate(form, "RetryAsync")!;
            PumpUntil(() => retryTask.IsCompleted);
            retryTask.GetAwaiter().GetResult();
            PumpUntil(() => GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1);

            Assert.Equal(0, Volatile.Read(ref liveCalls));
            Assert.Equal(0, form.HistoryCount);
            Assert.Equal(2, scenarioCalls.Count);
            Assert.All(scenarioCalls, call =>
            {
                Assert.Equal(kind, call.Kind);
                Assert.Equal(expectedBaseUrl, call.BaseUrl);
                Assert.Equal(expectedCertPosId, call.CertPosId);
                Assert.Equal(expectedCertPosId is not null, call.HasCert);
            });
            Assert.Equal(scenarioCalls[0].Body, scenarioCalls[1].Body);
            Assert.False(form.Result.RetryVisible);

            var queue = new DurableEventQueue(directory.Path, "POS-DN1-01");
            Assert.Equal(0, queue.Count);
            Assert.Empty(queue.Rejected);
            var journalPath = Path.Combine(directory.Path, "POS-DN1-01.jsonl");
            var journalLines = File.Exists(journalPath) ? File.ReadAllLines(journalPath) : Array.Empty<string>();
            Assert.Empty(journalLines);
        });
    }

    [Fact]
    public void Pb41_7_RetryingTimedOutF12FailureScenarioNeverEnqueuesOrAddsHistory()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path);
            using var form = new MainForm(loaded, directory.Path);
            PrepareForm(form);

            var calls = 0;
            using var liveHandler = new StubHttpHandler((_, _) =>
            {
                var attempt = Interlocked.Increment(ref calls);
                if (attempt == 1)
                {
                    return Task.FromResult(new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                    {
                        Content = new StringContent(
                            """{"outcome":"ERROR","code":"SERVICE_UNAVAILABLE","message":"Restarting"}""",
                            Encoding.UTF8, "application/json"),
                    });
                }

                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.UnprocessableEntity)
                {
                    Content = new StringContent(
                        """{"outcome":"REJECTED","code":"INSUFFICIENT_STOCK","message":"Not enough stock"}""",
                        Encoding.UTF8, "application/json"),
                });
            });
            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, liveHandler);

            var scenarioTask = (Task)InvokePrivate(form, "RunScenarioAsync", ScenarioKind.InsufficientStock)!;
            PumpUntil(() => scenarioTask.IsCompleted);
            scenarioTask.GetAwaiter().GetResult();
            Assert.True(form.Result.RetryVisible);

            var retryTask = (Task)InvokePrivate(form, "RetryAsync")!;
            PumpUntil(() => retryTask.IsCompleted);
            retryTask.GetAwaiter().GetResult();
            PumpUntil(() => GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1);

            Assert.Equal(2, calls);
            Assert.Equal(0, form.HistoryCount);

            var queue = new DurableEventQueue(directory.Path, "POS-DN1-01");
            Assert.Equal(0, queue.Count);
            Assert.Empty(queue.Rejected);
            var journalPath = Path.Combine(directory.Path, "POS-DN1-01.jsonl");
            var journalLines = File.Exists(journalPath) ? File.ReadAllLines(journalPath) : Array.Empty<string>();
            Assert.Empty(journalLines);
        });
    }

    [Fact]
    public void Pb41_7_SwitchingToMockClearsPendingF12Retry()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path);
            using var form = new MainForm(loaded, directory.Path);
            PrepareForm(form);

            form.ScenarioHandlerFactory = (_, _, _, _, _) =>
                new StubHttpHandler((_, _) => throw new HttpRequestException("Simulated drop"));

            var scenarioTask = (Task)InvokePrivate(form, "RunScenarioAsync", ScenarioKind.NoCertificate)!;
            PumpUntil(() => scenarioTask.IsCompleted);
            scenarioTask.GetAwaiter().GetResult();
            Assert.True(form.Result.RetryVisible);

            var toggleTask = form.ToggleMockAsync();
            PumpUntil(() => toggleTask.IsCompleted);
            toggleTask.GetAwaiter().GetResult();
            Assert.True(form.IsMockMode);
            Assert.False(form.Result.RetryVisible);

            // Invoking Retry after switching to MOCK must report no pending request and never enqueue.
            var retryTask = (Task)InvokePrivate(form, "RetryAsync")!;
            PumpUntil(() => retryTask.IsCompleted);
            retryTask.GetAwaiter().GetResult();

            var messageLabel = GetPrivateField<Label>(form.Result, "_message");
            Assert.Contains("thử lại", messageLabel.Text, StringComparison.OrdinalIgnoreCase);
            Assert.Equal(0, new DurableEventQueue(directory.Path, "POS-DN1-01").Count);
        });
    }

    [Fact]
    public void Pb41_7_SwitchingToMockMidDrainStopsBeforeNextQueuedItem()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildLiveConfig(directory.Path);
            using var form = new MainForm(loaded, directory.Path);
            PrepareForm(form);

            var firstStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var firstRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            var sentBodies = new List<string>();
            using var liveHandler = new StubHttpHandler(async (req, _) =>
            {
                var body = await req.Content!.ReadAsStringAsync();
                lock (sentBodies)
                {
                    sentBodies.Add(body);
                }

                if (body.Contains("TXN-1", StringComparison.Ordinal))
                {
                    firstStarted.TrySetResult(true);
                    return await firstRelease.Task;
                }

                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(
                        """{"outcome":"OK","code":"OK","message":"Accepted"}""",
                        Encoding.UTF8, "application/json"),
                };
            });

            var authority = GetPrivateField<X509Certificate2>(form, "_authority");
            var liveClients = GetPrivateField<Dictionary<string, TerminalClient>>(form, "_liveClients");
            liveClients["POS-DN1-01"] = new TerminalClient(
                loaded.Config.PosBaseUrl, authority, null, "POS-DN1-01", "token-pos-1", form.RequestLog, liveHandler);

            var queues = GetPrivateField<Dictionary<string, DurableEventQueue>>(form, "_queues");
            queues["POS-DN1-01"].Enqueue("""{"transaction_id":"TXN-1","event_type":"SALE"}""");
            queues["POS-DN1-01"].Enqueue("""{"transaction_id":"TXN-2","event_type":"SALE"}""");
            queues["POS-DN1-01"].Enqueue("""{"transaction_id":"TXN-3","event_type":"SALE"}""");

            var terminalA = loaded.Config.Terminals[0];
            var drainTask = (Task)InvokePrivate(form, "DrainTerminalAsync", terminalA)!;
            PumpUntil(() => firstStarted.Task.IsCompleted);

            // Switch to MOCK while TXN-1 is in flight.
            var toggleTask = form.ToggleMockAsync();
            PumpUntil(() => toggleTask.IsCompleted);
            toggleTask.GetAwaiter().GetResult();
            Assert.True(form.IsMockMode);

            // Finish the already-in-flight TXN-1.
            firstRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"outcome":"OK","code":"OK","message":"Accepted"}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => drainTask.IsCompleted);
            drainTask.GetAwaiter().GetResult();
            PumpUntil(() => GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1);

            // Only TXN-1 (already in flight before switch) was sent; TXN-2 and TXN-3 must remain queued.
            Assert.Single(sentBodies);
            Assert.Contains("TXN-1", sentBodies[0], StringComparison.Ordinal);
            Assert.Equal(2, queues["POS-DN1-01"].Count);

            // Existing #73 stale-result check stays intact: MOCK's INFO banner is not overwritten.
            var outcomeLabel = GetPrivateField<Label>(form.Result, "_outcome");
            Assert.Equal("Thông báo", outcomeLabel.Text);

            // Switching back to LIVE and draining sends TXN-2 and TXN-3 in order.
            var backToLive = form.ToggleMockAsync();
            PumpUntil(() => backToLive.IsCompleted);
            backToLive.GetAwaiter().GetResult();
            Assert.False(form.IsMockMode);

            var resumeDrain = (Task)InvokePrivate(form, "DrainTerminalAsync", terminalA)!;
            PumpUntil(() => resumeDrain.IsCompleted);
            resumeDrain.GetAwaiter().GetResult();
            PumpUntil(() => GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1);

            Assert.Equal(3, sentBodies.Count);
            Assert.Contains("TXN-2", sentBodies[1], StringComparison.Ordinal);
            Assert.Contains("TXN-3", sentBodies[2], StringComparison.Ordinal);
            Assert.Equal(0, queues["POS-DN1-01"].Count);
        });
    }
}
