using System.Text;
using System.Text.Json;
using DemoPos.Models;

namespace DemoPos.Services;

/// <summary>
/// Append-only journal for one terminal: an event is on disk before its first network send, and the
/// sender always works on the head of the queue so events go out in order.
/// </summary>
public sealed class DurableEventQueue
{
    public sealed record Entry(string Id, string Body);

    public sealed record Rejection(string Body, string Code, string Message, int HttpStatus);

    public sealed class State
    {
        public List<Entry> Pending { get; set; } = new();

        public List<Rejection> Rejected { get; set; } = new();
    }

    private sealed record JournalRecord(
        string Kind,
        Entry? Entry = null,
        string? Id = null,
        Rejection? Rejection = null,
        State? Snapshot = null);

    /// <summary>
    /// Retries while the link is unavailable or the stack is restarting: no answer at all (0) and
    /// every 5xx answer (the gateway answers 502/504 while the middleware restarts, and 503 when it
    /// is unavailable), plus the transport error codes. Every other answer that cannot succeed (the
    /// gateway's 400 without a certificate, a non-JSON body, another 4xx) is settled as rejected, so
    /// it can never block the events behind it.
    /// </summary>
    public static bool ShouldRetry(PosResult result) =>
        !result.IsSuccess
        && (result.HttpStatus is 0 or >= 500
            || result.Code is "NO_ANSWER" or "TIMEOUT" or "NETWORK_ERROR" or "SERVICE_UNAVAILABLE");

    private const int CompactThresholdBytes = 64 * 1024;

    private readonly string _path;
    private readonly string _journalLockPath;
    private readonly string _senderLockPath;
    private readonly object _gate = new();

    public DurableEventQueue(string directory, string posId)
    {
        if (string.IsNullOrWhiteSpace(posId)
            || posId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0
            || posId is "." or "..")
        {
            throw new ArgumentException("Invalid terminal ID", nameof(posId));
        }

        Directory.CreateDirectory(directory);
        _path = Path.Combine(directory, posId + ".jsonl");
        _journalLockPath = Path.Combine(directory, posId + ".journal.lock");
        _senderLockPath = Path.Combine(directory, posId + ".sender.lock");

        // Fail visibly on corruption; never discard a valid pending event.
        var state = ReadState();
        if (state.Pending.Count == 0 && File.Exists(_path) && new FileInfo(_path).Length > CompactThresholdBytes)
        {
            Compact();
        }
    }

    public int Count => ReadState().Pending.Count;

    public IReadOnlyList<Rejection> Rejected => ReadState().Rejected.ToArray();

    /// <summary>Appends the event and flushes it to disk. Returns the id used to settle the event.</summary>
    public string Enqueue(string body)
    {
        var entry = new Entry(Guid.NewGuid().ToString("N"), body);
        lock (_gate)
        {
            using var journalLock = AcquireJournalLock();
            using var file = OpenJournal();
            Load(file);
            Append(file, new JournalRecord("enqueue", Entry: entry));
        }

        return entry.Id;
    }

    /// <summary>
    /// Sends the head until the queue is empty or an answer says "try later". A retryable answer keeps
    /// the head in place and stops this cycle, so no event is reordered. Returns the last answer, or
    /// null when nothing was sent (empty queue or another sender holds the terminal).
    /// </summary>
    public async Task<PosResult?> DrainAsync(Func<Entry, Task<PosResult>> send,
                                             Action<Entry, PosResult>? settled = null)
    {
        FileStream lease;
        try
        {
            lease = new FileStream(_senderLockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        }
        catch (IOException error) when ((error.HResult & 0xffff) is 32 or 33)
        {
            return null;
        }

        using (lease)
        {
            PosResult? last = null;
            while (true)
            {
                var entry = ReadState().Pending.FirstOrDefault();
                if (entry is null)
                {
                    return last;
                }

                var result = await send(entry);
                last = result;
                if (ShouldRetry(result))
                {
                    return last;
                }

                Settle(entry, result);
                settled?.Invoke(entry, result);
            }
        }
    }

    /// <summary>Rewrites the journal as one snapshot when nothing waits; the rejected list is kept.</summary>
    public void Compact()
    {
        lock (_gate)
        {
            using var journalLock = AcquireJournalLock();
            var state = LoadFromDisk();
            if (state.Pending.Count == 0)
            {
                WriteSnapshot(state);
            }
        }
    }

    private void Settle(Entry entry, PosResult result)
    {
        var rejection = result.IsSuccess
            ? null
            : new Rejection(entry.Body, result.Code, result.Message, result.HttpStatus);

        lock (_gate)
        {
            using var journalLock = AcquireJournalLock();
            State state;
            using (var file = OpenJournal())
            {
                state = Load(file);
                if (state.Pending.FirstOrDefault()?.Id != entry.Id)
                {
                    throw new InvalidDataException("Queue head changed while sending");
                }

                Append(file, new JournalRecord("settle", Id: entry.Id, Rejection: rejection));
                state.Pending.RemoveAt(0);
                if (rejection is not null)
                {
                    state.Rejected.Add(rejection);
                }
            }

            // Compact while the journal lock is held, so a concurrent Enqueue cannot lose its append.
            if (state.Pending.Count == 0)
            {
                WriteSnapshot(state);
            }
        }
    }

    private void WriteSnapshot(State state)
    {
        var temporary = _path + ".compact";
        try
        {
            // Complete file first, then replace: a crash leaves either the old journal or this one.
            File.WriteAllText(temporary,
                JsonSerializer.Serialize(new JournalRecord("snapshot", Snapshot: state)) + "\n",
                new UTF8Encoding(false));
            File.Move(temporary, _path, overwrite: true);
        }
        catch (IOException)
        {
            // Compaction is housekeeping; a failed replace must not fail the settled event.
            try { File.Delete(temporary); } catch (IOException) { }
        }
    }

    private State ReadState()
    {
        lock (_gate)
        {
            using var journalLock = AcquireJournalLock();
            return LoadFromDisk();
        }
    }

    private State LoadFromDisk()
    {
        using var file = OpenJournal();
        return Load(file);
    }

    private FileStream OpenJournal()
    {
        // Brief contention with another process is retried; prolonged contention fails without
        // accepting the sale, never by dropping the tail of the journal.
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                return new FileStream(_path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch (IOException error) when (attempt < 100 && (error.HResult & 0xffff) is 32 or 33)
            {
                Thread.Sleep(10);
            }
        }
    }

    private FileStream AcquireJournalLock()
    {
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                return new FileStream(_journalLockPath, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch (IOException error) when (attempt < 200 && (error.HResult & 0xffff) is 32 or 33)
            {
                Thread.Sleep(5);
            }
        }
    }

    private State Load(FileStream file)
    {
        file.Position = 0;
        using var memory = new MemoryStream();
        file.CopyTo(memory);
        var bytes = memory.ToArray();
        var end = Array.LastIndexOf(bytes, (byte)'\n') + 1;
        if (end != bytes.Length)
        {
            // A crash can leave an incomplete final record; it was never acknowledged to the UI.
            file.SetLength(end);
            file.Flush(true);
        }

        var state = new State();
        foreach (var line in Encoding.UTF8.GetString(bytes, 0, end).Split('\n', StringSplitOptions.RemoveEmptyEntries))
        {
            var record = JsonSerializer.Deserialize<JournalRecord>(line)
                         ?? throw new InvalidDataException("Empty journal record");
            switch (record.Kind)
            {
                case "snapshot" when record.Snapshot is not null:
                    state = record.Snapshot;
                    break;
                case "enqueue" when record.Entry is not null:
                    state.Pending.Add(record.Entry);
                    break;
                case "settle" when state.Pending.FirstOrDefault()?.Id == record.Id:
                    if (record.Rejection is not null)
                    {
                        state.Rejected.Add(record.Rejection);
                    }

                    state.Pending.RemoveAt(0);
                    break;
                default:
                    throw new InvalidDataException("Invalid queue journal record");
            }
        }

        file.Position = file.Length;
        return state;
    }

    private static void Append(FileStream file, JournalRecord record)
    {
        var start = file.Length;
        try
        {
            file.Position = start;
            var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(record) + "\n");
            file.Write(bytes);
            file.Flush(true);
        }
        catch
        {
            file.SetLength(start);
            file.Flush(true);
            throw;
        }
    }
}
