namespace DemoConsole.UI;

/// <summary>
/// The "is this form still worth drawing to?" decision, apart from the window.
/// <para>
/// A refresh or an action can be in flight when the operator closes the console.
/// The answer then arrives with no form left to draw it on, and touching a disposed
/// control throws <see cref="ObjectDisposedException"/> from inside an async void
/// handler, which closes the process (audit #17). The form asks this object instead
/// of guessing, and the decision is testable without a window.
/// </para>
/// </summary>
internal sealed class PendingWork
{
    private int _closed;
    private int _began;

    /// <summary>True once the window started closing.</summary>
    public bool IsClosed => Volatile.Read(ref _closed) != 0;

    /// <summary>True while at least one call is waiting for its answer.</summary>
    public bool IsBusy => Volatile.Read(ref _began) > 0;

    /// <summary>Records that a call is starting; every Begin needs one completion.</summary>
    public void Begin() => Interlocked.Increment(ref _began);

    /// <summary>Records that the window is closing; later answers are abandoned.</summary>
    public void Close() => Interlocked.Exchange(ref _closed, 1);

    /// <summary>
    /// True when the answer must not be drawn because the window closed first. The
    /// flag is consumed so a later reopen of the same object would draw again.
    /// </summary>
    public bool TryAbandon()
    {
        if (Interlocked.CompareExchange(ref _closed, 0, 1) == 1)
        {
            Interlocked.Decrement(ref _began);
            return true;
        }

        return false;
    }

    /// <summary>
    /// Records a completed call and says whether its result was abandoned. This is
    /// the check every view helper makes after an <c>await</c>.
    /// </summary>
    public bool TryComplete(out bool abandoned)
    {
        abandoned = IsClosed;
        if (Volatile.Read(ref _began) > 0)
        {
            Interlocked.Decrement(ref _began);
        }

        return !abandoned;
    }
}
