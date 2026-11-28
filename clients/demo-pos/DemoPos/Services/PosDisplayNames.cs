using DemoPos.Models;

namespace DemoPos.Services;

/// <summary>
/// Vietnamese display text for server error/result codes, outcomes and event types (PB-51).
/// API payloads, error codes and log files stay English; unknown codes fall back to the server text.
/// </summary>
public static class PosDisplayNames
{
    private static readonly Dictionary<string, string> ServerMessages = new(StringComparer.OrdinalIgnoreCase)
    {
        ["OK"] = "Đã áp dụng giao dịch",
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
        ["INVALID_RESPONSE"] = "Phản hồi từ máy chủ không đúng định dạng JSON",
        ["TIMEOUT"] = "Quá thời gian chờ phản hồi từ cổng POS, vui lòng thử lại cùng mã giao dịch",
        ["NETWORK_ERROR"] = "Không kết nối được tới cổng POS, vui lòng thử lại cùng mã giao dịch",
        ["NO_ANSWER"] = "Không nhận được phản hồi từ máy chủ",
        ["HTTP_400"] = "Cổng POS từ chối yêu cầu (HTTP 400): thiếu hoặc sai chứng chỉ máy khách",
    };

    private static readonly Dictionary<string, string> OutcomeNames = new(StringComparer.OrdinalIgnoreCase)
    {
        ["OK"] = "Thành công",
        ["DUPLICATE"] = "Trùng lặp",
        ["REJECTED"] = "Bị từ chối",
        ["ERROR"] = "Lỗi",
        ["WAITING"] = "Chờ gửi",
    };

    private static readonly Dictionary<string, string> EventTypeNames = new(StringComparer.OrdinalIgnoreCase)
    {
        ["SALE"] = "Bán hàng",
        ["RETURN"] = "Trả hàng",
        ["CANCELLATION"] = "Hủy đơn",
    };

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

    public static string Outcome(PosOutcome outcome) => outcome switch
    {
        PosOutcome.OK => "Thành công",
        PosOutcome.DUPLICATE => "Trùng lặp",
        PosOutcome.REJECTED => "Bị từ chối",
        _ => "Lỗi",
    };

    public static string OutcomeText(string? outcomeCode) =>
        !string.IsNullOrWhiteSpace(outcomeCode) && OutcomeNames.TryGetValue(outcomeCode.Trim(), out var mapped)
            ? mapped
            : outcomeCode ?? string.Empty;

    public static string EventType(string? eventTypeCode) =>
        !string.IsNullOrWhiteSpace(eventTypeCode) && EventTypeNames.TryGetValue(eventTypeCode.Trim(), out var mapped)
            ? mapped
            : eventTypeCode ?? string.Empty;
}
