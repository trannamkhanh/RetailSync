using System.Text;
using System.Text.Json;
using DemoPos.Models;

namespace DemoPos.Services;

public enum QueueDelivery { Gateway, WrongCertificate, NoCertificate, SkipGateway }

/// <summary>Append-only journal; a durable enqueue precedes every network send.</summary>
public sealed class DurableEventQueue
{
    public sealed record Entry(string Id, string Body, QueueDelivery Delivery = QueueDelivery.Gateway, string? CertificatePosId = null);
    public sealed record Rejection(string Body, string Code, string Message);
    public sealed class State
    {
        public List<Entry> Pending { get; set; } = new();
        public List<Rejection> Rejected { get; set; } = new();
    }
    private sealed record JournalRecord(string Kind, Entry? Entry = null, string? Id = null, Rejection? Rejection = null, State? Snapshot = null);
    private sealed class LegacyState
    {
        public List<string> Pending { get; set; } = new();
        public List<Rejection> Rejected { get; set; } = new();
    }
    private readonly string _path;
    private readonly string _legacyPath;
    private readonly object _gate = new();

    public DurableEventQueue(string directory, string posId)
    {
        if (string.IsNullOrWhiteSpace(posId) || posId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || posId is "." or "..")
            throw new ArgumentException("Invalid terminal ID", nameof(posId));
        Directory.CreateDirectory(directory);
        _path = Path.Combine(directory, posId + ".jsonl");
        _legacyPath = Path.Combine(directory, posId + ".json");
        ReadState(); // Fail visibly on corruption; never discard a valid pending event.
    }

    public int Count => ReadState().Pending.Count;
    public IReadOnlyList<Rejection> Rejected => ReadState().Rejected.ToArray();

    public void Enqueue(string body, QueueDelivery delivery = QueueDelivery.Gateway, string? certificatePosId = null)
    {
        lock (_gate)
        {
            using var file = OpenJournal();
            Load(file);
            Append(file, new JournalRecord("enqueue", new Entry(Guid.NewGuid().ToString("N"), body, delivery, certificatePosId)));
        }
    }

    public async Task DrainAsync(Func<Entry, Task<PosResult>> send, Action<string, PosResult>? completed = null)
    {
        FileStream lease;
        try { lease = new FileStream(_path + ".sender.lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException error) when ((error.HResult & 0xffff) is 32 or 33) { return; }
        using (lease)
        {
            while (true)
            {
                var entry = ReadState().Pending.FirstOrDefault();
                if (entry is null) return;
                var result = await send(entry);
                if (result.HttpStatus == 503 || !result.IsSuccess && (result.CanRetry || result.Outcome != PosOutcome.REJECTED)) return;
                lock (_gate)
                {
                    using var file = OpenJournal();
                    var state = Load(file);
                    if (state.Pending.FirstOrDefault()?.Id != entry.Id)
                        throw new InvalidDataException("Queue head changed while sending");
                    Append(file, new JournalRecord("settle", Id: entry.Id,
                        Rejection: result.IsSuccess ? null : new Rejection(entry.Body, result.Code, result.Message)));
                }
                completed?.Invoke(entry.Body, result);
            }
        }
    }

    private FileStream OpenJournal()
    {
        // Brief contention with another process is retried; prolonged contention fails without accepting the sale.
        for (var attempt = 0; ; attempt++)
        {
            try { return new FileStream(_path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
            catch (IOException error) when (attempt < 20 && (error.HResult & 0xffff) is 32 or 33)
            { Thread.Sleep(10); }
        }
    }

    private State ReadState()
    {
        lock (_gate)
        {
            using var file = OpenJournal();
            return Load(file);
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
            var record = JsonSerializer.Deserialize<JournalRecord>(line) ?? throw new InvalidDataException("Empty journal record");
            switch (record.Kind)
            {
                case "snapshot" when record.Snapshot is not null: state = record.Snapshot; break;
                case "enqueue" when record.Entry is not null: state.Pending.Add(record.Entry); break;
                case "settle" when state.Pending.FirstOrDefault()?.Id == record.Id:
                    if (record.Rejection is not null) state.Rejected.Add(record.Rejection);
                    state.Pending.RemoveAt(0);
                    break;
                default: throw new InvalidDataException("Invalid queue journal record");
            }
        }
        if (end == 0 && File.Exists(_legacyPath))
        {
            var old = JsonSerializer.Deserialize<LegacyState>(File.ReadAllText(_legacyPath)) ?? throw new InvalidDataException("Invalid legacy queue");
            state.Pending = old.Pending.Select(body => new Entry(Guid.NewGuid().ToString("N"), body)).ToList();
            state.Rejected = old.Rejected;
            Append(file, new JournalRecord("snapshot", Snapshot: state));
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
