namespace StaffApp.Services;

/// <summary>
/// The Vietnamese text every tab shows for an API code (PB-41-3). Only the display changes: the API, the
/// requests and the models keep the codes. An unknown code is shown as it is.
/// </summary>
public static class DisplayNames
{
    private static readonly Dictionary<string, string> BalanceStatuses = new()
    {
        ["SURPLUS"] = "Thừa hàng", ["SHORTAGE"] = "Thiếu hàng", ["BALANCED"] = "Cân bằng",
    };

    private static readonly Dictionary<string, string> AlertTypes = new()
    {
        ["EXPIRED"] = "Đã hết hạn", ["NEAR_EXPIRY"] = "Sắp hết hạn",
    };

    private static readonly Dictionary<string, string> RuleTypes = new()
    {
        ["MIN_SHELF_LIFE"] = "Hạn dùng tối thiểu", ["MAX_DISCOUNT"] = "Giảm giá tối đa", ["MIN_PRICE"] = "Giá tối thiểu",
    };

    private static readonly Dictionary<string, string> Outcomes = new()
    {
        ["PASSED"] = "Đạt", ["ADJUSTED"] = "Điều chỉnh", ["BLOCKED"] = "Chặn",
    };

    private static readonly Dictionary<string, string> Categories = new()
    {
        ["Dairy"] = "Sữa", ["Bakery"] = "Bánh tươi", ["Dry goods"] = "Hàng khô",
        ["Beverages"] = "Đồ uống", ["Snacks"] = "Bánh kẹo", ["Frozen"] = "Đồ đông lạnh",
    };

    private static readonly Dictionary<string, string> ActionTypes = new()
    {
        ["DISCOUNT"] = "Giảm giá", ["CLEARANCE"] = "Thanh lý", ["REDISTRIBUTION"] = "Điều chuyển",
    };

    // Lower case: shown inside a sentence, "Đề xuất 11: đã chấp nhận".
    private static readonly Dictionary<string, string> DecisionStatuses = new()
    {
        ["ACCEPTED"] = "đã chấp nhận", ["REJECTED"] = "đã từ chối",
    };

    public static string BalanceStatus(string code) => Of(BalanceStatuses, code);

    public static string AlertType(string code) => Of(AlertTypes, code);

    public static string RuleType(string code) => Of(RuleTypes, code);

    public static string Outcome(string code) => Of(Outcomes, code);

    public static string Category(string code) => Of(Categories, code);

    public static string ActionType(string code) => Of(ActionTypes, code);

    public static string DecisionStatus(string code) => Of(DecisionStatuses, code);

    private static string Of(Dictionary<string, string> names, string code) => names.GetValueOrDefault(code, code);
}
