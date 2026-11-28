using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Windows.Forms;
using DemoConsole.Configuration;
using DemoConsole.Models;
using DemoConsole.Services;
using DemoConsole.UI;
using Xunit;

namespace DemoConsole.Tests;

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
    [InlineData("SURPLUS", "Thừa hàng")]
    [InlineData("SHORTAGE", "Thiếu hàng")]
    [InlineData("BALANCED", "Cân bằng")]
    [InlineData("UNKNOWN_BALANCE", "UNKNOWN_BALANCE")]
    public void BalanceStatus_MatchesStaffAppVocabularyAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.BalanceStatus(code));
    }

    [Theory]
    [InlineData("EXPIRED", "Đã hết hạn")]
    [InlineData("NEAR_EXPIRY", "Sắp hết hạn")]
    [InlineData("UNKNOWN_ALERT", "UNKNOWN_ALERT")]
    public void AlertType_MatchesStaffAppVocabularyAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.AlertType(code));
    }

    [Theory]
    [InlineData("MIN_SHELF_LIFE", "Hạn dùng tối thiểu")]
    [InlineData("MAX_DISCOUNT", "Giảm giá tối đa")]
    [InlineData("MIN_PRICE", "Giá tối thiểu")]
    [InlineData("UNKNOWN_RULE", "UNKNOWN_RULE")]
    public void RuleType_MatchesStaffAppVocabularyAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.RuleType(code));
    }

    [Theory]
    [InlineData("PASSED", "Đạt")]
    [InlineData("ADJUSTED", "Điều chỉnh")]
    [InlineData("BLOCKED", "Chặn")]
    [InlineData("UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME")]
    public void Outcome_MatchesStaffAppVocabularyAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.Outcome(code));
    }

    [Theory]
    [InlineData("Dairy", "Sữa")]
    [InlineData("Bakery", "Bánh tươi")]
    [InlineData("Dry goods", "Hàng khô")]
    [InlineData("Beverages", "Đồ uống")]
    [InlineData("Snacks", "Bánh kẹo")]
    [InlineData("Frozen", "Đồ đông lạnh")]
    [InlineData("Household", "Household")]
    public void Category_MatchesStaffAppVocabularyAndDashboardTabLabel(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.Category(code));
        Assert.Equal(expected, DashboardTab.Label(code));
    }

    [Theory]
    [InlineData("DISCOUNT", "Giảm giá")]
    [InlineData("CLEARANCE", "Thanh lý")]
    [InlineData("REDISTRIBUTION", "Điều chuyển")]
    [InlineData("UNKNOWN_ACTION", "UNKNOWN_ACTION")]
    public void ActionType_MatchesStaffAppVocabularyAndKeepsUnknownCode(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.ActionType(code));
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
    public void ServerMessage_MapsKnownCodesAndSummaryKeepsCodeVisible(string code, string expected)
    {
        Assert.Equal(expected, ConsoleDisplayNames.ServerMessage(code, "Raw English server text"));

        var result = new ApiResult(409, code, "Raw English server text", string.Empty, 12);
        Assert.Contains(code, result.Summary, StringComparison.Ordinal);
        Assert.Contains(expected, result.Summary, StringComparison.Ordinal);
    }

    [Fact]
    public void ServerMessage_UnknownCodeKeepsCodeVisibleAndShowsServerTextVerbatim()
    {
        const string serverText = "Exact server explanation for unknown error";
        Assert.Equal(serverText, ConsoleDisplayNames.ServerMessage("NEW_UNMAPPED_CODE", serverText));

        var result = new ApiResult(400, "NEW_UNMAPPED_CODE", serverText, string.Empty, 5);
        Assert.Equal($"HTTP 400 NEW_UNMAPPED_CODE - {serverText}", result.Summary);
    }

    [Fact]
    public void MainForm_UsesVietnameseHeadersAndAllSixCategoriesInThresholdDropdown()
    {
        OnStaThread(() =>
        {
            using var repo = new TestRepo();
            using var caKey = RSA.Create(2048);
            var caReq = new CertificateRequest("CN=Test CA", caKey, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
            caReq.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
            using var ca = caReq.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddDays(30));
            File.WriteAllText(Path.Combine(repo.Root, ".certs", "ca.crt"), ca.ExportCertificatePem());

            var loaded = ConfigLoader.Load(repo.Root, repo.SettingsFile);
            using var form = new MainForm(loaded);

            var tabs = form.Controls.OfType<TabControl>().Single();
            var tabTitles = tabs.TabPages.Cast<TabPage>().Select(p => p.Text).ToList();
            Assert.DoesNotContain("Job", tabTitles);
            Assert.Contains("Tác vụ", tabTitles);

            var auditGrid = GetPrivateField<DataGridView>(form, "_auditGrid");
            var auditHeaders = auditGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("Action", auditHeaders);
            Assert.DoesNotContain("Entity key", auditHeaders);
            Assert.Contains("Hành động", auditHeaders);
            Assert.Contains("Khóa đối tượng", auditHeaders);

            var txnGrid = GetPrivateField<DataGridView>(form, "_transactionGrid");
            var txnHeaders = txnGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("sync_batch_id", txnHeaders);

            var syncGrid = GetPrivateField<DataGridView>(form, "_syncGrid");
            var syncHeaders = syncGrid.Columns.Cast<DataGridViewColumn>().Select(c => c.HeaderText).ToList();
            Assert.DoesNotContain("sync_batch_id", syncHeaders);
            Assert.DoesNotContain("ACK lúc", syncHeaders);

            var thresholdCombo = GetPrivateField<ComboBox>(form, "_thresholdCategory");
            var displayed = thresholdCombo.Items.Cast<object>().Select(item => item.ToString()).ToList();
            Assert.Equal(new[] { "Sữa", "Bánh tươi", "Hàng khô", "Đồ uống", "Bánh kẹo", "Đồ đông lạnh" }, displayed);
        });
    }
}
