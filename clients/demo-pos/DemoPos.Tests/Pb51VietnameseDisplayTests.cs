using System.Reflection;
using DemoPos.Configuration;
using DemoPos.Models;
using DemoPos.Services;
using DemoPos.UI;
using Xunit;

namespace DemoPos.Tests;

public sealed class Pb51VietnameseDisplayTests
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

    private static T GetPrivateField<T>(object target, string fieldName)
    {
        var field = target.GetType().GetField(fieldName, BindingFlags.Instance | BindingFlags.NonPublic)
                    ?? throw new MissingFieldException(target.GetType().FullName, fieldName);
        return (T)field.GetValue(target)!;
    }

    [Theory]
    [InlineData("DUPLICATE_IGNORED", "Giao dịch đã được ghi trước đó")]
    [InlineData("CONFLICT", "Trùng mã giao dịch nhưng khác nội dung")]
    [InlineData("INSUFFICIENT_STOCK", "Không đủ tồn kho")]
    [InlineData("FORBIDDEN", "Không có quyền: chứng chỉ hoặc token không hợp lệ")]
    [InlineData("SALE_HAS_RETURNS", "Đơn bán đã có giao dịch trả hàng nên không thể hủy")]
    [InlineData("SALE_ALREADY_CANCELLED", "Đơn bán gốc đã bị hủy trước đó")]
    [InlineData("ORIGINAL_SALE_NOT_FOUND", "Không tìm thấy giao dịch bán gốc")]
    [InlineData("UNREGISTERED_STORE_OR_POS", "Cửa hàng hoặc máy POS chưa được đăng ký hoặc ngừng hoạt động")]
    [InlineData("INVALID_EVENT", "Dữ liệu sự kiện POS không hợp lệ")]
    [InlineData("VALIDATION_ERROR", "Dữ liệu gửi lên không hợp lệ")]
    [InlineData("UNAUTHORIZED", "Thiếu token hoặc token không hợp lệ / đã hết hạn")]
    [InlineData("SERVICE_UNAVAILABLE", "Dịch vụ tạm thời không khả dụng, vui lòng thử lại")]
    [InlineData("PAYLOAD_TOO_LARGE", "Nội dung yêu cầu vượt quá dung lượng cho phép")]
    [InlineData("SNAPSHOT_REJECTED", "Bản chụp từ HQ bị từ chối theo quy tắc bảo vệ dữ liệu")]
    [InlineData("JOB_RUNNING", "Tác vụ đang chạy, vui lòng thử lại sau")]
    [InlineData("RETURN_QTY_EXCEEDED", "Số lượng trả vượt quá số lượng đã bán")]
    [InlineData("OK", "Đã áp dụng giao dịch")]
    public void ServerMessage_MapsEveryKnownCodeToVietnamese(string code, string expected)
    {
        var text = PosDisplayNames.ServerMessage(code, "Raw English server text");

        Assert.Equal(expected, text);
    }

    [Fact]
    public void ServerMessage_UnknownCodeShowsVerbatimServerText()
    {
        const string serverText = "Custom upstream message from middleware";

        Assert.Equal(serverText, PosDisplayNames.ServerMessage("BRAND_NEW_CODE", serverText));
        Assert.Equal("BRAND_NEW_CODE", PosDisplayNames.ServerMessage("BRAND_NEW_CODE", string.Empty));
    }

    [Theory]
    [InlineData(PosOutcome.OK, "Thành công")]
    [InlineData(PosOutcome.DUPLICATE, "Trùng lặp")]
    [InlineData(PosOutcome.REJECTED, "Bị từ chối")]
    [InlineData(PosOutcome.ERROR, "Lỗi")]
    public void Outcome_MapsEveryPosOutcomeToVietnamese(PosOutcome outcome, string expected)
    {
        Assert.Equal(expected, PosDisplayNames.Outcome(outcome));
    }

    [Theory]
    [InlineData("OK", "Thành công")]
    [InlineData("DUPLICATE", "Trùng lặp")]
    [InlineData("REJECTED", "Bị từ chối")]
    [InlineData("ERROR", "Lỗi")]
    [InlineData("WAITING", "Chờ gửi")]
    [InlineData("MYSTERY_OUTCOME", "MYSTERY_OUTCOME")]
    public void OutcomeText_MapsKnownCodesAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, PosDisplayNames.OutcomeText(code));
    }

    [Theory]
    [InlineData("SALE", "Bán hàng")]
    [InlineData("RETURN", "Trả hàng")]
    [InlineData("CANCELLATION", "Hủy đơn")]
    [InlineData("CUSTOM_EVENT", "CUSTOM_EVENT")]
    public void EventType_MapsKnownTypesAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, PosDisplayNames.EventType(code));
    }

    [Fact]
    public void ResultPanel_KeepsCodeVisibleAndShowsVietnameseMessageForKnownAndRawForUnknown()
    {
        OnStaThread(() =>
        {
            using var panel = new ResultPanel();
            var outcomeLabel = GetPrivateField<Label>(panel, "_outcome");
            var codeLabel = GetPrivateField<Label>(panel, "_code");
            var messageLabel = GetPrivateField<Label>(panel, "_message");
            var stockLabel = GetPrivateField<Label>(panel, "_stock");
            var retryButton = GetPrivateField<Button>(panel, "_retry");

            Assert.Equal("Thử lại", retryButton.Text);

            panel.ShowResult(new PosResult
            {
                Outcome = PosOutcome.DUPLICATE,
                Code = "DUPLICATE_IGNORED",
                Message = "Transaction already recorded",
                CurrentStock = new Dictionary<string, int> { ["SKU-0001"] = 38 },
                HttpStatus = 200,
                ElapsedMs = 8,
            });
            Assert.Equal("Trùng lặp", outcomeLabel.Text);
            Assert.Equal("DUPLICATE_IGNORED", codeLabel.Text);
            Assert.Equal("Giao dịch đã được ghi trước đó", messageLabel.Text);
            Assert.StartsWith("Tồn kho hiện tại:", stockLabel.Text, StringComparison.Ordinal);

            panel.ShowResult(new PosResult
            {
                Outcome = PosOutcome.REJECTED,
                Code = "CUSTOM_SERVER_CODE",
                Message = "Server specific text stays verbatim",
                HttpStatus = 409,
                ElapsedMs = 5,
            });
            Assert.Equal("Bị từ chối", outcomeLabel.Text);
            Assert.Equal("CUSTOM_SERVER_CODE", codeLabel.Text);
            Assert.Equal("Server specific text stays verbatim", messageLabel.Text);

            panel.ShowInfo("Kiểm tra thông báo");
            Assert.Equal("Thông báo", outcomeLabel.Text);
        });
    }

    [Fact]
    public async Task MockPosBackend_WritesVietnameseMessagesWhileKeepingApiCodesEnglish()
    {
        var config = new AppConfig
        {
            UseMock = true,
            Terminals = new List<TerminalConfig>
            {
                new() { StoreId = "STORE-DN1", StoreName = "Cửa hàng Hải Châu", PosId = "POS-DN1-01" },
            },
            Products = new List<ProductConfig>
            {
                new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Sữa tươi 1L", UnitPrice = 32000m },
            },
        };
        var backend = new MockPosBackend(config);

        string SaleJson(string txnId, int qty, string storeId = "STORE-DN1") =>
            PosEventJson.Serialize(PosEvents.Sale(storeId, "POS-DN1-01",
                new[] { new PosEventItem { Sku = "SKU-0001", Quantity = qty, UnitPrice = 32000m } }, txnId));

        var ok = await backend.SendAsync(SaleJson("TXN-POS-DN1-01-20261128010101-0001", 2));
        Assert.Equal("OK", ok.Code);
        Assert.Equal("Đã áp dụng giao dịch", ok.Message);

        var dup = await backend.SendAsync(SaleJson("TXN-POS-DN1-01-20261128010101-0001", 2));
        Assert.Equal("DUPLICATE_IGNORED", dup.Code);
        Assert.Equal("Giao dịch đã được ghi trước đó", dup.Message);

        var conflict = await backend.SendAsync(SaleJson("TXN-POS-DN1-01-20261128010101-0001", 3));
        Assert.Equal("CONFLICT", conflict.Code);
        Assert.Equal("Trùng mã giao dịch nhưng khác nội dung", conflict.Message);

        var stock = await backend.SendAsync(SaleJson("TXN-POS-DN1-01-20261128010101-0002", 999));
        Assert.Equal("INSUFFICIENT_STOCK", stock.Code);
        Assert.Contains("Không đủ tồn kho", stock.Message);

        var unregistered = await backend.SendAsync(SaleJson("TXN-POS-DN1-01-20261128010101-0003", 1, "STORE-XX"));
        Assert.Equal("UNREGISTERED_STORE_OR_POS", unregistered.Code);
        Assert.Contains("chưa được đăng ký", unregistered.Message);

        var badJson = await backend.SendAsync("{not-json");
        Assert.Equal("INVALID_EVENT", badJson.Code);
        Assert.Contains("không hợp lệ", badJson.Message);
    }

    [Fact]
    public void MainForm_UsesVietnameseTabHeadersColumnHeadersAndButtons()
    {
        OnStaThread(() =>
        {
            using var directory = new TemporaryDirectory();
            var loaded = new LoadedConfig
            {
                Config = new AppConfig
                {
                    UseMock = true,
                    Terminals = new List<TerminalConfig>
                    {
                        new() { StoreId = "STORE-DN1", StoreName = "Cửa hàng Hải Châu", PosId = "POS-DN1-01" },
                    },
                    Products = new List<ProductConfig>
                    {
                        new() { Sku = "SKU-0001", Barcode = "8930000000011", Name = "Sữa tươi 1L", UnitPrice = 32000m },
                    },
                },
                Paths = new AppPaths
                {
                    RepoRoot = directory.Path,
                    CaCertificate = Path.Combine(directory.Path, "ca.crt"),
                    ClientCertificateDir = directory.Path,
                    TokensFile = Path.Combine(directory.Path, "tokens.json"),
                    SettingsFile = Path.Combine(directory.Path, "appsettings.json"),
                    LocalSettingsFile = Path.Combine(directory.Path, "appsettings.Local.json"),
                },
                Tokens = new Dictionary<string, string>(),
                Problems = Array.Empty<string>(),
            };

            using var form = new MainForm(loaded, directory.Path);

            var tabTitles = form.Tabs.TabPages.Cast<TabPage>().Select(p => p.Text).ToList();
            Assert.Equal(new[] { "Bán hàng", "Giám sát (chỉ đọc)", "Máy POS", "Nhật ký yêu cầu" }, tabTitles);

            var historyHeaders = form.HistoryGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("Transaction id", historyHeaders);
            Assert.DoesNotContain("Items", historyHeaders);
            Assert.DoesNotContain("Code", historyHeaders);
            Assert.Contains("Mã giao dịch", historyHeaders);
            Assert.Contains("Mặt hàng", historyHeaders);
            Assert.Contains("Mã phản hồi", historyHeaders);

            var auditGrid = GetPrivateField<DataGridView>(form, "_auditGrid");
            var auditHeaders = auditGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("Action", auditHeaders);
            Assert.DoesNotContain("Entity key", auditHeaders);
            Assert.DoesNotContain("Details", auditHeaders);
            Assert.Contains("Hành động", auditHeaders);
            Assert.Contains("Khóa đối tượng", auditHeaders);
            Assert.Contains("Chi tiết", auditHeaders);

            var terminalsHeaders = form.TerminalsGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("Store", terminalsHeaders);
            Assert.DoesNotContain("POS id", terminalsHeaders);
            Assert.DoesNotContain("Cert", terminalsHeaders);
            Assert.DoesNotContain("Key", terminalsHeaders);
            Assert.DoesNotContain("Fingerprint (12)", terminalsHeaders);

            var logHeaders = form.RequestLogGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("Method", logHeaders);
            Assert.DoesNotContain("Status", logHeaders);
            Assert.DoesNotContain("Cert", logHeaders);
            Assert.DoesNotContain("Role / subject", logHeaders);
        });
    }
}
