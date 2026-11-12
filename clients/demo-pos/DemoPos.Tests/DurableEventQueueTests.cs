using DemoPos.Models;
using DemoPos.Services;
using Xunit;

namespace DemoPos.Tests;

public sealed class DurableEventQueueTests
{
    private static PosResult Result(PosOutcome outcome, int status = 200, bool retry = false) =>
        new() { Outcome = outcome, Code = outcome.ToString(), Message = "test", HttpStatus = status, CanRetry = retry };

    [Fact]
    public async Task RetryKeepsOrderAndBodyAcrossRestart()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        queue.Enqueue("second");
        var sent = new List<string>();
        await queue.DrainAsync(body => { sent.Add(body); return Task.FromResult(Result(PosOutcome.ERROR, 503, true)); });
        Assert.Equal(new[] { "first" }, sent);
        Assert.Equal(2, queue.Count);

        queue = new DurableEventQueue(directory.Path, "POS-1");
        await queue.DrainAsync(body => { sent.Add(body); return Task.FromResult(Result(PosOutcome.OK)); });
        Assert.Equal(new[] { "first", "first", "second" }, sent);
        Assert.Equal(0, queue.Count);
        Assert.Equal(0, new DurableEventQueue(directory.Path, "POS-1").Count);
    }

    [Fact]
    public async Task RejectionIsPersistedAndDuplicateIsRemoved()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("bad");
        queue.Enqueue("duplicate");
        await queue.DrainAsync(body => Task.FromResult(body == "bad"
            ? Result(PosOutcome.REJECTED, 409) : Result(PosOutcome.DUPLICATE)));
        var reloaded = new DurableEventQueue(directory.Path, "POS-1");
        Assert.Equal(0, reloaded.Count);
        Assert.Equal("bad", Assert.Single(reloaded.Rejected).Body);
    }

    [Fact]
    public async Task OnlyOneSenderProcessesATerminalAtATime()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        var entered = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var calls = 0;
        async Task<PosResult> Send(string body)
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
}
