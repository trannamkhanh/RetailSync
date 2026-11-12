using DemoConsole.Models;
using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class FeatureAvailabilityTests
{
    private static ApiResult Answer(int status, string code = "") => new(status, code, string.Empty, string.Empty, 1);

    [Fact]
    public void A_probe_answered_404_means_not_deployed()
    {
        Assert.Equal(FeatureState.NotDeployed, FeatureAvailability.FromProbe(Answer(404, "NOT_FOUND")));
    }

    [Theory]
    [InlineData(405)]
    [InlineData(200)]
    [InlineData(401)]
    [InlineData(403)]
    [InlineData(503)]
    public void A_probe_answered_anything_else_means_deployed(int status)
    {
        Assert.Equal(FeatureState.Deployed, FeatureAvailability.FromProbe(Answer(status)));
    }

    [Fact]
    public void A_probe_without_an_answer_is_unknown_and_keeps_the_button()
    {
        Assert.Equal(FeatureState.Unknown, FeatureAvailability.FromProbe(Answer(0)));
    }

    [Fact]
    public void Pressing_a_button_answered_404_disables_it()
    {
        Assert.Equal(FeatureState.NotDeployed,
            FeatureAvailability.FromAction(Answer(404, "NOT_FOUND"), FeatureState.Unknown));
    }

    [Theory]
    [InlineData(200)]
    [InlineData(202)]
    [InlineData(409)]
    [InlineData(422)]
    [InlineData(503)]
    public void Pressing_a_button_answered_otherwise_keeps_it(int status)
    {
        Assert.Equal(FeatureState.Deployed, FeatureAvailability.FromAction(Answer(status), FeatureState.Unknown));
    }

    [Fact]
    public void A_merged_feature_is_enabled_again_by_the_next_probe()
    {
        var state = FeatureAvailability.FromProbe(Answer(404));
        Assert.Equal(FeatureState.NotDeployed, state);

        state = FeatureAvailability.FromProbe(Answer(405));

        Assert.Equal(FeatureState.Deployed, state);
    }

    [Fact]
    public void No_answer_after_pressing_keeps_the_previous_state()
    {
        Assert.Equal(FeatureState.Deployed, FeatureAvailability.FromAction(Answer(0), FeatureState.Deployed));
        Assert.Equal(FeatureState.NotDeployed, FeatureAvailability.FromAction(Answer(0), FeatureState.NotDeployed));
    }

    [Fact]
    public void The_reason_says_404_only_when_not_deployed()
    {
        Assert.Contains("404", FeatureAvailability.Reason("Run sync", FeatureState.NotDeployed));
        Assert.Equal(string.Empty, FeatureAvailability.Reason("Run sync", FeatureState.Deployed));
    }
}
