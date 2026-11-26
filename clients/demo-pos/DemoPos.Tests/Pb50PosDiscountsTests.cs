using System.Globalization;
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

public sealed class Pb50PosDiscountsTests
{
    private static readonly DateTime FixedUtc = new(2026, 11, 23, 7, 35, 0, DateTimeKind.Utc);
    private static readonly DateTime FixedLocal = new(2026, 11, 23, 14, 35, 0, DateTimeKind.Local);
    private static readonly DateOnly FixedBusinessDate = new(2026, 11, 23);

    private sealed record CachedPems(string CaPem, string ClientCertPem, string ClientKeyPem);

    private static readonly Lazy<CachedPems> SharedPems = new(() =>
    {
        using var authority = TestCertificates.CreateAuthority();
        using var cert = TestCertificates.CreateClientCertificate(authority, "POS-DN1-01");
        using var key = cert.GetRSAPrivateKey()!;
        return new CachedPems(
            authority.ExportCertificatePem(),
            cert.ExportCertificatePem(),
            key.ExportPkcs8PrivateKeyPem());
    });

    private static readonly Lazy<CachedPems> SharedSecondTerminalPems = new(() =>
    {
        using var authority = TestCertificates.CreateAuthority();
        using var cert1 = TestCertificates.CreateClientCertificate(authority, "POS-DN1-01");
        using var key1 = cert1.GetRSAPrivateKey()!;
        using var cert2 = TestCertificates.CreateClientCertificate(authority, "POS-DN2-01");
        using var key2 = cert2.GetRSAPrivateKey()!;
        return new CachedPems(
            authority.ExportCertificatePem(),
            cert1.ExportCertificatePem() + "\n---SECOND---\n" + cert2.ExportCertificatePem(),
            key1.ExportPkcs8PrivateKeyPem() + "\n---SECOND---\n" + key2.ExportPkcs8PrivateKeyPem());
    });

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

    private static StubHttpHandler CreateMonitorStub() =>
        new((req, _) =>
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
        });

    private static StubHttpHandler CreateGatewayProbeStub() =>
        new((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.BadRequest)
        {
            Content = new StringContent("client certificate required", Encoding.UTF8, "text/plain"),
        }));

    private static void StopBackgroundTimers(MainForm form)
    {
        foreach (var timerName in new[] { "_monitorTimer", "_statusTimer", "_queueTimer", "_discountTimer" })
        {
            var field = form.GetType().GetField(timerName, BindingFlags.Instance | BindingFlags.NonPublic);
            if (field?.GetValue(form) is System.Windows.Forms.Timer timer)
            {
                timer.Stop();
            }
        }
    }

    private static bool IsFormIdle(MainForm form)
    {
        var discountBusyField = form.GetType().GetField("_discountBusy", BindingFlags.Instance | BindingFlags.NonPublic);
        var discountPendingField = form.GetType().GetField("_discountRefreshPending", BindingFlags.Instance | BindingFlags.NonPublic);
        var discountBusy = discountBusyField?.GetValue(form) as bool? ?? false;
        var discountPending = discountPendingField?.GetValue(form) as bool? ?? false;
        return !GetPrivateField<bool>(form, "_statusBusy")
               && !GetPrivateField<bool>(form, "_statusRefreshPending")
               && !GetPrivateField<bool>(form, "_monitorBusy")
               && !GetPrivateField<bool>(form, "_monitorRefreshPending")
               && !discountBusy
               && !discountPending
               && GetPrivateField<SemaphoreSlim>(form, "_queueGate").CurrentCount == 1;
    }

    private static StubHttpHandler CreateOfflineStub(string message = "Connection refused") =>
        new((_, _) => Task.FromException<HttpResponseMessage>(new HttpRequestException(message)));

    private static void ShowFormDeterministically(MainForm form, Func<TerminalConfig, HttpMessageHandler>? discountFactory = null,
                                                  bool offline = false)
    {
        StopBackgroundTimers(form);
        if (discountFactory is not null)
        {
            form.DiscountHandlerFactory = discountFactory;
        }

        if (!form.IsMockMode)
        {
            var monitor = GetPrivateField<MonitorApiClient?>(form, "_monitorClient");
            if (monitor is not null)
            {
                ReplaceHttpClient(monitor, offline ? CreateOfflineStub() : CreateMonitorStub(), disposeHandler: true);
            }

            var probe = GetPrivateField<GatewayProbe?>(form, "_gatewayProbe");
            if (probe is not null)
            {
                ReplaceHttpClient(probe, offline ? CreateOfflineStub() : CreateGatewayProbeStub(), disposeHandler: true);
            }
        }

        form.ShowInTaskbar = false;
        form.StartPosition = FormStartPosition.Manual;
        form.Location = new Point(-32000, -32000);
        form.Show();
        PumpUntil(() => IsFormIdle(form));
    }

    private static LoadedConfig BuildConfig(string directory, bool mock,
                                            string posBaseUrl = "https://127.0.0.1:19443/api/v1",
                                            string storeId = "STORE-DN1",
                                            bool includeSecondTerminal = false)
    {
        var caPath = Path.Combine(directory, "ca.crt");
        if (includeSecondTerminal)
        {
            var pair = SharedSecondTerminalPems.Value;
            var certs = pair.ClientCertPem.Split("\n---SECOND---\n");
            var keys = pair.ClientKeyPem.Split("\n---SECOND---\n");
            File.WriteAllText(caPath, pair.CaPem);
            File.WriteAllText(Path.Combine(directory, "POS-DN1-01.crt"), certs[0]);
            File.WriteAllText(Path.Combine(directory, "POS-DN1-01.key"), keys[0]);
            File.WriteAllText(Path.Combine(directory, "POS-DN2-01.crt"), certs[1]);
            File.WriteAllText(Path.Combine(directory, "POS-DN2-01.key"), keys[1]);
        }
        else
        {
            var pems = SharedPems.Value;
            File.WriteAllText(caPath, pems.CaPem);
            File.WriteAllText(Path.Combine(directory, "POS-DN1-01.crt"), pems.ClientCertPem);
            File.WriteAllText(Path.Combine(directory, "POS-DN1-01.key"), pems.ClientKeyPem);
        }

        static string MakePosJwt(string sid, string pid)
        {
            var payload = Convert.ToBase64String(Encoding.UTF8.GetBytes(
                    $"{{\"sub\":\"pos_system\",\"role\":\"POS\",\"store_id\":\"{sid}\",\"pos_id\":\"{pid}\"}}"))
                .TrimEnd('=').Replace('+', '-').Replace('/', '_');
            return $"header.{payload}.sig";
        }

        var tokensPath = Path.Combine(directory, "tokens.json");
        var tokens = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["POS-DN1-01"] = MakePosJwt(storeId, "POS-DN1-01"),
            ["staff_dn1"] = "token-staff-1",
        };
        var terminals = new List<TerminalConfig>
        {
            new() { StoreId = storeId, StoreName = "Cửa hàng Hải Châu", PosId = "POS-DN1-01" },
        };
        if (includeSecondTerminal)
        {
            tokens["POS-DN2-01"] = MakePosJwt("STORE-DN2", "POS-DN2-01");
            terminals.Add(new TerminalConfig { StoreId = "STORE-DN2", StoreName = "Cửa hàng Thanh Khê", PosId = "POS-DN2-01" });
        }

        File.WriteAllText(tokensPath, JsonSerializer.Serialize(tokens));

        return new LoadedConfig
        {
            Config = new AppConfig
            {
                UseMock = mock,
                PosBaseUrl = posBaseUrl,
                MonitorBaseUrl = "https://127.0.0.1:18443/api/v1",
                Terminals = terminals,
                Products = new List<ProductConfig>
                {
                    new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Fresh milk 1L", UnitPrice = 32000m },
                    new() { Sku = "SKU-0002", Barcode = "8930000000028", Name = "Yogurt 100g", UnitPrice = 7000m },
                    new() { Sku = "SKU-0003", Barcode = "8930000000035", Name = "Bread 400g", UnitPrice = 25000m },
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

        public List<Uri?> RequestedUris { get; } = new();
        public List<HttpMethod> Methods { get; } = new();
        public List<string?> AuthHeaders { get; } = new();

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            RequestedUris.Add(request.RequestUri);
            Methods.Add(request.Method);
            AuthHeaders.Add(request.Headers.Authorization?.ToString());
            return _responder(request, cancellationToken);
        }
    }

    // 1. JSON parsing with CultureInfo.InvariantCulture + price lookup

    [Theory]
    [InlineData("en-US")]
    [InlineData("vi-VN")]
    [InlineData("de-DE")]
    public void Pb50_ParsesDiscountJsonWithInvariantCultureAcrossLocales(string cultureName)
    {
        var previous = CultureInfo.CurrentCulture;
        try
        {
            CultureInfo.CurrentCulture = new CultureInfo(cultureName);
            const string json = """
                {
                  "business_date": "2026-11-24",
                  "items": [
                    {"sku": "SKU-0001", "discount_pct": 30.00, "discounted_price": 22400.00},
                    {"sku": "SKU-0002", "discount_pct": 15.5, "discounted_price": 5900}
                  ]
                }
                """;

            var ok = PosDiscounts.TryParse(json, out var list, out var error);

            Assert.True(ok, error);
            Assert.NotNull(list);
            Assert.Equal(new DateOnly(2026, 11, 24), list!.BusinessDate);
            Assert.Equal(2, list.Items.Count);
            Assert.Equal(("SKU-0001", 30.00m, 22400.00m),
                (list.Items[0].Sku, list.Items[0].DiscountPct, list.Items[0].DiscountedPrice));
            Assert.Equal(("SKU-0002", 15.5m, 5900m),
                (list.Items[1].Sku, list.Items[1].DiscountPct, list.Items[1].DiscountedPrice));
        }
        finally
        {
            CultureInfo.CurrentCulture = previous;
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData("not-json")]
    [InlineData("""{"items":[]}""")]
    [InlineData("""{"business_date":"24-11-2026","items":[]}""")]
    [InlineData("""{"business_date":"2026-11-24","items":[{"sku":"","discount_pct":10,"discounted_price":1000}]}""")]
    [InlineData("""{"business_date":"2026-11-24","items":[{"sku":"SKU-1","discount_pct":120,"discounted_price":1000}]}""")]
    [InlineData("""{"business_date":"2026-11-24","items":[{"sku":"SKU-1","discount_pct":10,"discounted_price":-100}]}""")]
    public void Pb50_RejectsMalformedDiscountResponses(string raw)
    {
        Assert.False(PosDiscounts.TryParse(raw, out var list, out var error));
        Assert.Null(list);
        Assert.False(string.IsNullOrWhiteSpace(error));
    }

    [Fact]
    public void Pb50_DiscountBookUsesMiddlewareDiscountedPriceVerbatimAndListPriceOtherwise()
    {
        var milk = new ProductConfig { Sku = "SKU-0001", Name = "Milk", UnitPrice = 32000m };
        var yogurt = new ProductConfig { Sku = "SKU-0002", Name = "Yogurt", UnitPrice = 7000m };
        var book = new PosDiscountBook();

        // Deliberately pass 21900 (not 32000 * 0.7 = 22400) to prove POS never recalculates from discount_pct.
        book.ApplySuccess(
            new PosDiscountList(FixedBusinessDate, new[]
            {
                new PosDiscountItem("SKU-0001", 30m, 21900m),
            }),
            FixedUtc,
            FixedLocal);

        Assert.Equal(21900m, book.PriceFor(milk, FixedUtc));
        Assert.Equal(7000m, book.PriceFor(yogurt, FixedUtc));
    }

    // 2. HTTP client contract, failure retention (network/5xx/timeout/401/403), and UTC+7 rollover

    [Fact]
    public async Task Pb50_PosDiscountClientCallsGatewayWithoutStoreIdAndLogsAuthFailuresWithoutTokenLeak()
    {
        using var authority = TestCertificates.CreateAuthority();
        var log = new RequestLog();
        var payload = Convert.ToBase64String(Encoding.UTF8.GetBytes("""{"sub":"pos_system","role":"POS"}"""))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');
        var secretToken = $"hdr.{payload}.secret-sig";

        var call = 0;
        using var handler = new StubHttpHandler((_, _) =>
        {
            call++;
            if (call == 1)
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(
                        """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                        Encoding.UTF8, "application/json"),
                });
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.Forbidden)
            {
                Content = new StringContent(
                    """{"outcome":"REJECTED","code":"FORBIDDEN","message":"Certificate mismatch."}""",
                    Encoding.UTF8, "application/json"),
            });
        });

        using var client = new PosDiscountClient(
            "https://localhost:9443/api/v1/", authority, null, "POS-DN1-01", secretToken, log, handler);

        Assert.Equal("https://localhost:9443/api/v1/pos/discounts", client.DiscountsUrl);

        var ok = await client.FetchAsync();
        Assert.True(ok.IsSuccess);
        Assert.Single(ok.Data!.Items);

        var forbidden = await client.FetchAsync();
        Assert.False(forbidden.IsSuccess);
        Assert.Equal(403, forbidden.HttpStatus);

        Assert.All(handler.RequestedUris, uri =>
        {
            Assert.Equal("https://localhost:9443/api/v1/pos/discounts", uri!.ToString());
            Assert.Equal(string.Empty, uri.Query);
        });
        Assert.All(handler.Methods, method => Assert.Equal(HttpMethod.Get, method));
        Assert.All(handler.AuthHeaders, auth => Assert.Equal($"Bearer {secretToken}", auth));

        var entries = log.Snapshot();
        Assert.Equal(2, entries.Count);
        Assert.Equal(403, entries[0].Status);
        Assert.Equal("POS-DN1-01", entries[0].CertificatePosId);
        Assert.Equal("POS", entries[0].Role);
        Assert.DoesNotContain(secretToken, entries[0].DetailsText);
    }

    [Fact]
    public void Pb50_FetchFailuresKeepLastListAndShowUpdatedAtTimeOnStatusBar()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);
            var step = 0;
            using var discountHandler = new StubHttpHandler((_, _) =>
            {
                step++;
                return step switch
                {
                    1 => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                    {
                        Content = new StringContent(
                            """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30.0,"discounted_price":22400.0}]}""",
                            Encoding.UTF8, "application/json"),
                    }),
                    2 => Task.FromException<HttpResponseMessage>(new HttpRequestException("Connection refused")),
                    3 => Task.FromResult(new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                    {
                        Content = new StringContent("""{"code":"SERVICE_UNAVAILABLE"}""", Encoding.UTF8, "application/json"),
                    }),
                    4 => Task.FromException<HttpResponseMessage>(new TaskCanceledException("Simulated timeout")),
                    5 => Task.FromResult(new HttpResponseMessage(HttpStatusCode.Unauthorized)
                    {
                        Content = new StringContent("""{"code":"UNAUTHORIZED"}""", Encoding.UTF8, "application/json"),
                    }),
                    _ => Task.FromResult(new HttpResponseMessage(HttpStatusCode.Forbidden)
                    {
                        Content = new StringContent("""{"code":"FORBIDDEN"}""", Encoding.UTF8, "application/json"),
                    }),
                };
            });

            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form, _ => discountHandler);

            // Step 1 happened on startup (14:35 local): SKU-0001 is discounted at 22,400.
            Assert.Equal(1, step);
            form.AddProductToCart("SKU-0001", 1);
            Assert.Equal(22400m, Assert.Single(form.CartItems).UnitPrice);
            InvokePrivate(form, "ClearCart");

            // Steps 2..6: network error, 503, timeout, 401, 403 -> all keep the 22,400 discount and show "Giảm giá: cập nhật lúc 14:35".
            for (var expectedStep = 2; expectedStep <= 6; expectedStep++)
            {
                var refresh = form.RefreshDiscountsAsync();
                PumpUntil(() => refresh.IsCompleted && IsFormIdle(form));
                refresh.GetAwaiter().GetResult();

                Assert.Equal(expectedStep, step);
                Assert.Equal("Giảm giá: cập nhật lúc 14:35", form.DiscountStatusText);

                form.AddProductToCart("SKU-0001", 1);
                Assert.Equal(22400m, Assert.Single(form.CartItems).UnitPrice);
                InvokePrivate(form, "ClearCart");
            }

            // Confirm 401 and 403 were logged in RequestLog.
            var statuses = form.RequestLog.Snapshot()
                .Where(entry => entry.Url.EndsWith("/pos/discounts", StringComparison.OrdinalIgnoreCase))
                .Select(entry => entry.Status)
                .ToList();
            Assert.Contains(401, statuses);
            Assert.Contains(403, statuses);
        });
    }

    [Fact]
    public void Pb50_ListFromYesterdayInUtcPlus7IsDroppedAndRevertsToListPrice()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);
            // 2026-11-23 16:59:30 UTC == 2026-11-23 23:59:30 UTC+7 (still 23 Nov business date)
            var currentUtc = new DateTime(2026, 11, 23, 16, 59, 30, DateTimeKind.Utc);
            var currentLocal = new DateTime(2026, 11, 23, 23, 59, 30, DateTimeKind.Local);

            var call = 0;
            using var discountHandler = new StubHttpHandler((_, _) =>
            {
                call++;
                if (call == 1)
                {
                    return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                    {
                        Content = new StringContent(
                            """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                            Encoding.UTF8, "application/json"),
                    });
                }

                return Task.FromException<HttpResponseMessage>(new HttpRequestException("Middleware offline at midnight"));
            });

            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => currentUtc,
                LocalClock = () => currentLocal,
            };
            ShowFormDeterministically(form, _ => discountHandler);

            form.AddProductToCart("SKU-0001", 1);
            Assert.Equal(22400m, Assert.Single(form.CartItems).UnitPrice);
            InvokePrivate(form, "ClearCart");

            // Cross midnight UTC+7: 2026-11-23 17:00:05 UTC == 2026-11-24 00:00:05 UTC+7!
            currentUtc = new DateTime(2026, 11, 23, 17, 0, 5, DateTimeKind.Utc);
            currentLocal = new DateTime(2026, 11, 24, 0, 0, 5, DateTimeKind.Local);

            // Even BEFORE any network poll, adding to cart immediately drops yesterday's discount and uses list price 32,000.
            form.AddProductToCart("SKU-0001", 1);
            Assert.Equal(32000m, Assert.Single(form.CartItems).UnitPrice);
            InvokePrivate(form, "ClearCart");

            // And if a fetch also fails after midnight, yesterday's list stays dropped.
            var refresh = form.RefreshDiscountsAsync();
            PumpUntil(() => refresh.IsCompleted && IsFormIdle(form));
            refresh.GetAwaiter().GetResult();
            Assert.DoesNotContain("23:59", form.DiscountStatusText);
        });
    }

    // 3. UI Strikeout in ProductGrid & CartGrid + MockBackend + Normal SALE contract

    [Fact]
    public void Pb50_MockBackendDefaultsEmptyAndShowsStrikeoutPricesInProductAndCartGrids()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: true);
            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form);

            // Default MockPosBackend discount list is empty for today's UTC+7 business date.
            var defaultList = form.MockBackend.GetDiscounts("STORE-DN1", FixedUtc);
            Assert.Equal(FixedBusinessDate, defaultList.BusinessDate);
            Assert.Empty(defaultList.Items);

            // Configure a discount on SKU-0001 (32,000 -> 22,400 at 30%), leave SKU-0002 undiscounted.
            form.MockBackend.SetDiscounts("STORE-DN1", new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) }));
            var refresh = form.RefreshDiscountsAsync();
            PumpUntil(() => refresh.IsCompleted && IsFormIdle(form));
            refresh.GetAwaiter().GetResult();

            // Check ProductGrid: SKU-0001 has struck-through original price and 22,400 discounted price.
            var origCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .FirstOrDefault(col => col.DataPropertyName == nameof(ProductRow.OriginalPriceText));
            Assert.NotNull(origCol);
            var priceCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.UnitPriceText));

            var milkRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
            var yogurtRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0002");

            Assert.Equal(32000m.ToString("N0"), milkRow.Cells[origCol!.Index].Value?.ToString());
            Assert.NotNull(milkRow.Cells[origCol.Index].Style.Font);
            Assert.True(milkRow.Cells[origCol.Index].Style.Font!.Strikeout);
            Assert.Contains(22400m.ToString("N0"), milkRow.Cells[priceCol.Index].Value?.ToString());

            Assert.Equal(string.Empty, yogurtRow.Cells[origCol.Index].Value?.ToString());
            Assert.False(yogurtRow.Cells[origCol.Index].Style.Font?.Strikeout ?? false);

            // Add both to Cart and check CartGrid strikeout + unit prices.
            form.AddProductToCart("SKU-0001", 2);
            form.AddProductToCart("SKU-0002", 1);

            var cartOrigCol = form.CartGrid.Columns.Cast<DataGridViewColumn>()
                .FirstOrDefault(col => col.DataPropertyName == nameof(CartItem.ListPriceText));
            Assert.NotNull(cartOrigCol);

            var cartMilkRow = form.CartGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((CartItem)row.DataBoundItem!).Sku == "SKU-0001");
            var cartYogurtRow = form.CartGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((CartItem)row.DataBoundItem!).Sku == "SKU-0002");

            Assert.Equal(32000m.ToString("N0"), cartMilkRow.Cells[cartOrigCol!.Index].Value?.ToString());
            Assert.NotNull(cartMilkRow.Cells[cartOrigCol.Index].Style.Font);
            Assert.True(cartMilkRow.Cells[cartOrigCol.Index].Style.Font!.Strikeout);
            Assert.Equal(22400m, ((CartItem)cartMilkRow.DataBoundItem!).UnitPrice);
            Assert.Equal(44800m, ((CartItem)cartMilkRow.DataBoundItem!).LineTotal);

            Assert.Equal(string.Empty, cartYogurtRow.Cells[cartOrigCol.Index].Value?.ToString());
            Assert.False(cartYogurtRow.Cells[cartOrigCol.Index].Style.Font?.Strikeout ?? false);
            Assert.Equal(7000m, ((CartItem)cartYogurtRow.DataBoundItem!).UnitPrice);

            // Pay sends a standard SALE event with discounted unit_price 22400 and list price 7000.
            var pay = form.PayAsync();
            PumpUntil(() => pay.IsCompleted);
            var payResult = pay.GetAwaiter().GetResult();
            Assert.Equal(PosOutcome.OK, payResult.Outcome);

            var sentSale = PosEventJson.Deserialize(form.CurrentHistory[0].RawBody);
            Assert.Equal(EventTypes.Sale, sentSale.EventType);
            Assert.Equal(22400m, sentSale.Items!.Single(i => i.Sku == "SKU-0001").UnitPrice);
            Assert.Equal(7000m, sentSale.Items!.Single(i => i.Sku == "SKU-0002").UnitPrice);
        });
    }

    [Fact]
    public void Pb50_ProductGridPriceColumnFitsDiscountTextAtDefaultWindowSize()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: true);
            // Match the 9-product demo catalogue so the vertical scrollbar is present just like live runs.
            loaded.Config.Products.AddRange(new[]
            {
                new ProductConfig { Sku = "SKU-0004", Barcode = "8930000000042", Name = "Cheese slices 200g", UnitPrice = 65000m },
                new ProductConfig { Sku = "SKU-0005", Barcode = "8930000000059", Name = "Sponge cake 300g", UnitPrice = 45000m },
                new ProductConfig { Sku = "SKU-0006", Barcode = "8930000000066", Name = "Butter cookies 200g", UnitPrice = 38000m },
                new ProductConfig { Sku = "SKU-0007", Barcode = "8930000000073", Name = "Rice 5kg", UnitPrice = 120000m },
                new ProductConfig { Sku = "SKU-0008", Barcode = "8930000000080", Name = "Instant noodles 75g", UnitPrice = 4500m },
                new ProductConfig { Sku = "SKU-0009", Barcode = "8930000000097", Name = "Cooking oil 1L", UnitPrice = 58000m },
            });

            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form);

            form.MockBackend.SetDiscounts("STORE-DN1", new PosDiscountList(
                FixedBusinessDate,
                new[]
                {
                    new PosDiscountItem("SKU-0001", 30m, 22400m),
                    new PosDiscountItem("SKU-0007", 30m, 84000m),
                }));
            var refresh = form.RefreshDiscountsAsync();
            PumpUntil(() => refresh.IsCompleted && IsFormIdle(form));
            refresh.GetAwaiter().GetResult();

            var skuCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.Sku));
            var nameCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.Name));
            var barcodeCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.Barcode));
            var origCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.OriginalPriceText));
            var priceCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.UnitPriceText));

            var milkRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
            var cookieRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0006");
            var riceRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0007");

            // At default 1420x900 (with 125% PerMonitorV2 DPI headroom where fonts scale by 1.25x
            // while fixed pixel window size stays 1420px), "22,400 (-30%)" and "84,000 (-30%)" must fit without ellipsis.
            var dpiScale = form.DeviceDpi > 96 ? 1.0 : 1.25;
            var neededMilkPrice = (int)Math.Ceiling(milkRow.Cells[priceCol.Index].PreferredSize.Width * dpiScale);
            var neededRicePrice = (int)Math.Ceiling(riceRow.Cells[priceCol.Index].PreferredSize.Width * dpiScale);
            Assert.True(priceCol.Width >= neededMilkPrice,
                $"Giá column width {priceCol.Width}px is narrower than {neededMilkPrice}px needed for '{milkRow.Cells[priceCol.Index].FormattedValue}'.");
            Assert.True(priceCol.Width >= neededRicePrice,
                $"Giá column width {priceCol.Width}px is narrower than {neededRicePrice}px needed for '{riceRow.Cells[priceCol.Index].FormattedValue}'.");
            Assert.True(skuCol.Width >= cookieRow.Cells[skuCol.Index].PreferredSize.Width,
                $"SKU column width {skuCol.Width}px < preferred {cookieRow.Cells[skuCol.Index].PreferredSize.Width}px.");
            Assert.True(nameCol.Width >= cookieRow.Cells[nameCol.Index].PreferredSize.Width,
                $"Tên column width {nameCol.Width}px < preferred {cookieRow.Cells[nameCol.Index].PreferredSize.Width}px.");
            Assert.True(barcodeCol.Width >= cookieRow.Cells[barcodeCol.Index].PreferredSize.Width,
                $"Barcode column width {barcodeCol.Width}px < preferred {cookieRow.Cells[barcodeCol.Index].PreferredSize.Width}px.");
            Assert.True(origCol.Width >= riceRow.Cells[origCol.Index].PreferredSize.Width,
                $"Giá gốc column width {origCol.Width}px < preferred {riceRow.Cells[origCol.Index].PreferredSize.Width}px.");
        });
    }

    // 4. RETURN and CANCELLATION preserve original sale unit_price

    [Fact]
    public void Pb50_ReturnUsesDiscountedSalePriceEvenAfterDiscountEndsAndListPriceEvenAfterDiscountStarts()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: true);
            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form);

            // Sale 1: sell SKU-0001 at FULL list price (32,000) before any discount exists.
            form.AddProductToCart("SKU-0001", 1);
            var payFull = form.PayAsync();
            PumpUntil(() => payFull.IsCompleted);
            Assert.Equal(PosOutcome.OK, payFull.GetAwaiter().GetResult().Outcome);
            var fullPriceSaleId = form.CurrentHistory[0].TransactionId;

            // Now activate a 30% discount (22,400) on SKU-0001.
            form.MockBackend.SetDiscounts(new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) }));
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();

            // Return of Sale 1 (which was sold at 32,000) while 22,400 discount is active MUST still send 32,000!
            SelectHistoryByTxnId(form, fullPriceSaleId);
            form.ReturnPrompt = _ => (true, "SKU-0001", 1);
            var returnFull = (Task)InvokePrivate(form, "ReturnAsync")!;
            PumpUntil(() => returnFull.IsCompleted);
            returnFull.GetAwaiter().GetResult();

            var returnFullEvent = PosEventJson.Deserialize(form.CurrentHistory[0].RawBody);
            Assert.Equal(EventTypes.Return, returnFullEvent.EventType);
            Assert.Equal(fullPriceSaleId, returnFullEvent.OriginalTransactionId);
            Assert.Equal(32000m, Assert.Single(returnFullEvent.Items!).UnitPrice);

            // Sale 2: sell SKU-0001 at DISCOUNTED price (22,400).
            form.AddProductToCart("SKU-0001", 2);
            var payDisc = form.PayAsync();
            PumpUntil(() => payDisc.IsCompleted);
            Assert.Equal(PosOutcome.OK, payDisc.GetAwaiter().GetResult().Outcome);
            var discountedSaleId = form.CurrentHistory[0].TransactionId;

            // Clear discounts (discount ended) so current price is back to 32,000.
            form.MockBackend.ClearDiscounts();
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();

            // Return 1 unit of Sale 2 MUST still send 22,400 (from original TxnRecord), NOT 32,000!
            SelectHistoryByTxnId(form, discountedSaleId);
            form.ReturnPrompt = _ => (true, "SKU-0001", 1);
            var returnDisc = (Task)InvokePrivate(form, "ReturnAsync")!;
            PumpUntil(() => returnDisc.IsCompleted);
            returnDisc.GetAwaiter().GetResult();

            var returnDiscEvent = PosEventJson.Deserialize(form.CurrentHistory[0].RawBody);
            Assert.Equal(EventTypes.Return, returnDiscEvent.EventType);
            Assert.Equal(discountedSaleId, returnDiscEvent.OriginalTransactionId);
            Assert.Equal(22400m, Assert.Single(returnDiscEvent.Items!).UnitPrice);

            // Sale 3: discounted sale followed by CANCELLATION after discount changes to 19,200.
            form.MockBackend.SetDiscounts(new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) }));
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();
            form.AddProductToCart("SKU-0001", 1);
            var payCancel = form.PayAsync();
            PumpUntil(() => payCancel.IsCompleted);
            var cancelTargetId = form.CurrentHistory[0].TransactionId;

            form.MockBackend.SetDiscounts(new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 40m, 19200m) }));
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();

            SelectHistoryByTxnId(form, cancelTargetId);
            form.CancelPrompt = _ => true;
            var cancelTask = (Task)InvokePrivate(form, "CancelAsync")!;
            PumpUntil(() => cancelTask.IsCompleted);
            cancelTask.GetAwaiter().GetResult();

            var cancelEvent = PosEventJson.Deserialize(form.CurrentHistory[0].RawBody);
            Assert.Equal(EventTypes.Cancellation, cancelEvent.EventType);
            Assert.Equal(cancelTargetId, cancelEvent.OriginalTransactionId);
            Assert.Null(cancelEvent.Items);
        });
    }

    // 5. Automatic mode applies discounted_price through MainForm's AddToCart path

    [Fact]
    public void Pb50_AutomaticSalesUsesDiscountedPriceInMainForm()
    {
        // AutomaticSales does not take a priceSelector parameter: MainForm applies discounts via AddToCart.
        var ctor = Assert.Single(typeof(AutomaticSales).GetConstructors());
        Assert.Equal(2, ctor.GetParameters().Length);

        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: true);
            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form);

            form.MockBackend.SetDiscounts(new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) }));
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();

            form.AutomaticToggle.Checked = true;
            for (var tick = 0; tick < 8; tick++)
            {
                var tickTask = form.RunAutomaticTickAsync();
                PumpUntil(() => tickTask.IsCompleted);
                tickTask.GetAwaiter().GetResult();
            }

            var soldItems = form.CurrentHistory
                .Select(record => PosEventJson.Deserialize(record.RawBody))
                .SelectMany(sale => sale.Items!)
                .ToList();
            Assert.Contains(soldItems, item => item.Sku == "SKU-0001");
            Assert.All(soldItems.Where(item => item.Sku == "SKU-0001"), item => Assert.Equal(22400m, item.UnitPrice));
            Assert.All(soldItems.Where(item => item.Sku == "SKU-0002"), item => Assert.Equal(7000m, item.UnitPrice));
            Assert.All(soldItems.Where(item => item.Sku == "SKU-0003"), item => Assert.Equal(25000m, item.UnitPrice));
        });
    }

    // 6. Lifecycle & Disposal Guard (PR #73 compatibility) + 60-second timer configuration

    [Fact]
    public void Pb50_DisposingFormDuringInFlightDiscountFetchDoesNotThrowObjectDisposed()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);

            var fetchStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var fetchRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            var call = 0;
            using var gatedHandler = new StubHttpHandler((_, cancellationToken) =>
            {
                var current = Interlocked.Increment(ref call);
                if (current == 1)
                {
                    return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                    {
                        Content = new StringContent("""{"business_date":"2026-11-23","items":[]}""",
                            Encoding.UTF8, "application/json"),
                    });
                }

                fetchStarted.TrySetResult(true);
                cancellationToken.Register(() => fetchRelease.TrySetCanceled(cancellationToken));
                return fetchRelease.Task;
            });

            var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };

            // Verify the 60-second timer interval before stopping background timers for deterministic stepping.
            var discountTimer = GetPrivateField<System.Windows.Forms.Timer>(form, "_discountTimer");
            Assert.Equal(60_000, discountTimer.Interval);
            Assert.True(discountTimer.Enabled);

            ShowFormDeterministically(form, _ => gatedHandler);
            Assert.Equal(1, call);

            // Start an in-flight discount refresh and prove it is genuinely suspended before disposal.
            var inFlight = form.RefreshDiscountsAsync();
            PumpUntil(() => fetchStarted.Task.IsCompleted);
            Assert.False(inFlight.IsCompleted);

            form.Close();
            form.Dispose();

            fetchRelease.TrySetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => inFlight.IsCompleted);
            inFlight.GetAwaiter().GetResult();
            Assert.False(discountTimer.Enabled);
        });
    }

    [Fact]
    public void Pb50_TogglingToMockDuringInFlightDiscountFetchDropsStaleLiveResult()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);

            var fetchStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            var fetchRelease = new TaskCompletionSource<HttpResponseMessage>(TaskCreationOptions.RunContinuationsAsynchronously);
            var call = 0;
            using var gatedHandler = new StubHttpHandler((_, _) =>
            {
                if (Interlocked.Increment(ref call) == 1)
                {
                    return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                    {
                        Content = new StringContent("""{"business_date":"2026-11-23","items":[]}""",
                            Encoding.UTF8, "application/json"),
                    });
                }

                fetchStarted.TrySetResult(true);
                return fetchRelease.Task;
            });

            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form, _ => gatedHandler);

            var inFlight = form.RefreshDiscountsAsync();
            PumpUntil(() => fetchStarted.Task.IsCompleted);
            Assert.False(inFlight.IsCompleted);

            var toggle = form.ToggleMockAsync();
            PumpUntil(() => toggle.IsCompleted);
            toggle.GetAwaiter().GetResult();
            Assert.True(form.IsMockMode);

            fetchRelease.SetResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                    Encoding.UTF8, "application/json"),
            });

            PumpUntil(() => inFlight.IsCompleted && IsFormIdle(form));
            inFlight.GetAwaiter().GetResult();

            Assert.Contains("MOCK", form.DiscountStatusText);
            form.AddProductToCart("SKU-0001", 1);
            Assert.Equal(32000m, Assert.Single(form.CartItems).UnitPrice);
        });
    }

    [Fact]
    public void Pb50_DiscountGridFontsAreCachedAndReusedAcrossRefreshes()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: true);
            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form);

            form.MockBackend.SetDiscounts(new PosDiscountList(
                FixedBusinessDate,
                new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) }));
            form.RefreshDiscountsAsync().GetAwaiter().GetResult();

            var origCol = form.ProductGrid.Columns.Cast<DataGridViewColumn>()
                .First(col => col.DataPropertyName == nameof(ProductRow.OriginalPriceText));
            var milkRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
            var firstFont = milkRow.Cells[origCol.Index].Style.Font;
            Assert.NotNull(firstFont);

            form.RefreshDiscountsAsync().GetAwaiter().GetResult();
            var secondMilkRow = form.ProductGrid.Rows.Cast<DataGridViewRow>()
                .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
            Assert.Same(firstFont, secondMilkRow.Cells[origCol.Index].Style.Font);
        });
    }

    // 7. Issue #88 (DSH50-10): Persist active discounts across offline restarts on same business date

    [Fact]
    public void Dsh50_10_OfflineRestartKeepsLastDiscountOnSameBusinessDate()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);

            // Session 1 (online at 14:35 UTC+7): load 30% discount for SKU-0001 -> 22,400 VND.
            using (var onlineHandler = new StubHttpHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30.0,"discounted_price":22400.0}]}""",
                    Encoding.UTF8, "application/json"),
            })))
            using (var form1 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            })
            {
                ShowFormDeterministically(form1, _ => onlineHandler);
                form1.AddProductToCart("SKU-0001", 1);
                Assert.Equal(22400m, Assert.Single(form1.CartItems).UnitPrice);
                form1.Close();
            }

            // Session 2 (same config, same business date 5 minutes later, middleware unavailable).
            using (var offlineDiscountHandler = CreateOfflineStub("Connection refused"))
            using (var form2 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc.AddMinutes(5),
                LocalClock = () => FixedLocal.AddMinutes(5),
            })
            {
                ShowFormDeterministically(form2, _ => offlineDiscountHandler, offline: true);

                // Fetch failure must be shown with the last successful update time (14:35).
                Assert.Equal("Giảm giá: cập nhật lúc 14:35", form2.DiscountStatusText);

                // ProductGrid must show strikeout original price and 22,400 discounted price.
                var origCol = form2.ProductGrid.Columns.Cast<DataGridViewColumn>()
                    .First(col => col.DataPropertyName == nameof(ProductRow.OriginalPriceText));
                var priceCol = form2.ProductGrid.Columns.Cast<DataGridViewColumn>()
                    .First(col => col.DataPropertyName == nameof(ProductRow.UnitPriceText));
                var milkRow = form2.ProductGrid.Rows.Cast<DataGridViewRow>()
                    .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
                Assert.Equal(32000m.ToString("N0"), milkRow.Cells[origCol.Index].Value?.ToString());
                Assert.True(milkRow.Cells[origCol.Index].Style.Font?.Strikeout ?? false);
                Assert.Contains(22400m.ToString("N0"), milkRow.Cells[priceCol.Index].Value?.ToString());

                // Cart uses 22,400 VND (not 32,000 list price), and Pay queues offline without blocking sales.
                form2.AddProductToCart("SKU-0001", 1);
                var cartItem = Assert.Single(form2.CartItems);
                Assert.Equal(22400m, cartItem.UnitPrice);
                Assert.Equal(32000m, cartItem.ListPrice);
                Assert.True(cartItem.HasDiscount);

                var liveClient = (TerminalClient)InvokePrivate(form2, "GetLiveClient", loaded.Config.Terminals[0])!;
                ReplaceHttpClient(liveClient, CreateOfflineStub("Connection refused"), disposeHandler: true);

                var payTask = form2.PayAsync();
                PumpUntil(() => payTask.IsCompleted && IsFormIdle(form2));
                var payResult = payTask.GetAwaiter().GetResult();
                Assert.Equal("WAITING", payResult.Code);
                Assert.Empty(form2.CartItems);

                var queuedSale = PosEventJson.Deserialize(form2.CurrentHistory[0].RawBody);
                Assert.Equal(EventTypes.Sale, queuedSale.EventType);
                Assert.Equal(22400m, Assert.Single(queuedSale.Items!).UnitPrice);
                form2.Close();
            }
        });
    }

    [Fact]
    public void Dsh50_10_OfflineRestartOnNextBusinessDateDropsCachedDiscount()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);

            var beforeMidnightUtc = new DateTime(2026, 11, 23, 16, 59, 30, DateTimeKind.Utc);
            var beforeMidnightLocal = new DateTime(2026, 11, 23, 23, 59, 30, DateTimeKind.Local);
            using (var onlineHandler = new StubHttpHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                    Encoding.UTF8, "application/json"),
            })))
            using (var form1 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => beforeMidnightUtc,
                LocalClock = () => beforeMidnightLocal,
            })
            {
                ShowFormDeterministically(form1, _ => onlineHandler);
                form1.AddProductToCart("SKU-0001", 1);
                Assert.Equal(22400m, Assert.Single(form1.CartItems).UnitPrice);
                form1.Close();
            }

            // Reopen offline after UTC+7 midnight: 2026-11-24 00:00:05 UTC+7.
            var afterMidnightUtc = new DateTime(2026, 11, 23, 17, 0, 5, DateTimeKind.Utc);
            var afterMidnightLocal = new DateTime(2026, 11, 24, 0, 0, 5, DateTimeKind.Local);
            using (var offlineHandler = CreateOfflineStub("Connection refused"))
            using (var form2 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => afterMidnightUtc,
                LocalClock = () => afterMidnightLocal,
            })
            {
                ShowFormDeterministically(form2, _ => offlineHandler, offline: true);

                Assert.Equal("Giảm giá: chưa tải được", form2.DiscountStatusText);
                Assert.DoesNotContain("23:59", form2.DiscountStatusText);

                var milkRow = form2.ProductGrid.Rows.Cast<DataGridViewRow>()
                    .First(row => ((ProductRow)row.DataBoundItem!).Sku == "SKU-0001");
                Assert.False(((ProductRow)milkRow.DataBoundItem!).HasDiscount);

                form2.AddProductToCart("SKU-0001", 1);
                Assert.Equal(32000m, Assert.Single(form2.CartItems).UnitPrice);
                Assert.False(File.Exists(Path.Combine(directory.Path, "POS-DN1-01.discounts.json")));
                form2.Close();
            }
        });
    }

    [Fact]
    public void Dsh50_10_EmptyOnlineRefreshOverwritesPersistedDiscountCache()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);
            var currentUtc = FixedUtc;
            var currentLocal = FixedLocal;
            var call = 0;

            using (var handler = new StubHttpHandler((_, _) =>
            {
                call++;
                var body = call == 1
                    ? """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}"""
                    : """{"business_date":"2026-11-23","items":[]}""";
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(body, Encoding.UTF8, "application/json"),
                });
            }))
            using (var form1 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => currentUtc,
                LocalClock = () => currentLocal,
            })
            {
                ShowFormDeterministically(form1, _ => handler);
                form1.AddProductToCart("SKU-0001", 1);
                Assert.Equal(22400m, Assert.Single(form1.CartItems).UnitPrice);

                currentUtc = FixedUtc.AddMinutes(5);
                currentLocal = FixedLocal.AddMinutes(5);
                var refresh = form1.RefreshDiscountsAsync();
                PumpUntil(() => refresh.IsCompleted && IsFormIdle(form1));
                refresh.GetAwaiter().GetResult();
                form1.Close();
            }

            // Reopen offline on the same business date: revoked discount must NOT resurrect.
            using (var offlineHandler = CreateOfflineStub("Connection refused"))
            using (var form2 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc.AddMinutes(10),
                LocalClock = () => FixedLocal.AddMinutes(10),
            })
            {
                ShowFormDeterministically(form2, _ => offlineHandler, offline: true);

                Assert.Equal("Giảm giá: cập nhật lúc 14:40", form2.DiscountStatusText);
                form2.AddProductToCart("SKU-0001", 1);
                Assert.Equal(32000m, Assert.Single(form2.CartItems).UnitPrice);
                form2.Close();
            }
        });
    }

    [Fact]
    public void Dsh50_10_MockModeAndChangedConfigDoNotPolluteOrLeakLiveDiscountCache()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);

            // Session 1: fetch LIVE 30% discount (22,400), then toggle to MOCK with a 50% discount (16,000).
            using (var onlineHandler = new StubHttpHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30,"discounted_price":22400}]}""",
                    Encoding.UTF8, "application/json"),
            })))
            using (var form1 = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            })
            {
                ShowFormDeterministically(form1, _ => onlineHandler);
                var toMock = form1.ToggleMockAsync();
                PumpUntil(() => toMock.IsCompleted && IsFormIdle(form1));
                toMock.GetAwaiter().GetResult();

                form1.MockBackend.SetDiscounts("STORE-DN1", new PosDiscountList(
                    FixedBusinessDate,
                    new[] { new PosDiscountItem("SKU-0001", 50m, 16000m) }));
                var mockRefresh = form1.RefreshDiscountsAsync();
                PumpUntil(() => mockRefresh.IsCompleted && IsFormIdle(form1));
                mockRefresh.GetAwaiter().GetResult();
                form1.Close();
            }

            // Session 2 (same LIVE config, offline): still has LIVE 22,400 (NOT mock 16,000).
            var sameLiveConfig = BuildConfig(directory.Path, mock: false);
            using (var offlineHandler = CreateOfflineStub("Connection refused"))
            using (var form2 = new MainForm(sameLiveConfig, directory.Path)
            {
                UtcClock = () => FixedUtc.AddMinutes(5),
                LocalClock = () => FixedLocal.AddMinutes(5),
            })
            {
                ShowFormDeterministically(form2, _ => offlineHandler, offline: true);
                Assert.Equal("Giảm giá: cập nhật lúc 14:35", form2.DiscountStatusText);
                form2.AddProductToCart("SKU-0001", 1);
                Assert.Equal(22400m, Assert.Single(form2.CartItems).UnitPrice);
                form2.Close();
            }

            // Session 3 (different PosBaseUrl, offline): must not reuse cache from another endpoint.
            var differentEndpointConfig = BuildConfig(
                directory.Path, mock: false, posBaseUrl: "https://127.0.0.1:29443/api/v1");
            using (var offlineHandler = CreateOfflineStub("Connection refused"))
            using (var form3 = new MainForm(differentEndpointConfig, directory.Path)
            {
                UtcClock = () => FixedUtc.AddMinutes(5),
                LocalClock = () => FixedLocal.AddMinutes(5),
            })
            {
                ShowFormDeterministically(form3, _ => offlineHandler, offline: true);
                Assert.Equal("Giảm giá: chưa tải được", form3.DiscountStatusText);
                form3.AddProductToCart("SKU-0001", 1);
                Assert.Equal(32000m, Assert.Single(form3.CartItems).UnitPrice);
                form3.Close();
            }

            // Session 4 (different StoreId for same PosId, offline): must not leak another store's discount.
            var differentStoreConfig = BuildConfig(
                directory.Path, mock: false, storeId: "STORE-DN2");
            using (var offlineHandler = CreateOfflineStub("Connection refused"))
            using (var form4 = new MainForm(differentStoreConfig, directory.Path)
            {
                UtcClock = () => FixedUtc.AddMinutes(5),
                LocalClock = () => FixedLocal.AddMinutes(5),
            })
            {
                ShowFormDeterministically(form4, _ => offlineHandler, offline: true);
                Assert.Equal("Giảm giá: chưa tải được", form4.DiscountStatusText);
                form4.AddProductToCart("SKU-0001", 1);
                Assert.Equal(32000m, Assert.Single(form4.CartItems).UnitPrice);
                form4.Close();
            }
        });
    }

    [Theory]
    [InlineData("en-US")]
    [InlineData("vi-VN")]
    [InlineData("de-DE")]
    public void Dsh50_10_RestartPreservesDiscountsPerTerminalAcrossLocales(string cultureName)
    {
        OnStaThread(() =>
        {
            var previous = CultureInfo.CurrentCulture;
            try
            {
                CultureInfo.CurrentCulture = new CultureInfo(cultureName);
                using var directory = new TemporaryDirectory();
                var loaded = BuildConfig(directory.Path, mock: false, includeSecondTerminal: true);

                using (var form1 = new MainForm(loaded, directory.Path)
                {
                    UtcClock = () => FixedUtc,
                    LocalClock = () => FixedLocal,
                })
                {
                    ShowFormDeterministically(form1, terminal => new StubHttpHandler((_, _) =>
                    {
                        var body = string.Equals(terminal.PosId, "POS-DN1-01", StringComparison.OrdinalIgnoreCase)
                            ? """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":30.5,"discounted_price":22240.50}]}"""
                            : """{"business_date":"2026-11-23","items":[{"sku":"SKU-0001","discount_pct":15.0,"discounted_price":27200.00}]}""";
                        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                        {
                            Content = new StringContent(body, Encoding.UTF8, "application/json"),
                        });
                    }));

                    // Switch to terminal 2 so both terminals fetch and persist their own discount caches.
                    form1.SelectTerminal("POS-DN2-01");
                    PumpUntil(() => IsFormIdle(form1));
                    form1.AddProductToCart("SKU-0001", 1);
                    Assert.Equal(27200m, Assert.Single(form1.CartItems).UnitPrice);
                    form1.Close();
                }

                // Restart offline: terminal 1 keeps 22,240.50 and terminal 2 keeps 27,200.
                using (var offlineHandler = CreateOfflineStub("Connection refused"))
                using (var form2 = new MainForm(loaded, directory.Path)
                {
                    UtcClock = () => FixedUtc.AddMinutes(5),
                    LocalClock = () => FixedLocal.AddMinutes(5),
                })
                {
                    ShowFormDeterministically(form2, _ => offlineHandler, offline: true);

                    Assert.Equal("Giảm giá: cập nhật lúc 14:35", form2.DiscountStatusText);
                    form2.AddProductToCart("SKU-0001", 1);
                    Assert.Equal(22240.50m, Assert.Single(form2.CartItems).UnitPrice);

                    form2.SelectTerminal("POS-DN2-01");
                    PumpUntil(() => IsFormIdle(form2));
                    Assert.Equal("Giảm giá: cập nhật lúc 14:35", form2.DiscountStatusText);
                    form2.AddProductToCart("SKU-0001", 1);
                    Assert.Equal(27200m, Assert.Single(form2.CartItems).UnitPrice);
                    form2.Close();
                }
            }
            finally
            {
                CultureInfo.CurrentCulture = previous;
            }
        });
    }

    [Fact]
    public void Dsh50_10_CorruptDiscountCacheFileIsIgnoredSafelyOnOfflineStartup()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = BuildConfig(directory.Path, mock: false);
            File.WriteAllText(Path.Combine(directory.Path, "POS-DN1-01.discounts.json"), "{corrupt-json", Encoding.UTF8);

            using var offlineHandler = CreateOfflineStub("Connection refused");
            using var form = new MainForm(loaded, directory.Path)
            {
                UtcClock = () => FixedUtc,
                LocalClock = () => FixedLocal,
            };
            ShowFormDeterministically(form, _ => offlineHandler, offline: true);

            Assert.Equal("Giảm giá: chưa tải được", form.DiscountStatusText);
            form.AddProductToCart("SKU-0001", 1);
            Assert.Equal(32000m, Assert.Single(form.CartItems).UnitPrice);
            form.Close();
        });
    }

    [Fact]
    public void Dsh50_10_PosDiscountCacheStoreValidatesPosIdNormalizesUrlAndLeavesNoTempFiles()
    {
        using var directory = new TemporaryDirectory();
        var store = new PosDiscountCacheStore(directory.Path);

        Assert.Throws<ArgumentException>(() => store.PathFor(""));
        Assert.Throws<ArgumentException>(() => store.PathFor(".."));
        Assert.Throws<ArgumentException>(() => store.PathFor("POS/01"));
        Assert.Null(store.Load("..", "STORE-DN1", "https://127.0.0.1:19443/api/v1"));

        var list = new PosDiscountList(
            FixedBusinessDate,
            new[] { new PosDiscountItem("SKU-0001", 30m, 22400m) });
        store.Save("POS-DN1-01", "STORE-DN1", "https://127.0.0.1:19443/api/v1/", list, FixedLocal);

        var loaded = store.Load("POS-DN1-01", "store-dn1", "https://127.0.0.1:19443/api/v1");
        Assert.NotNull(loaded);
        Assert.Equal(FixedBusinessDate, loaded!.List.BusinessDate);
        Assert.Equal(22400m, Assert.Single(loaded.List.Items).DiscountedPrice);
        Assert.Equal(FixedLocal, loaded.UpdatedAtLocal);
        Assert.Empty(Directory.GetFiles(directory.Path, "*.tmp"));

        store.Clear("POS-DN1-01");
        Assert.Null(store.Load("POS-DN1-01", "STORE-DN1", "https://127.0.0.1:19443/api/v1"));
    }

    private static void SelectHistoryByTxnId(MainForm form, string txnId)
    {
        foreach (DataGridViewRow row in form.HistoryGrid.Rows)
        {
            if (row.DataBoundItem is TxnRecord record && record.TransactionId == txnId)
            {
                form.HistoryGrid.ClearSelection();
                row.Selected = true;
                form.HistoryGrid.CurrentCell = row.Cells[0];
                Application.DoEvents();
                return;
            }
        }

        throw new InvalidOperationException($"Transaction '{txnId}' not found in HistoryGrid.");
    }
}
