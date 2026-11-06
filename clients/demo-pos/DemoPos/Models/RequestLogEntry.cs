namespace DemoPos.Models;

public enum RequestKind
{
    Pos,
    Monitor,
    Probe,
    Mock,
}

/// <summary>A request log row. It never stores the Authorization header or a bearer token.</summary>
public sealed class RequestLogEntry
{
    public DateTime Time { get; init; } = DateTime.Now;

    public required string Method { get; init; }

    public required string Url { get; init; }

    public int Status { get; init; }

    public double ElapsedMs { get; init; }

    public string RequestBody { get; init; } = string.Empty;

    public string ResponseBody { get; init; } = string.Empty;

    public string? CertificatePosId { get; init; }

    public string Role { get; init; } = "—";

    public string Subject { get; init; } = "—";

    public RequestKind Kind { get; init; }

    public string TimeText => Time.ToString("HH:mm:ss");

    public string StatusText => Status == 0 ? "NO ANSWER" : Status.ToString();

    public string CertificateText => CertificatePosId ?? "none";

    public string IdentityText => $"{Role} / {Subject}";

    public string ElapsedText => $"{ElapsedMs:0} ms";

    public string DetailsText
    {
        get
        {
            var nl = Environment.NewLine;
            return $"TIME      {Time:yyyy-MM-dd HH:mm:ss}{nl}" +
                   $"METHOD    {Method}{nl}" +
                   $"URL       {Url}{nl}" +
                   $"STATUS    {StatusText}{nl}" +
                   $"ELAPSED   {ElapsedMs:0.0} ms{nl}" +
                   $"CERT      {CertificateText}{nl}" +
                   $"IDENTITY  {IdentityText}{nl}{nl}" +
                   $"REQUEST{nl}{RequestBody}{nl}{nl}" +
                   $"RESPONSE{nl}{ResponseBody}";
        }
    }
}

/// <summary>A bounded, thread-safe log of the last 200 calls.</summary>
public sealed class RequestLog
{
    public const int Capacity = 200;

    private readonly List<RequestLogEntry> _entries = new(Capacity + 1);
    private readonly object _gate = new();

    public event EventHandler? Changed;

    public int Count
    {
        get
        {
            lock (_gate)
            {
                return _entries.Count;
            }
        }
    }

    public void Add(RequestLogEntry entry)
    {
        lock (_gate)
        {
            _entries.Insert(0, entry);
            if (_entries.Count > Capacity)
            {
                _entries.RemoveRange(Capacity, _entries.Count - Capacity);
            }
        }

        Changed?.Invoke(this, EventArgs.Empty);
    }

    public IReadOnlyList<RequestLogEntry> Snapshot()
    {
        lock (_gate)
        {
            return _entries.ToList();
        }
    }

    public void Clear()
    {
        lock (_gate)
        {
            _entries.Clear();
        }

        Changed?.Invoke(this, EventArgs.Empty);
    }
}
