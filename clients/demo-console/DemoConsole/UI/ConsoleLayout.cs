namespace DemoConsole.UI;

/// <summary>
/// Geometry the console can compute without a window, so it can be tested.
/// <para>
/// A <see cref="SplitContainer"/> throws <see cref="InvalidOperationException"/> when
/// <c>SplitterDistance</c> is set outside
/// <c>[Panel1MinSize, Height - Panel2MinSize - SplitterWidth]</c>, and it throws when it
/// is set before the container has a usable size. With <c>FontSize</c> up to 40 the
/// tab header and the status lines grow and the container gets shorter, so the old
/// fixed distance (about 45% of the screen, at least 200 px) became larger than the
/// container and the console crashed on start (audit #17).
/// </para>
/// </summary>
internal static class ConsoleLayout
{
    /// <summary>Smallest height worth giving either pane, in pixels.</summary>
    public const int MinimumPaneHeight = 80;

    /// <summary>
    /// The splitter distance to use for a container of <paramref name="height"/>,
    /// or <c>null</c> when the container is too short for both minimum panes and the
    /// caller must leave the distance alone.
    /// </summary>
    /// <param name="height">The container's client height.</param>
    /// <param name="splitterWidth">The splitter's own thickness.</param>
    /// <param name="panel1MinSize">The container's Panel1MinSize.</param>
    /// <param name="panel2MinSize">The container's Panel2MinSize.</param>
    /// <param name="preferred">The distance the layout would like, usually a fraction of the height.</param>
    public static int? SplitterDistance(int height, int splitterWidth, int panel1MinSize,
                                        int panel2MinSize, int preferred)
    {
        var lowest = Math.Max(panel1MinSize, 0);
        var highest = height - Math.Max(panel2MinSize, 0) - Math.Max(splitterWidth, 0);
        if (highest < lowest)
        {
            // Both panes cannot fit at their minimum size: any value would throw.
            return null;
        }

        return Math.Clamp(preferred, lowest, highest);
    }

    /// <summary>
    /// The preferred distance for the stock pane: a share of the container, never
    /// less than one usable pane.
    /// </summary>
    public static int PreferredStockPaneHeight(int height, double share = 0.45) =>
        Math.Max(MinimumPaneHeight, (int)(height * share));

    /// <summary>
    /// The font size to draw with: the configured size, held inside the range the
    /// configuration allows. Draw code uses this so a hand-edited settings file
    /// cannot ask for a size WinForms refuses.
    /// </summary>
    public static float FontSize(float configured) => Math.Clamp(configured, 8f, 40f);
}
