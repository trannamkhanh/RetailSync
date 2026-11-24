using StaffApp.Models;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

public class RecommendationBoardTests
{
    private static RecommendationBoard Board()
    {
        var board = new RecommendationBoard();
        board.Replace(new[]
        {
            new RecommendationLine(11, "SKU-0006", "DISCOUNT", 50m, null, "PENDING"),
            new RecommendationLine(12, "SKU-0007", "CLEARANCE", null, 8, "PENDING"),
        });
        return board;
    }

    private static ApiResult Ok(string status) =>
        new(200, string.Empty, string.Empty, $$"""{"rec_id":11,"status":"{{status}}","decided_at":"2026-11-20T03:15:00Z"}""");

    [Fact]
    public void Stf47_3_accept_removes_the_row_at_once()
    {
        var board = Board();

        var outcome = board.Apply(11, Ok("ACCEPTED"));

        Assert.Equal((true, false), (outcome.Removed, outcome.Refresh));
        Assert.Equal(new long[] { 12 }, board.Rows.Select(row => row.RecId));
        Assert.Equal("Đề xuất 11: đã chấp nhận", outcome.Message);
    }

    [Fact]
    public void Stf47_4_reject_removes_the_row_at_once()
    {
        var board = Board();

        board.Apply(11, Ok("REJECTED"));

        Assert.DoesNotContain(board.Rows, row => row.RecId == 11);
    }

    [Theory]
    [InlineData("ACCEPTED", "Đề xuất 11: đã chấp nhận")]
    [InlineData("REJECTED", "Đề xuất 11: đã từ chối")]
    [InlineData("ON_HOLD", "Đề xuất 11: ON_HOLD")]
    public void Pb46_5_decision_status_shows_in_vietnamese_and_an_unknown_one_as_sent(string status, string text)
    {
        Assert.Equal(text, Board().Apply(11, Ok(status)).Message);
    }

    [Theory]
    [InlineData(409, "ALREADY_DECIDED", "Đề xuất đã được quyết định")]
    [InlineData(409, "RECOMMENDATION_EXPIRED", "Đề xuất không còn hiệu lực")]
    public void Stf47_5_a_conflict_shows_the_message_and_asks_for_a_refresh(int status, string code, string text)
    {
        var board = Board();

        var outcome = board.Apply(11, new ApiResult(status, code, "m", string.Empty));

        Assert.Equal((true, true, text), (outcome.Removed, outcome.Refresh, outcome.Message));
        Assert.DoesNotContain(board.Rows, row => row.RecId == 11);
    }

    [Theory]
    [InlineData(0)]
    [InlineData(503)]
    [InlineData(401)]
    public void Pb47_other_failures_keep_the_row_for_another_try(int status)
    {
        var board = Board();

        var outcome = board.Apply(11, new ApiResult(status, string.Empty, "down", string.Empty));

        Assert.Equal((false, false), (outcome.Removed, outcome.Refresh));
        Assert.Equal(2, board.Rows.Count);
    }
}
