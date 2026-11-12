using DemoConsole.Services;
using Xunit;

namespace DemoConsole.Tests;

public class ChangeTrackerTests
{
    private static readonly DateTime T0 = new(2026, 11, 14, 2, 0, 0, DateTimeKind.Utc);

    private static Dictionary<string, int> Stock(int milk, int bread) =>
        new() { ["STORE-DN1|SKU-0001"] = milk, ["STORE-DN1|SKU-0004"] = bread };

    [Fact]
    public void The_first_refresh_is_the_baseline()
    {
        var tracker = new ChangeTracker<int>(TimeSpan.FromSeconds(15));

        var changed = tracker.Update(Stock(40, 40), T0);

        Assert.Empty(changed);
        Assert.False(tracker.IsHighlighted("STORE-DN1|SKU-0001", T0));
    }

    [Fact]
    public void A_changed_quantity_is_highlighted_with_its_previous_value()
    {
        var tracker = new ChangeTracker<int>(TimeSpan.FromSeconds(15));
        tracker.Update(Stock(40, 40), T0);

        var changed = tracker.Update(Stock(38, 40), T0.AddSeconds(3));

        Assert.Equal(new[] { "STORE-DN1|SKU-0001" }, changed);
        Assert.True(tracker.IsHighlighted("STORE-DN1|SKU-0001", T0.AddSeconds(3)));
        Assert.False(tracker.IsHighlighted("STORE-DN1|SKU-0004", T0.AddSeconds(3)));
        Assert.True(tracker.TryGetPrevious("STORE-DN1|SKU-0001", T0.AddSeconds(3), out var previous));
        Assert.Equal(40, previous);
    }

    [Fact]
    public void The_highlight_stays_for_the_hold_time_then_goes()
    {
        var tracker = new ChangeTracker<int>(TimeSpan.FromSeconds(15));
        tracker.Update(Stock(40, 40), T0);
        tracker.Update(Stock(38, 40), T0.AddSeconds(3));

        tracker.Update(Stock(38, 40), T0.AddSeconds(6));

        Assert.True(tracker.IsHighlighted("STORE-DN1|SKU-0001", T0.AddSeconds(17)));
        Assert.False(tracker.IsHighlighted("STORE-DN1|SKU-0001", T0.AddSeconds(18)));
        Assert.False(tracker.TryGetPrevious("STORE-DN1|SKU-0001", T0.AddSeconds(18), out _));
    }

    [Fact]
    public void A_new_row_after_the_baseline_is_a_change()
    {
        var tracker = new ChangeTracker<string>(TimeSpan.FromSeconds(15));
        tracker.Update(new Dictionary<string, string> { ["TXN-1"] = "OK|" }, T0);

        var changed = tracker.Update(new Dictionary<string, string> { ["TXN-1"] = "OK|", ["TXN-2"] = "OK|" }, T0.AddSeconds(3));

        Assert.Equal(new[] { "TXN-2" }, changed);
        Assert.True(tracker.IsHighlighted("TXN-2", T0.AddSeconds(3)));
        Assert.False(tracker.TryGetPrevious("TXN-2", T0.AddSeconds(3), out _));
    }

    [Fact]
    public void A_status_change_of_a_sync_batch_is_highlighted()
    {
        var tracker = new ChangeTracker<string>(TimeSpan.FromSeconds(15));
        tracker.Update(new Dictionary<string, string> { ["SB-1"] = "PENDING|1|HQ_OFFLINE" }, T0);

        var changed = tracker.Update(new Dictionary<string, string> { ["SB-1"] = "ACKED|2|" }, T0.AddSeconds(3));

        Assert.Equal(new[] { "SB-1" }, changed);
    }

    [Fact]
    public void A_row_that_goes_away_and_comes_back_is_new_again()
    {
        var tracker = new ChangeTracker<int>(TimeSpan.FromSeconds(15));
        tracker.Update(Stock(40, 40), T0);
        tracker.Update(new Dictionary<string, int> { ["STORE-DN1|SKU-0001"] = 40 }, T0.AddSeconds(3));

        var changed = tracker.Update(Stock(40, 40), T0.AddSeconds(6));

        Assert.Equal(new[] { "STORE-DN1|SKU-0004" }, changed);
    }

    [Fact]
    public void A_zero_hold_never_highlights()
    {
        var tracker = new ChangeTracker<int>(TimeSpan.Zero);
        tracker.Update(Stock(40, 40), T0);
        tracker.Update(Stock(38, 40), T0.AddSeconds(3));

        Assert.False(tracker.IsHighlighted("STORE-DN1|SKU-0001", T0.AddSeconds(3)));
    }
}
