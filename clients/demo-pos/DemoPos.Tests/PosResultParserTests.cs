using DemoPos.Models;
using Xunit;

namespace DemoPos.Tests;

public sealed class PosResultParserTests
{
    [Fact]
    public void ParsesAnOkResult()
    {
        var result = PosResultParser.Parse(
            """{"outcome":"OK","code":"OK","message":"Event applied","current_stock":{"SKU-0001":38}}""",
            200, 12.34);

        Assert.Equal(PosOutcome.OK, result.Outcome);
        Assert.Equal("OK", result.Code);
        Assert.Equal(38, result.CurrentStock["SKU-0001"]);
        Assert.True(result.IsSuccess);
        Assert.False(result.CanRetry);
        Assert.Equal(12.3, result.ElapsedMs);
    }

    [Fact]
    public void ParsesADuplicateResult()
    {
        var result = PosResultParser.Parse(
            """{"outcome":"DUPLICATE","code":"DUPLICATE_IGNORED","message":"Transaction already recorded","current_stock":{"SKU-0001":38}}""",
            200, 7);

        Assert.Equal(PosOutcome.DUPLICATE, result.Outcome);
        Assert.True(result.IsSuccess);
        Assert.Equal("DUPLICATE_IGNORED", result.Code);
    }

    [Fact]
    public void ParsesARejectedErrorBody()
    {
        var result = PosResultParser.Parse(
            """{"outcome":"REJECTED","code":"INSUFFICIENT_STOCK","message":"Not enough stock."}""",
            409, 9);

        Assert.Equal(PosOutcome.REJECTED, result.Outcome);
        Assert.Equal("INSUFFICIENT_STOCK", result.Code);
        Assert.False(result.CanRetry);
    }

    [Fact]
    public void HandlesANonJsonGatewayBody()
    {
        var result = PosResultParser.Parse(
            "<html><head><title>400 No required SSL certificate was sent</title></head></html>",
            400, 4);

        Assert.Equal(PosOutcome.REJECTED, result.Outcome);
        Assert.Equal("HTTP_400", result.Code);
        Assert.Contains("400", result.Message);
    }

    [Fact]
    public void Treats503AsRetryable()
    {
        var result = PosResultParser.Parse(
            """{"outcome":"ERROR","code":"SERVICE_UNAVAILABLE","message":"Try again later."}""",
            503, 3);

        Assert.Equal(PosOutcome.ERROR, result.Outcome);
        Assert.True(result.CanRetry);
    }

    [Fact]
    public void TreatsAGateway502AsRetryable()
    {
        var result = PosResultParser.Parse("<html><title>502 Bad Gateway</title></html>", 502, 3);

        Assert.Equal(PosOutcome.ERROR, result.Outcome);
        Assert.True(result.CanRetry);
    }

    [Fact]
    public void NetworkErrorIsRetryable()
    {
        var result = PosResultParser.NetworkError("TIMEOUT", "No answer.", 5000);

        Assert.Equal(PosOutcome.ERROR, result.Outcome);
        Assert.Equal(0, result.HttpStatus);
        Assert.True(result.CanRetry);
    }

    [Fact]
    public void NonJson200IsNotTreatedAsSuccess()
    {
        var result = PosResultParser.Parse("not json", 200, 1);

        Assert.Equal(PosOutcome.ERROR, result.Outcome);
        Assert.Equal("INVALID_RESPONSE", result.Code);
        Assert.False(result.IsSuccess);
    }
}
