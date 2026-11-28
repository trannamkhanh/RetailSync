using DemoConsole.Models;

namespace DemoConsole.Services;

/// <summary>
/// Vietnamese display mapping for console grids, charts and server responses (PB-51).
/// Uses the same Vietnamese vocabulary as StaffApp.Services.DisplayNames.
/// API requests, stored models and log values stay English; unknown codes stay as received.
/// </summary>
public static class ConsoleDisplayNames
{
    private static readonly Dictionary<string, string> BalanceStatuses = new(StringComparer.Ordinal)
    {
        ["SURPLUS"] = "Thừa hàng",
        ["SHORTAGE"] = "Thiếu hàng",
        ["BALANCED"] = "Cân bằng",
    };

    private static readonly Dictionary<string, string> AlertTypes = new(StringComparer.Ordinal)
    {
        ["EXPIRED"] = "Đã hết hạn",
        ["NEAR_EXPIRY"] = "Sắp hết hạn",
    };

    private static readonly Dictionary<string, string> AlertStatuses = new(StringComparer.Ordinal)
    {
        ["OPEN"] = "Đang mở",
        ["CLOSED"] = "Đã đóng",
        ["RESOLVED"] = "Đã xử lý",
    };

    private static readonly Dictionary<string, string> RuleTypes = new(StringComparer.Ordinal)
    {
        ["MIN_SHELF_LIFE"] = "Hạn dùng tối thiểu",
        ["MAX_DISCOUNT"] = "Giảm giá tối đa",
        ["MIN_PRICE"] = "Giá tối thiểu",
    };

    private static readonly Dictionary<string, string> Outcomes = new(StringComparer.Ordinal)
    {
        ["PASSED"] = "Đạt",
        ["ADJUSTED"] = "Điều chỉnh",
        ["BLOCKED"] = "Chặn",
    };

    private static readonly Dictionary<string, string> Categories = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Dairy"] = "Sữa",
        ["Bakery"] = "Bánh tươi",
        ["Dry goods"] = "Hàng khô",
        ["Beverages"] = "Đồ uống",
        ["Snacks"] = "Bánh kẹo",
        ["Frozen"] = "Đồ đông lạnh",
    };

    private static readonly Dictionary<string, string> ActionTypes = new(StringComparer.Ordinal)
    {
        ["DISCOUNT"] = "Giảm giá",
        ["CLEARANCE"] = "Thanh lý",
        ["REDISTRIBUTION"] = "Điều chuyển",
    };

    private static readonly Dictionary<string, string> TransactionTypes = new(StringComparer.OrdinalIgnoreCase)
    {
        ["SALE"] = "Bán hàng",
        ["RETURN"] = "Trả hàng",
        ["CANCELLATION"] = "Hủy đơn",
    };

    private static readonly Dictionary<string, string> TransactionStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        ["APPLIED"] = "Đã ghi nhận",
        ["CANCELLED"] = "Đã hủy",
        ["OK"] = "Thành công",
    };

    private static readonly Dictionary<string, string> SyncStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        ["PENDING"] = "Chờ gửi",
        ["ACKED"] = "Đã xác nhận",
        ["FAILED"] = "Thất bại",
    };

    private static readonly Dictionary<string, string> JobStatuses = new(StringComparer.OrdinalIgnoreCase)
    {
        ["COMPLETED"] = "hoàn tất",
        ["RUNNING"] = "đang chạy",
        ["FAILED"] = "thất bại",
    };

    private static readonly Dictionary<string, string> ServerMessages = new(StringComparer.OrdinalIgnoreCase)
    {
        ["DUPLICATE_IGNORED"] = "Giao dịch đã được ghi trước đó",
        ["CONFLICT"] = "Trùng mã giao dịch nhưng khác nội dung",
        ["INSUFFICIENT_STOCK"] = "Không đủ tồn kho",
        ["FORBIDDEN"] = "Không có quyền: chứng chỉ hoặc token không hợp lệ",
        ["SALE_HAS_RETURNS"] = "Đơn bán đã có giao dịch trả hàng nên không thể hủy",
        ["SALE_ALREADY_CANCELLED"] = "Đơn bán gốc đã bị hủy trước đó",
        ["ORIGINAL_SALE_NOT_FOUND"] = "Không tìm thấy giao dịch bán gốc",
        ["UNREGISTERED_STORE_OR_POS"] = "Cửa hàng hoặc máy POS chưa được đăng ký hoặc ngừng hoạt động",
        ["INVALID_EVENT"] = "Dữ liệu sự kiện POS không hợp lệ",
        ["VALIDATION_ERROR"] = "Dữ liệu gửi lên không hợp lệ",
        ["UNAUTHORIZED"] = "Thiếu token hoặc token không hợp lệ / đã hết hạn",
        ["SERVICE_UNAVAILABLE"] = "Dịch vụ tạm thời không khả dụng, vui lòng thử lại",
        ["PAYLOAD_TOO_LARGE"] = "Nội dung yêu cầu vượt quá dung lượng cho phép",
        ["SNAPSHOT_REJECTED"] = "Bản chụp từ HQ bị từ chối theo quy tắc bảo vệ dữ liệu",
        ["JOB_RUNNING"] = "Tác vụ đang chạy, vui lòng thử lại sau",
        ["RETURN_QTY_EXCEEDED"] = "Số lượng trả vượt quá số lượng đã bán",
        ["NOT_FOUND"] = "Không tìm thấy tài nguyên yêu cầu",
        ["ALREADY_EXISTS"] = "Dữ liệu đã tồn tại",
        ["HQ_OFFLINE"] = "Hệ thống HQ đang ngoại tuyến",
        ["HQ_ERROR"] = "Hệ thống HQ trả về lỗi",
        ["METHOD_NOT_ALLOWED"] = "Phương thức HTTP không được hỗ trợ",
    };

    public static string BalanceStatus(string code) => Of(BalanceStatuses, code);

    public static string AlertType(string code) => Of(AlertTypes, code);

    public static string AlertStatus(string code) => Of(AlertStatuses, code);

    public static string RuleType(string code) => Of(RuleTypes, code);

    public static string Outcome(string code) => Of(Outcomes, code);

    public static string Category(string code) => Of(Categories, code);

    public static string ActionType(string code) => Of(ActionTypes, code);

    public static string TransactionType(string code) => Of(TransactionTypes, code);

    public static string TransactionStatus(string code) => Of(TransactionStatuses, code);

    public static string SyncStatus(string code) => Of(SyncStatuses, code);

    public static string JobStatus(string code) => Of(JobStatuses, code);

    public static string ServerMessage(string? code, string? serverMessage)
    {
        if (!string.IsNullOrWhiteSpace(code) && ServerMessages.TryGetValue(code.Trim(), out var mapped))
        {
            return mapped;
        }

        if (!string.IsNullOrWhiteSpace(serverMessage))
        {
            return serverMessage;
        }

        return code ?? string.Empty;
    }

    public static string FormatSummary(ApiResult result)
    {
        if (result.IsUnreachable)
        {
            return $"Không có phản hồi: {result.Message}";
        }

        var explanation = ServerMessage(result.Code, result.Message);
        var codePart = result.Code.Length > 0 ? " " + result.Code : string.Empty;
        var messagePart = explanation.Length > 0 && !string.Equals(explanation, result.Code, StringComparison.Ordinal)
            ? " - " + explanation
            : string.Empty;
        return $"HTTP {result.Status}{codePart}{messagePart}";
    }

    private static string Of(Dictionary<string, string> names, string code) =>
        names.TryGetValue(code, out var value) ? value : code;
}
