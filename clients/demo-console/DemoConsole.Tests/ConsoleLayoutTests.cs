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
    public void Splitter_distance_stays_inside_the_panel_limits(int height, int panel2MinSize, int preferred)
    {
        var distance = ConsoleLayout.SplitterDistance(height, 8, 25, panel2MinSize, preferred);

        Assert.NotNull(distance);
        Assert.InRange(distance!.Value, 25, height - panel2MinSize - 8);
    }

    [Fact]
    public void The_old_fixed_distance_is_clamped_instead_of_throwing()
    {
        // The crash: about 45% of a 1080 px screen, at least 200 px, in a short pane.
        const int shortHeight = 240;

        var distance = ConsoleLayout.SplitterDistance(shortHeight, 8, 25, 100, 486);

        Assert.Equal(shortHeight - 100 - 8, distance);
    }

    [Theory]
    [InlineData(120, 25, 200)]
    [InlineData(50, 25, 100)]
    [InlineData(0, 25, 200)]
    public void A_container_too_short_for_both_panes_reports_no_distance(int height, int panel2MinSize,
                                                                       int panel1MinSize)
    {
        Assert.Null(ConsoleLayout.SplitterDistance(height, 8, panel1MinSize, panel2MinSize, 200));
    }

    [Fact]
    public void The_preferred_height_never_drops_below_a_usable_pane()
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
    public void The_font_size_is_clamped_to_the_configured_range(float configured, float expected)
    {
        Assert.Equal(expected, ConsoleLayout.FontSize(configured));
    }

    [Fact]
    public void A_real_split_container_accepts_what_the_clamp_returns()
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
}
