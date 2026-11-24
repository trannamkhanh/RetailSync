using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>Where a call was made, because 404 means something different on each screen.</summary>
public enum ApiArea
{
    Lookup,
    Alerts,
    Recommendations,
    Detail,
    Decision,
}

/// <summary>A failed call as the user sees it. <c>CanRetry</c> offers Retry; <c>Refresh</c> reloads the list.</summary>
public sealed record UserMessage(string Text, bool CanRetry, bool Refresh);

/// <summary>Maps a failed answer to the DS-08 messages, in Vietnamese ("Token không hợp lệ hoặc đã hết hạn" ...).</summary>
public static class UserMessages
{
    public const string TokenInvalid = "Token không hợp lệ hoặc đã hết hạn";
    public const string Forbidden = "Vai trò này không dùng được chức năng này";
    public const string ProductNotFound = "Không tìm thấy sản phẩm";
    public const string AlreadyDecided = "Đề xuất đã được quyết định";
    public const string NoLongerValid = "Đề xuất không còn hiệu lực";
    public const string NoStores = "Không có cửa hàng nào để tra cứu";
    public const string NoStock = "Không cửa hàng nào còn hàng sản phẩm này";
    public const string NoAlerts = "Không có cảnh báo cận hạn";
    public const string NoRecommendations = "Không có đề xuất cần xử lý";
    public const string InvalidBarcode = "Nhập mã vạch từ 1 đến 30 ký tự: chữ, số hoặc '-'";

    public static UserMessage For(ApiResult result, ApiArea area)
    {
        if (result.IsUnreachable)
        {
            return new UserMessage($"Không kết nối được máy chủ ({result.Message}). Kiểm tra mạng rồi bấm Thử lại.",
                CanRetry: true, Refresh: false);
        }

        return result.Status switch
        {
            401 => new UserMessage(TokenInvalid, false, false),
            403 => new UserMessage(Forbidden, false, false),
            404 when area == ApiArea.Lookup => new UserMessage(ProductNotFound, false, false),
            404 when area is ApiArea.Detail or ApiArea.Decision => new UserMessage(NoLongerValid, false, true),
            409 when result.Code == "ALREADY_DECIDED" => new UserMessage(AlreadyDecided, false, true),
            409 when result.Code == "RECOMMENDATION_EXPIRED" => new UserMessage(NoLongerValid, false, true),
            422 when area == ApiArea.Lookup => new UserMessage(InvalidBarcode, false, false),
            >= 500 => new UserMessage($"Lỗi máy chủ (HTTP {result.Status}). Bấm Thử lại.", true, false),
            _ => new UserMessage(Describe(result), false, false),
        };
    }

    /// <summary>A parse failure of a 2xx answer: the server does not follow DS-04.</summary>
    public static UserMessage Unexpected(FormatException error) =>
        new($"Máy chủ trả lời không đúng định dạng: {error.Message}", CanRetry: true, Refresh: false);

    private static string Describe(ApiResult result)
    {
        var detail = result.Message.Length > 0 ? result.Message : result.Code;
        return detail.Length > 0 ? $"HTTP {result.Status}: {detail}" : $"HTTP {result.Status}";
    }
}
