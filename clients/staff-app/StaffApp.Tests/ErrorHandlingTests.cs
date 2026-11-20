using StaffApp.Models;
using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

public class ErrorHandlingTests
{
    private static ApiResult Answer(int status, string code = "") => new(status, code, string.Empty, string.Empty);

    [Theory]
    [InlineData(ApiArea.Lookup)]
    [InlineData(ApiArea.Alerts)]
    [InlineData(ApiArea.Recommendations)]
    [InlineData(ApiArea.Decision)]
    public void Stf46_5_401_shows_token_invalid_or_expired_on_every_screen(ApiArea area)
    {
        Assert.Equal("Token invalid or expired", UserMessages.For(Answer(401), area).Text);
    }

    [Fact]
    public void Stf46_3_unknown_barcode_shows_product_not_found()
    {
        Assert.Equal("Product not found", UserMessages.For(Answer(404, "NOT_FOUND"), ApiArea.Lookup).Text);
    }

    [Fact]
    public void Pb46_403_shows_the_role_message()
    {
        Assert.Equal("This role cannot use this function", UserMessages.For(Answer(403), ApiArea.Alerts).Text);
    }

    [Fact]
    public void Stf47_5_already_decided_shows_the_message_and_refreshes()
    {
        var message = UserMessages.For(Answer(409, "ALREADY_DECIDED"), ApiArea.Decision);

        Assert.Equal(("Already decided", true), (message.Text, message.Refresh));
    }

    [Theory]
    [InlineData(409, "RECOMMENDATION_EXPIRED")]
    [InlineData(404, "NOT_FOUND")]
    public void Pb47_expired_or_gone_shows_no_longer_valid_and_refreshes(int status, string code)
    {
        var message = UserMessages.For(Answer(status, code), ApiArea.Decision);

        Assert.Equal(("No longer valid", true), (message.Text, message.Refresh));
    }

    [Fact]
    public void Pb46_network_error_offers_retry_and_keeps_the_screen()
    {
        var message = UserMessages.For(new ApiResult(0, string.Empty, "Could not connect to 10.0.0.5:8443.", string.Empty),
            ApiArea.Alerts);

        Assert.True(message.CanRetry);
        Assert.False(message.Refresh);
        Assert.Contains("Cannot reach the server", message.Text);
    }

    [Fact]
    public void Pb46_server_error_offers_retry()
    {
        var message = UserMessages.For(Answer(503, "SERVICE_UNAVAILABLE"), ApiArea.Recommendations);

        Assert.True(message.CanRetry);
        Assert.Contains("503", message.Text);
    }

    [Theory]
    [InlineData("8930000000011", true)]
    [InlineData("ABC-123", true)]
    [InlineData("", false)]
    [InlineData("bad code", false)]
    [InlineData("1234567890123456789012345678901", false)]
    public void Pb46_barcode_follows_the_ds04_pattern(string barcode, bool valid)
    {
        Assert.Equal(valid, StaffApiClient.IsValidBarcode(barcode));
    }
}
