using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class BusinessClockTests
{
    [Fact]
    public void The_business_date_is_utc_plus_seven()
    {
        Assert.Equal(new DateOnly(2026, 11, 14), BusinessClock.Today(new DateTime(2026, 11, 13, 17, 0, 0, DateTimeKind.Utc)));
        Assert.Equal(new DateOnly(2026, 11, 13), BusinessClock.Today(new DateTime(2026, 11, 13, 16, 59, 59, DateTimeKind.Utc)));
    }

    [Theory]
    [InlineData("2026-11-13", "EXPIRED")]
    [InlineData("2026-11-14", "OK, 0 d left")]
    [InlineData("2026-11-16", "OK, 2 d left")]
    public void A_batch_is_expired_only_before_today(string expiry, string expected)
    {
        Assert.Equal(expected, BusinessClock.BatchState(DateOnly.Parse(expiry), new DateOnly(2026, 11, 14)));
    }
}
