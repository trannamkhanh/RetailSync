using StaffApp.Services;
using Xunit;

namespace StaffApp.Tests;

public class LatestRequestTests
{
    [Fact]
    public void Pb47_only_the_newest_detail_request_is_current()
    {
        var requests = new LatestRequest();

        var first = requests.Next();
        var second = requests.Next();

        Assert.False(requests.IsCurrent(first));
        Assert.True(requests.IsCurrent(second));
    }

    [Fact]
    public void Pb47_rebuilding_the_list_drops_an_answer_still_in_flight()
    {
        var requests = new LatestRequest();
        var ticket = requests.Next();

        requests.Invalidate();

        Assert.False(requests.IsCurrent(ticket));
    }
}
