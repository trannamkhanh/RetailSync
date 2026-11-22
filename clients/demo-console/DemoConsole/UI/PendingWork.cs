namespace DemoConsole.UI;

/// <summary>
/// The "is this form still worth drawing to?" decision, apart from the window.
/// <para>
/// A refresh or an action can be in flight when the operator closes the console.
/// The answer then arrives with no form left to draw it on, and touching a
/// disposed control throws <see cref="ObjectDisposedException"/> from inside an
/// async void handler, which closes the process (audit #17). The form asks this
/// object instead of guessing, and the decision is testable without a window.
/// </para>
/// <para>
/// Once closed, always closed: a WinForms form is disposed on close and never
/// reopened, so the flag is only ever set, never cleared. Clearing it made a
/// second in-flight answer look like it could still draw -- with two calls
/// pending at close, the first one's <see cref="TryAbandon"/> reset the flag and
/// the second then wrote to disposed controls, which is the crash this type
/// exists to prevent (review of PR #79).
/// </para>
/// </summary>
internal sealed class PendingWork
{
    private int _closed;
    private int _began;

    /// <summary>True once the window started closing; stays true afterwards.</summary>
    public bool IsClosed => Volatile.Read(ref _closed) != 0;

    /// <summary>True while at least one call is waiting for its answer.</summary>
    public bool IsBusy => Volatile.Read(ref _began) > 0;

    /// <summary>Records that a call is starting; every Begin needs one completion.</summary>
    public void Begin() => Interlocked.Increment(ref _began);

    /// <summary>Records that the window is closing. Idempotent, and never undone.</summary>
    public void Close() => Interlocked.Exchange(ref _closed, 1);

    /// <summary>
    /// Records that a call ended without being drawn, and says whether that was
    /// because the window had closed. The closed flag is left set, so every other
    /// call that was in flight sees it too.
    /// </summary>
    public bool TryAbandon()
    {
        if (!IsClosed)
        {
            return false;
        }

        Complete();
        return true;
    }

    /// <summary>
    /// Records a completed call and says whether its result was abandoned. This is
    /// the check every view helper makes after an <c>await</c>.
    /// </summary>
    public bool TryComplete(out bool abandoned)
    {
        abandoned = IsClosed;
        Complete();
        return !abandoned;
    }

    /// <summary>Counts one call out, never below zero.</summary>
    private void Complete()
    {
        if (Interlocked.Decrement(ref _began) < 0)
        {
            Interlocked.Increment(ref _began);
        }
    }
}
