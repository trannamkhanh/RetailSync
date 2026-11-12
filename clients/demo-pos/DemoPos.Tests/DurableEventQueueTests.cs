using DemoPos.Models;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

public sealed class DurableEventQueueTests
{
    private static PosResult Result(PosOutcome outcome, int status = 200, string? code = null) => new()
    {
        Outcome = outcome,
        Code = code ?? outcome.ToString(),
        Message = "test",
        HttpStatus = status,
        CanRetry = status is 0 or 503,
    };

    [Fact]
    public async Task SendsInOrderAndSettlesEveryEvent_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        queue.Enqueue("second");
        queue.Enqueue("third");

        var sent = new List<string>();
        await queue.DrainAsync(entry =>
        {
            sent.Add(entry.Body);
            return Task.FromResult(Result(PosOutcome.OK));
        });

        Assert.Equal(new[] { "first", "second", "third" }, sent);
        Assert.Equal(0, queue.Count);
    }

    [Fact]
    public async Task RetriesAfter503AndKeepsTheHeadInPlace_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        queue.Enqueue("second");

        var sent = new List<string>();
        var firstCycle = await queue.DrainAsync(entry =>
        {
            sent.Add(entry.Body);
            return Task.FromResult(Result(PosOutcome.ERROR, 503, "SERVICE_UNAVAILABLE"));
        });

        Assert.NotNull(firstCycle);
        Assert.Equal(new[] { "first" }, sent);
        Assert.Equal(2, queue.Count);

        await queue.DrainAsync(entry =>
        {
            sent.Add(entry.Body);
            return Task.FromResult(Result(PosOutcome.OK));
        });

        Assert.Equal(new[] { "first", "first", "second" }, sent);
        Assert.Equal(0, queue.Count);
    }

    [Fact]
    public async Task ConnectionErrorIsRetriedToo_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("sale");

        await queue.DrainAsync(_ => Task.FromResult(PosResultParser.NetworkError(
            "NO_ANSWER", "No answer from the middleware.", 5000)));

        Assert.Equal(1, queue.Count);
        Assert.Empty(queue.Rejected);
    }

    [Fact]
    public async Task PermanentFailureMovesAsideAndTheNextEventIsSent_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("no-certificate");
        queue.Enqueue("sale");

        var sent = new List<string>();
        await queue.DrainAsync(entry =>
        {
            sent.Add(entry.Body);
            return Task.FromResult(entry.Body == "no-certificate"
                ? Result(PosOutcome.REJECTED, 400, "HTTP_400")
                : Result(PosOutcome.OK));
        });

        Assert.Equal(new[] { "no-certificate", "sale" }, sent);
        Assert.Equal(0, queue.Count);
        var rejected = Assert.Single(queue.Rejected);
        Assert.Equal("no-certificate", rejected.Body);
        Assert.Equal(400, rejected.HttpStatus);
    }

    [Fact]
    public async Task RejectionIsPersistedAndDuplicateIsRemoved_PB45_5()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("bad");
        queue.Enqueue("duplicate");

        await queue.DrainAsync(entry => Task.FromResult(entry.Body == "bad"
            ? Result(PosOutcome.REJECTED, 409, "CONFLICT")
            : Result(PosOutcome.DUPLICATE)));

        var reloaded = new DurableEventQueue(directory.Path, "POS-1");
        Assert.Equal(0, reloaded.Count);
        Assert.Equal("bad", Assert.Single(reloaded.Rejected).Body);
    }

    [Fact]
    public async Task ResendingTheSameBodyIsDuplicateNotANewTransaction_PB45_5()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        const string body = """{"transaction_id":"TXN-1","event_type":"SALE"}""";
        queue.Enqueue(body);

        var settled = new List<PosResult>();
        var seen = new HashSet<string>();
        await queue.DrainAsync(entry =>
        {
            var duplicate = !seen.Add(entry.Body);
            return Task.FromResult(duplicate ? Result(PosOutcome.DUPLICATE) : Result(PosOutcome.OK));
        }, (_, result) => settled.Add(result));

        // "Gửi lại" re-enqueues the same body: the gateway answers DUPLICATE for the same transaction_id.
        queue.Enqueue(body);
        var resent = new List<string>();
        await queue.DrainAsync(entry =>
        {
            resent.Add(entry.Body);
            return Task.FromResult(Result(PosOutcome.DUPLICATE));
        }, (_, result) => settled.Add(result));

        Assert.Equal(body, Assert.Single(resent));
        Assert.Equal(PosOutcome.OK, settled[0].Outcome);
        Assert.Equal(PosOutcome.DUPLICATE, settled[1].Outcome);
        Assert.Equal(0, queue.Count);
    }

    [Fact]
    public async Task CompactsTheJournalWhenNothingIsWaiting_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("rejected");
        await queue.DrainAsync(_ => Task.FromResult(Result(PosOutcome.REJECTED, 422, "INVALID_EVENT")));

        for (var index = 0; index < 200; index++)
        {
            queue.Enqueue($$"""{"transaction_id":"TXN-{{index}}","event_type":"SALE"}""");
        }

        await queue.DrainAsync(_ => Task.FromResult(Result(PosOutcome.OK)));

        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        Assert.True(new FileInfo(path).Length < 4096, $"journal is {new FileInfo(path).Length} bytes");
        var reloaded = new DurableEventQueue(directory.Path, "POS-1");
        Assert.Equal(0, reloaded.Count);
        Assert.Single(reloaded.Rejected);
    }

    [Fact]
    public async Task ResumesAfterRestartWithTheSameTransactionIds_PB45_7()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("""{"transaction_id":"TXN-A"}""");
        queue.Enqueue("""{"transaction_id":"TXN-B"}""");
        queue.Enqueue("""{"transaction_id":"TXN-C"}""");

        var restarted = new DurableEventQueue(directory.Path, "POS-1");
        var sent = new List<string>();
        await restarted.DrainAsync(entry =>
        {
            sent.Add(entry.Body);
            return Task.FromResult(Result(PosOutcome.OK));
        });

        Assert.Equal(3, sent.Count);
        Assert.StartsWith("{\"transaction_id\":\"TXN-A\"", sent[0], StringComparison.Ordinal);
        Assert.StartsWith("{\"transaction_id\":\"TXN-C\"", sent[2], StringComparison.Ordinal);
        Assert.Equal(0, new DurableEventQueue(directory.Path, "POS-1").Count);
    }

    [Fact]
    public async Task TornTailIsDiscardedButDurableEventsRemain_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("durable");
        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        var committed = File.ReadAllBytes(path);
        File.AppendAllText(path, "{\"Kind\":\"settle\"");

        var recovered = new DurableEventQueue(directory.Path, "POS-1");

        Assert.Equal(committed, File.ReadAllBytes(path));
        Assert.Equal(1, recovered.Count);
        await recovered.DrainAsync(entry =>
        {
            Assert.Equal("durable", entry.Body);
            return Task.FromResult(Result(PosOutcome.DUPLICATE));
        });
        Assert.Equal(0, new DurableEventQueue(directory.Path, "POS-1").Count);
    }

    [Fact]
    public void CompleteCorruptRecordIsNotSilentlyDeleted_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        File.WriteAllText(path, "not-json\n");

        Assert.Throws<System.Text.Json.JsonException>(() => new DurableEventQueue(directory.Path, "POS-1"));
        Assert.Equal("not-json\n", File.ReadAllText(path));
    }

    [Fact]
    public async Task OnlyOneSenderProcessesATerminalAtATime_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;

        async Task<PosResult> Send(DurableEventQueue.Entry body)
        {
            Interlocked.Increment(ref calls);
            entered.SetResult();
            await release.Task;
            return Result(PosOutcome.OK);
        }

        var first = queue.DrainAsync(Send);
        await entered.Task;
        await queue.DrainAsync(Send);
        release.SetResult();
        await first;

        Assert.Equal(1, calls);
        Assert.Equal(0, queue.Count);
    }

    [Fact]
    public async Task SeparateInstancesDoNotLoseEnqueuesOrSendConcurrently_PB45_4()
    {
        using var directory = new TemporaryDirectory();
        var first = new DurableEventQueue(directory.Path, "POS-1");
        var second = new DurableEventQueue(directory.Path, "POS-1");
        first.Enqueue("first");
        second.Enqueue("second");

        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var sent = new List<string>();
        var draining = first.DrainAsync(async entry =>
        {
            sent.Add(entry.Body);
            entered.TrySetResult();
            await release.Task;
            return Result(PosOutcome.OK);
        });

        await entered.Task;
        try
        {
            var secondLease = await second.DrainAsync(_ => throw new Exception("Second sender entered"));
            Assert.Null(secondLease);
            second.Enqueue("third");
        }
        finally
        {
            release.SetResult();
        }

        await draining;
        Assert.Equal(new[] { "first", "second", "third" }, sent);
        Assert.Equal(0, second.Count);
    }
}
