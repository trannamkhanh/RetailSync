using System.Windows.Forms;
using DemoConsole.UI;
using Xunit;

namespace DemoConsole.Tests;

/// <summary>
/// Audit #17: the stock pane and the font size must survive any height the window
/// ends up with, and the clamp must agree with what WinForms itself accepts.
/// </summary>
public class ConsoleLayoutTests
{
    [Theory]
    [InlineData(1000, 8, 200)]
    [InlineData(320, 8, 200)]
    [InlineData(1000, 400, 200)]
    [InlineData(2000, 8, 900)]
    public void Audit17_splitter_distance_stays_inside_the_panel_limits(int height, int panel2MinSize, int preferred)
    {
        var distance = ConsoleLayout.SplitterDistance(height, 8, 25, panel2MinSize, preferred);

        Assert.NotNull(distance);
        Assert.InRange(distance!.Value, 25, height - panel2MinSize - 8);
    }

    [Fact]
    public void Audit17_the_old_screen_based_value_is_outside_the_container_range()
    {
        // The old code asked for about 45% of a 1080 px screen, at least 200 px, and
        // assigned it whatever height the pane actually had. Measured on this
        // runtime, WinForms does not refuse that: it quietly reduces it, so the split
        // ends up wherever the container's own limits put it instead of the share the
        // layout meant. On a 400 px tab those limits are 25 and 367, so the old
        // 486 px request left the stock pane at 367 -- more than twice the 180 px it
        // was supposed to take.
        const int height = 400;
        const int oldValue = 486;
        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(1200, height),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 25;
        var share = ConsoleLayout.PreferredStockPaneHeight(split.Height);

        split.SplitterDistance = oldValue;
        var afterRaw = split.Panel1.Height;

        split.SplitterDistance = ConsoleLayout.SplitterDistance(
            split.Height, split.SplitterWidth, split.Panel1MinSize, split.Panel2MinSize,
            share)!.Value;

        Assert.Equal(180, share);
        Assert.Equal(180, split.Panel1.Height);
        Assert.NotEqual(share, afterRaw);   // the defect: the share is not what was drawn
        Assert.Equal(367, afterRaw);        // WinForms clamped the request silently
    }

    [Fact]
    public void Audit17_a_container_too_short_for_the_share_gets_the_most_it_can()
    {
        // A large font makes the tab shorter than the share the layout wants; the
        // clamp then hands over every pixel the other pane's minimum leaves.
        const int height = 100;
        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(1200, height),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 25;

        var distance = ConsoleLayout.SplitterDistance(
            split.Height, split.SplitterWidth, split.Panel1MinSize, split.Panel2MinSize,
            ConsoleLayout.PreferredStockPaneHeight(split.Height));

        Assert.Equal(height - 25 - 8, distance);
        Assert.True(ConsoleLayout.PreferredStockPaneHeight(height) > distance);
    }

    [Fact]
    public void Audit17_a_negative_or_inverted_range_is_reported_not_assigned()
    {
        // The clamp answers None rather than passing a value WinForms would reject:
        // a negative distance is the one assignment that does throw on this runtime.
        Assert.Null(ConsoleLayout.SplitterDistance(50, 8, 25, 100, 200));

        using var split = new SplitContainer { Orientation = Orientation.Horizontal, SplitterWidth = 8 };
        split.Size = new Size(1200, 240);
        Assert.Throws<ArgumentOutOfRangeException>(() => split.SplitterDistance = -5);
    }

    [Theory]
    [InlineData(120, 25, 200)]
    [InlineData(50, 25, 100)]
    [InlineData(0, 25, 200)]
    public void Audit17_a_container_too_short_for_both_panes_reports_no_distance(int height, int panel2MinSize,
                                                                                int panel1MinSize)
    {
        Assert.Null(ConsoleLayout.SplitterDistance(height, 8, panel1MinSize, panel2MinSize, 200));
    }

    [Fact]
    public void Audit17_the_preferred_height_never_drops_below_a_usable_pane()
    {
        Assert.Equal(ConsoleLayout.MinimumPaneHeight, ConsoleLayout.PreferredStockPaneHeight(120));
        Assert.Equal(540, ConsoleLayout.PreferredStockPaneHeight(1200));
    }

    [Theory]
    [InlineData(1f, 8f)]
    [InlineData(8f, 8f)]
    [InlineData(13f, 13f)]
    [InlineData(40f, 40f)]
    [InlineData(64f, 40f)]
    public void Audit17_the_font_size_is_clamped_to_the_configured_range(float configured, float expected)
    {
        Assert.Equal(expected, ConsoleLayout.FontSize(configured));
    }

    [Fact]
    public void Audit17_a_real_split_container_accepts_what_the_clamp_returns()
    {
        // The geometry has to agree with WinForms, not just with itself.
        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(800, 240),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 100;

        var distance = ConsoleLayout.SplitterDistance(split.Height, split.SplitterWidth,
            split.Panel1MinSize, split.Panel2MinSize, 486);

        split.SplitterDistance = distance!.Value;

        Assert.Equal(distance.Value, split.SplitterDistance);
    }

    [Fact]
    public void Audit17_a_shrunk_window_clamps_the_operators_own_position()
    {
        // What ApplyStockSplit does on a resize after a drag: keep the position,
        // clamp it into range, never recompute the share.
        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(1200, 900),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 100;
        split.SplitterDistance = 700;

        var shrunk = 400;
        var clamped = ConsoleLayout.SplitterDistance(shrunk, split.SplitterWidth,
            split.Panel1MinSize, split.Panel2MinSize, split.SplitterDistance);

        Assert.Equal(400 - 100 - 8, clamped);
    }
}
