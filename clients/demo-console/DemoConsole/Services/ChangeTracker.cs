namespace DemoConsole.Services;

/// <summary>
/// Remembers the last value of each row key and when it last changed, so a grid can
/// highlight a row that changed since the previous refresh and keep it highlighted
/// for a few seconds, long enough for the audience to see it.
///
/// The first snapshot is the baseline: nothing is highlighted on the first refresh.
/// A key that appears later counts as a change.
/// </summary>
public sealed class ChangeTracker<TValue>
{
    private readonly Dictionary<string, TValue> _values = new(StringComparer.Ordinal);
    private readonly Dictionary<string, DateTime> _changedAt = new(StringComparer.Ordinal);
    private readonly Dictionary<string, TValue> _previous = new(StringComparer.Ordinal);
    private readonly IEqualityComparer<TValue> _comparer;
    private readonly TimeSpan _hold;
    private bool _hasBaseline;

    public ChangeTracker(TimeSpan hold, IEqualityComparer<TValue>? comparer = null)
    {
        _hold = hold;
        _comparer = comparer ?? EqualityComparer<TValue>.Default;
    }

    /// <summary>Records a full snapshot taken at <paramref name="now"/>; returns the keys that changed in it.</summary>
    public IReadOnlyCollection<string> Update(IReadOnlyDictionary<string, TValue> snapshot, DateTime now)
    {
        var changed = new List<string>();
        foreach (var (key, value) in snapshot)
        {
            if (_values.TryGetValue(key, out var old))
            {
                if (!_comparer.Equals(old, value))
                {
                    _previous[key] = old;
                    changed.Add(key);
                }
            }
            else if (_hasBaseline)
            {
                changed.Add(key);
            }

            _values[key] = value;
        }

        foreach (var gone in _values.Keys.Where(key => !snapshot.ContainsKey(key)).ToList())
        {
            _values.Remove(gone);
            _changedAt.Remove(gone);
            _previous.Remove(gone);
        }

        foreach (var key in changed)
        {
            _changedAt[key] = now;
        }

        _hasBaseline = true;
        return changed;
    }

    public bool IsHighlighted(string key, DateTime now) =>
        _changedAt.TryGetValue(key, out var at) && now - at < _hold;

    /// <summary>The value before the last change, while the row is highlighted.</summary>
    public bool TryGetPrevious(string key, DateTime now, out TValue previous)
    {
        if (IsHighlighted(key, now) && _previous.TryGetValue(key, out previous!))
        {
            return true;
        }

        previous = default!;
        return false;
    }
}
