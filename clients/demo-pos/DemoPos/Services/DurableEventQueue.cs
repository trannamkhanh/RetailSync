using System.Text.Json;
using DemoPos.Models;

namespace DemoPos.Services;

/// <summary>One terminal's pending and rejected events, persisted before sending.</summary>
public sealed class DurableEventQueue
{
    public sealed record Rejection(string Body, string Code, string Message);
    public sealed class State
    {
        public List<string> Pending { get; set; } = new();
        public List<Rejection> Rejected { get; set; } = new();
    }

    private readonly string _path;
    private readonly object _gate = new();
    private readonly SemaphoreSlim _sender = new(1, 1);
    private State _state;

    public DurableEventQueue(string directory, string posId)
    {
        if (string.IsNullOrWhiteSpace(posId) || posId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || posId is "." or "..")
            throw new ArgumentException("Invalid terminal ID", nameof(posId));
        Directory.CreateDirectory(directory);
        _path = Path.Combine(directory, posId + ".json");
        _state = File.Exists(_path)
            ? JsonSerializer.Deserialize<State>(File.ReadAllText(_path)) ?? throw new InvalidDataException("Empty queue file")
            : new State();
    }

    public int Count { get { lock (_gate) return _state.Pending.Count; } }
    public IReadOnlyList<Rejection> Rejected { get { lock (_gate) return _state.Rejected.ToArray(); } }

    public void Enqueue(string body)
    {
        lock (_gate)
        {
            var next = Copy();
            next.Pending.Add(body);
            Save(next);
        }
    }

    public async Task DrainAsync(Func<string, Task<PosResult>> send, Action<string, PosResult>? completed = null)
    {
        if (!await _sender.WaitAsync(0)) return;
        try
        {
            while (true)
            {
                string body;
                lock (_gate)
                {
                    if (_state.Pending.Count == 0) return;
                    body = _state.Pending[0];
                }
                var result = await send(body);
                if (!result.IsSuccess && (result.CanRetry || result.Outcome != PosOutcome.REJECTED)) return;
                lock (_gate)
                {
                    var next = Copy();
                    if (!result.IsSuccess) next.Rejected.Add(new Rejection(body, result.Code, result.Message));
                    next.Pending.RemoveAt(0);
                    Save(next);
                }
                completed?.Invoke(body, result);
            }
        }
        finally { _sender.Release(); }
    }

    private State Copy() => new() { Pending = new(_state.Pending), Rejected = new(_state.Rejected) };

    private void Save(State next)
    {
        var temp = _path + ".tmp";
        using (var stream = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            JsonSerializer.Serialize(stream, next);
            stream.Flush(flushToDisk: true);
        }
        File.Move(temp, _path, overwrite: true);
        _state = next;
    }
}
