using DemoConsole.UI;
using Xunit;

namespace DemoConsole.Tests;

/// <summary>
/// Audit #17: the sizes the configuration allows (up to 40) must lay out without
/// throwing, and a close while a request is pending must not touch a disposed form.
/// <para>
/// These are headless tests. The layout helpers are pure geometry and are checked
/// against a real <see cref="SplitContainer"/>, and the close behaviour is exercised
/// through <see cref="PendingWork"/>, the small guard the form itself uses.
/// </para>
/// </summary>
public class MainFormLayoutTests
{
    [Theory]
    [InlineData(30f)]
    [InlineData(40f)]
    public void The_largest_configured_fonts_still_lay_out_a_stock_split(float fontSize)
    {
        // At font 40 the header and status lines grow, so the container is shorter
        // than the 45%-of-screen distance the old code used.
        const int shortContainer = 300;

        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(1200, shortContainer),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 100;

        var preferred = ConsoleLayout.PreferredStockPaneHeight(split.Height);
        var distance = ConsoleLayout.SplitterDistance(split.Height, split.SplitterWidth,
            split.Panel1MinSize, split.Panel2MinSize, preferred);

        Assert.NotNull(distance);
        split.SplitterDistance = distance!.Value;
        Assert.Equal(distance.Value, split.SplitterDistance);
        Assert.True(split.Panel1.Height >= split.Panel1MinSize);
        Assert.True(split.Panel2.Height >= split.Panel2MinSize);
        Assert.Equal(fontSize, ConsoleLayout.FontSize(fontSize));
    }

    [Fact]
    public void The_stock_pane_does_not_shrink_to_a_few_pixels()
    {
        // The audit's symptom: the pane became 22 px because the distance was larger
        // than the container. Clamping keeps it usable.
        using var split = new SplitContainer
        {
            Orientation = Orientation.Horizontal,
            SplitterWidth = 8,
            Size = new Size(1200, 900),
        };
        split.Panel1MinSize = 25;
        split.Panel2MinSize = 100;

        split.SplitterDistance = ConsoleLayout.SplitterDistance(
            split.Height, split.SplitterWidth, split.Panel1MinSize, split.Panel2MinSize, 2000)!.Value;

        Assert.True(split.Panel2.Height >= 100, $"Panel2 was {split.Panel2.Height}");
    }

    [Fact]
    public void A_close_during_a_pending_call_reports_that_the_work_was_abandoned()
    {
        var work = new PendingWork();
        work.Begin();

        work.Close();

        Assert.True(work.IsClosed);
        Assert.False(work.TryComplete(out _), "a closed form must not draw an answer");
        Assert.True(work.TryAbandon());
        Assert.False(work.TryAbandon(), "the close reason is recorded once");
    }

    [Fact]
    public void A_completed_call_before_the_close_still_draws()
    {
        var work = new PendingWork();
        work.Begin();

        Assert.True(work.TryComplete(out var abandoned));
        Assert.False(abandoned);
        Assert.False(work.IsClosed);
    }

    [Theory]
    [InlineData(1f)]
    [InlineData(7.9f)]
    [InlineData(40.1f)]
    [InlineData(200f)]
    public void A_hand_edited_font_outside_the_range_is_clamped(float configured)
    {
        // ConfigLoader refuses these, but a Local override or a stale build must not
        // be able to reach WinForms with a size it rejects.
        var size = ConsoleLayout.FontSize(configured);

        Assert.InRange(size, 8f, 40f);
    }

    [Fact]
    public void The_snapshot_body_is_iso_8601_whatever_the_machine_culture()
    {
        var previous = Thread.CurrentThread.CurrentCulture;
        try
        {
            // th-TH defaults to the Buddhist calendar, which would print year 2569.
            Thread.CurrentThread.CurrentCulture = new System.Globalization.CultureInfo("th-TH");
            var body = Services.DemoApiClient.SnapshotSample(new DateTime(2026, 11, 21, 3, 15, 0, DateTimeKind.Utc));

            Assert.Contains("\"taken_at\":\"2026-11-21T03:15:00Z\"", body);
        }
        finally
        {
            Thread.CurrentThread.CurrentCulture = previous;
        }
    }
}
