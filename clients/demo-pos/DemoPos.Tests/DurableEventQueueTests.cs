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
        await queue.DrainAsync(body => { sent.Add(body.Body); return Task.FromResult(Result(PosOutcome.ERROR, 503, true)); });
        Assert.Equal(new[] { "first" }, sent);
        Assert.Equal(2, queue.Count);

        queue = new DurableEventQueue(directory.Path, "POS-1");
        await queue.DrainAsync(body => { sent.Add(body.Body); return Task.FromResult(Result(PosOutcome.OK)); });
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
        await queue.DrainAsync(body => Task.FromResult(body.Body == "bad"
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
    public async Task SeparateInstancesDoNotLoseEnqueuesOrSendConcurrently()
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
            await second.DrainAsync(_ => throw new Exception("Second sender entered"));
            second.Enqueue("third");
        }
        finally { release.SetResult(); }
        await draining;
        Assert.Equal(new[] { "first", "second", "third" }, sent);
        Assert.Equal(0, second.Count);
    }

    [Fact]
    public async Task TornTailIsDiscardedButDurableEventsRemain()
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
    public void CompleteCorruptRecordIsNotSilentlyDeleted()
    {
        using var directory = new TemporaryDirectory();
        var path = Path.Combine(directory.Path, "POS-1.jsonl");
        File.WriteAllText(path, "not-json\n");
        Assert.Throws<System.Text.Json.JsonException>(() => new DurableEventQueue(directory.Path, "POS-1"));
        Assert.Equal("not-json\n", File.ReadAllText(path));
    }

    [Fact]
    public async Task LegacyStateMigratesOnceAndDoesNotResurrectCompletedEvents()
    {
        using var directory = new TemporaryDirectory();
        File.WriteAllText(Path.Combine(directory.Path, "POS-1.json"),
            """{"Pending":["old-event"],"Rejected":[{"Body":"bad","Code":"CONFLICT","Message":"test"}]}""");
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        Assert.Equal(1, queue.Count);
        await queue.DrainAsync(entry => Task.FromResult(Result(PosOutcome.OK)));
        var restarted = new DurableEventQueue(directory.Path, "POS-1");
        Assert.Equal(0, restarted.Count);
        Assert.Single(restarted.Rejected);
    }

    [Theory]
    [InlineData(QueueDelivery.Gateway, null)]
    [InlineData(QueueDelivery.WrongCertificate, "POS-OTHER")]
    [InlineData(QueueDelivery.NoCertificate, null)]
    [InlineData(QueueDelivery.SkipGateway, null)]
    public async Task DeliveryModeSurvivesRestart(QueueDelivery delivery, string? certificate)
    {
        using var directory = new TemporaryDirectory();
        new DurableEventQueue(directory.Path, "POS-1").Enqueue("original-body", delivery, certificate);
        await new DurableEventQueue(directory.Path, "POS-1").DrainAsync(entry =>
        {
            Assert.Equal("original-body", entry.Body);
            Assert.Equal(delivery, entry.Delivery);
            Assert.Equal(certificate, entry.CertificatePosId);
            return Task.FromResult(Result(PosOutcome.REJECTED, 403));
        });
    }

    [Fact]
    public async Task SenderLeaseIsExclusiveAcrossProcesses()
    {
        using var directory = new TemporaryDirectory();
        var queue = new DurableEventQueue(directory.Path, "POS-1");
        queue.Enqueue("first");
        var script = Path.Combine(directory.Path, "hold-lock.ps1");
        File.WriteAllText(script, """
            param([string]$LockPath)
            $file = [IO.File]::Open($LockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            try {
                [Console]::Out.WriteLine('ready')
                [Console]::Out.Flush()
                [Console]::In.ReadLine() | Out-Null
            } finally { $file.Dispose() }
            """);
        var info = new System.Diagnostics.ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true,
        };
        foreach (var arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                     "-LockPath", Path.Combine(directory.Path, "POS-1.jsonl.sender.lock") })
            info.ArgumentList.Add(arg);
        using var process = System.Diagnostics.Process.Start(info)!;
        try
        {
            Assert.Equal("ready", await process.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(15)));
            await queue.DrainAsync(_ => throw new Exception("Sender ignored other process lease"));
            Assert.Equal(1, queue.Count);
        }
        finally
        {
            await process.StandardInput.WriteLineAsync("release");
            await process.StandardInput.FlushAsync();
            await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
        }
        await queue.DrainAsync(_ => Task.FromResult(Result(PosOutcome.OK)));
        Assert.Equal(0, queue.Count);
    }
}
