namespace StaffApp.Services;

/// <summary>
/// Keeps only the newest request current. A screen takes a ticket before an async call and
/// drops the answer when <see cref="IsCurrent"/> is false, so a slow answer for a row the
/// user already left never replaces the details of the row now selected.
/// </summary>
public sealed class LatestRequest
{
    private int _current;

    /// <summary>Starts a new request; every earlier ticket becomes stale.</summary>
    public int Next() => ++_current;

    /// <summary>Makes every ticket stale without starting a request (the list was rebuilt).</summary>
    public void Invalidate() => _current++;

    public bool IsCurrent(int ticket) => ticket == _current;

    /// <summary>True when an answer may still be shown: the ticket is current and the window is not gone
    /// (closed or disposed while the call ran).</summary>
    public bool Applies(int ticket, bool windowGone) => !windowGone && IsCurrent(ticket);
}
