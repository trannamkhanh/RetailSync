using StaffApp.Models;

namespace StaffApp.Services;

/// <summary>What the screen does after a decision call.</summary>
public sealed record DecisionOutcome(bool Removed, bool Refresh, string Message);

/// <summary>
/// The rows of the Recommendations screen. A successful decision removes its row at once
/// (STF47-3, 47-4); a 409 or 404 shows the DS-08 message and asks for a refresh (STF47-5);
/// any other failure keeps the row so the user can try again.
/// </summary>
public sealed class RecommendationBoard
{
    private readonly List<RecommendationLine> _rows = new();

    public IReadOnlyList<RecommendationLine> Rows => _rows;

    public void Replace(IEnumerable<RecommendationLine> rows)
    {
        _rows.Clear();
        _rows.AddRange(rows);
    }

    public DecisionOutcome Apply(long recId, ApiResult result)
    {
        if (result.IsSuccess)
        {
            string status;
            try
            {
                status = ApiParsers.Decision(result.Body).Status;
            }
            catch (FormatException)
            {
                status = "đã quyết định";
            }

            _rows.RemoveAll(row => row.RecId == recId);
            return new DecisionOutcome(true, false, $"Đề xuất {recId}: {status}");
        }

        var message = UserMessages.For(result, ApiArea.Decision);
        if (message.Refresh)
        {
            _rows.RemoveAll(row => row.RecId == recId);
        }

        return new DecisionOutcome(message.Refresh, message.Refresh, message.Text);
    }
}
